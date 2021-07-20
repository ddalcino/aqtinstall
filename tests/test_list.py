import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Generator

import pytest

from aqt.exceptions import ArchiveConnectionError, ArchiveDownloadError, CliInputError
from aqt.helper import Settings
from aqt.installer import Cli
from aqt.metadata import (
    ArchiveId,
    MetadataFactory,
    SimpleSpec,
    Version,
    Versions,
    format_suggested_follow_up,
    show_list,
    suggested_follow_up,
)

Settings.load_settings()


def test_versions():
    versions = Versions(
        [
            (1, [Version("1.1.1"), Version("1.1.2")]),
            (2, [Version("1.2.1"), Version("1.2.2")]),
        ]
    )
    assert (
        str(versions)
        == "[[Version('1.1.1'), Version('1.1.2')], [Version('1.2.1'), Version('1.2.2')]]"
    )
    assert format(versions) == "1.1.1 1.1.2\n1.2.1 1.2.2"
    assert format(versions, "s") == str(versions)
    assert versions.flattened() == [
        Version("1.1.1"),
        Version("1.1.2"),
        Version("1.2.1"),
        Version("1.2.2"),
    ]
    assert isinstance(versions.__iter__(), Generator)
    assert versions.latest() == Version("1.2.2")
    assert versions

    empty_versions = Versions(None)
    assert str(empty_versions) == "[]"
    assert format(empty_versions) == ""
    assert empty_versions.flattened() == []
    assert isinstance(empty_versions.__iter__(), Generator)
    assert empty_versions.latest() is None
    assert not empty_versions

    one_version = Versions(Version("1.2.3"))
    assert str(one_version) == "[[Version('1.2.3')]]"
    assert format(one_version) == "1.2.3"
    assert one_version.flattened() == [Version("1.2.3")]
    assert isinstance(one_version.__iter__(), Generator)
    assert one_version.latest() == Version("1.2.3")
    assert one_version

    with pytest.raises(TypeError) as pytest_wrapped_e:
        format(versions, "x")
    assert pytest_wrapped_e.type == TypeError


MINOR_REGEX = re.compile(r"^\d+\.(\d+)")


@pytest.mark.parametrize(
    "os_name,target,in_file,expect_out_file",
    [
        ("windows", "android", "windows-android.html", "windows-android-expect.json"),
        ("windows", "desktop", "windows-desktop.html", "windows-desktop-expect.json"),
        ("windows", "winrt", "windows-winrt.html", "windows-winrt-expect.json"),
        ("linux", "android", "linux-android.html", "linux-android-expect.json"),
        ("linux", "desktop", "linux-desktop.html", "linux-desktop-expect.json"),
        ("mac", "android", "mac-android.html", "mac-android-expect.json"),
        ("mac", "desktop", "mac-desktop.html", "mac-desktop-expect.json"),
        ("mac", "ios", "mac-ios.html", "mac-ios-expect.json"),
    ],
)
def test_list_versions_tools(monkeypatch, os_name, target, in_file, expect_out_file):
    _html = (Path(__file__).parent / "data" / in_file).read_text("utf-8")
    monkeypatch.setattr(MetadataFactory, "fetch_http", lambda self, _: _html)

    expected = json.loads(
        (Path(__file__).parent / "data" / expect_out_file).read_text("utf-8")
    )

    # Test 'aqt list tools'
    tools = MetadataFactory(ArchiveId("tools", os_name, target)).getList()
    assert tools == expected["tools"]

    for qt in ("qt5", "qt6"):
        for ext, expected_output in expected[qt].items():
            # Test 'aqt list qt'
            archive_id = ArchiveId(qt, os_name, target, ext if ext != "qt" else "")
            all_versions = MetadataFactory(archive_id).getList()

            if len(expected_output) == 0:
                assert not all_versions
            else:
                assert f"{all_versions}" == "\n".join(expected_output)

            # Filter for the latest version only
            latest_ver = MetadataFactory(archive_id, is_latest_version=True).getList()

            if len(expected_output) == 0:
                assert not latest_ver
            else:
                assert f"{latest_ver}" == expected_output[-1].split(" ")[-1]

            for row in expected_output:
                minor = int(MINOR_REGEX.search(row).group(1))

                # Find the latest version for a particular minor version
                latest_ver_for_minor = MetadataFactory(
                    archive_id,
                    filter_minor=minor,
                    is_latest_version=True,
                ).getList()
                assert f"{latest_ver_for_minor}" == row.split(" ")[-1]

                # Find all versions for a particular minor version
                all_ver_for_minor = MetadataFactory(
                    archive_id,
                    filter_minor=minor,
                ).getList()
                assert f"{all_ver_for_minor}" == row


@pytest.mark.parametrize(
    "version,extension,in_file,expect_out_file",
    [
        ("5.14.0", "", "windows-5140-update.xml", "windows-5140-expect.json"),
        ("5.15.0", "", "windows-5150-update.xml", "windows-5150-expect.json"),
        (
            "5.15.2",
            "src_doc_examples",
            "windows-5152-src-doc-example-update.xml",
            "windows-5152-src-doc-example-expect.json",
        ),
    ],
)
def test_list_architectures_and_modules(
    monkeypatch, version: str, extension: str, in_file: str, expect_out_file: str
):
    archive_id = ArchiveId("qt" + version[0], "windows", "desktop", extension)
    _xml = (Path(__file__).parent / "data" / in_file).read_text("utf-8")
    expect = json.loads(
        (Path(__file__).parent / "data" / expect_out_file).read_text("utf-8")
    )

    monkeypatch.setattr(MetadataFactory, "fetch_http", lambda self, _: _xml)

    modules = MetadataFactory(archive_id).fetch_modules(Version(version))
    assert modules == expect["modules"]

    arches = MetadataFactory(archive_id).fetch_arches(Version(version))
    assert arches == expect["architectures"]


@pytest.mark.parametrize(
    "host, target, tool_name",
    [
        ("mac", "desktop", "tools_cmake"),
        ("mac", "desktop", "tools_ifw"),
        ("mac", "desktop", "tools_qtcreator"),
    ],
)
def test_tool_modules(monkeypatch, host: str, target: str, tool_name: str):
    archive_id = ArchiveId("tools", host, target)
    in_file = "{}-{}-{}-update.xml".format(host, target, tool_name)
    expect_out_file = "{}-{}-{}-expect.json".format(host, target, tool_name)
    _xml = (Path(__file__).parent / "data" / in_file).read_text("utf-8")
    expect = json.loads(
        (Path(__file__).parent / "data" / expect_out_file).read_text("utf-8")
    )

    monkeypatch.setattr(MetadataFactory, "fetch_http", lambda self, _: _xml)

    modules = MetadataFactory(archive_id, tool_name=tool_name).getList()
    assert modules == expect["modules"]

    table = MetadataFactory(archive_id, tool_long_listing=tool_name).getList()
    assert table._rows() == expect["long_listing"]


@pytest.mark.parametrize(
    "cat, host, target, minor_ver, ver, ext, xmlfile, xmlexpect, htmlfile, htmlexpect",
    [
        (
            "qt5",
            "windows",
            "desktop",
            "14",
            "5.14.0",
            "wasm",
            "windows-5140-update.xml",
            "windows-5140-expect.json",
            "windows-desktop.html",
            "windows-desktop-expect.json",
        ),
    ],
)
def test_list_cli(
    capsys,
    monkeypatch,
    cat,
    host,
    target,
    minor_ver,
    ver,
    ext,
    xmlfile,
    xmlexpect,
    htmlfile,
    htmlexpect,
):
    def _mock(_, rest_of_url: str) -> str:
        in_file = xmlfile if rest_of_url.endswith("Updates.xml") else htmlfile
        text = (Path(__file__).parent / "data" / in_file).read_text("utf-8")
        if not rest_of_url.endswith("Updates.xml"):
            return text

        # If we are serving an Updates.xml, `aqt list` will look for a Qt version number.
        # We will replace the version numbers in the file with the requested version.
        match = re.search(r"qt\d_(\d+)", rest_of_url)
        assert match
        desired_version = match.group(1)
        ver_to_replace = ver.replace(".", "")
        return text.replace(ver_to_replace, desired_version)

    monkeypatch.setattr(MetadataFactory, "fetch_http", _mock)

    expected_modules_arches = json.loads(
        (Path(__file__).parent / "data" / xmlexpect).read_text("utf-8")
    )
    expect_modules = expected_modules_arches["modules"]
    expect_arches = expected_modules_arches["architectures"]

    def check_extensions():
        out, err = capsys.readouterr()
        # We should probably generate expected from htmlexpect, but this will work for now
        assert out.strip() == "wasm src_doc_examples"

    def check_modules():
        out, err = capsys.readouterr()
        assert set(out.strip().split()) == set(expect_modules)

    def check_arches():
        out, err = capsys.readouterr()
        assert set(out.strip().split()) == set(expect_arches)

    _minor = ["--filter-minor", minor_ver]
    _ext = ["--extension", ext]

    cli = Cli()
    # Query extensions by latest version, minor version, and specific version
    cli.run(["list", cat, host, target, "--extensions", "latest"])
    check_extensions()
    cli.run(["list", cat, host, target, *_minor, "--extensions", "latest"])
    check_extensions()
    cli.run(["list", cat, host, target, "--extensions", ver])
    check_extensions()
    # Query modules by latest version, minor version, and specific version
    cli.run(["list", cat, host, target, "--modules", "latest"])
    check_modules()
    cli.run(["list", cat, host, target, *_minor, "--modules", "latest"])
    check_modules()
    cli.run(["list", cat, host, target, "--modules", ver])
    check_modules()
    cli.run(["list", cat, host, target, *_ext, "--modules", "latest"])
    check_modules()
    cli.run(["list", cat, host, target, *_ext, *_minor, "--modules", "latest"])
    check_modules()
    cli.run(["list", cat, host, target, *_ext, "--modules", ver])
    check_modules()
    # Query architectures by latest version, minor version, and specific version
    cli.run(["list", cat, host, target, "--arch", "latest"])
    check_arches()
    cli.run(["list", cat, host, target, *_minor, "--arch", "latest"])
    check_arches()
    cli.run(["list", cat, host, target, "--arch", ver])
    check_arches()
    cli.run(["list", cat, host, target, *_ext, "--arch", "latest"])
    check_arches()
    cli.run(["list", cat, host, target, *_ext, *_minor, "--arch", "latest"])
    check_arches()
    cli.run(["list", cat, host, target, *_ext, "--arch", ver])
    check_arches()


@pytest.mark.parametrize(
    "simple_spec, expected_name",
    (
        (SimpleSpec("*"), "mytool.999"),
        (SimpleSpec(">3.5"), "mytool.999"),
        (SimpleSpec("3.5.5"), "mytool.355"),
        (SimpleSpec("<3.5"), "mytool.300"),
        (SimpleSpec("<=3.5"), "mytool.355"),
        (SimpleSpec("<=3.5.0"), "mytool.350"),
        (SimpleSpec(">10"), None),
    ),
)
def test_list_choose_tool_by_version(simple_spec, expected_name):
    tools_data = {
        "mytool.999": {"Version": "9.9.9", "Name": "mytool.999"},
        "mytool.355": {"Version": "3.5.5", "Name": "mytool.355"},
        "mytool.350": {"Version": "3.5.0", "Name": "mytool.350"},
        "mytool.300": {"Version": "3.0.0", "Name": "mytool.300"},
    }
    item = MetadataFactory.choose_highest_version_in_spec(tools_data, simple_spec)
    if item is not None:
        assert item["Name"] == expected_name
    else:
        assert expected_name is None


qt6_android_requires_ext_msg = (
    "Qt 6 for Android requires one of the following extensions: "
    f"{ArchiveId.EXTENSIONS_REQUIRED_ANDROID_QT6}. "
    "Please add your extension using the `--extension` flag."
)
no_arm64_v8_msg = "The extension 'arm64_v8a' is only valid for Qt 6 for Android"
no_wasm_msg = "The extension 'wasm' is only available in Qt 5.13 to 5.15 on desktop."


@pytest.mark.parametrize(
    "target, ext, version, expected_msg",
    (
        ("android", "", "6.2.0", qt6_android_requires_ext_msg),
        ("android", "arm64_v8a", "5.13.0", no_arm64_v8_msg),
        ("desktop", "arm64_v8a", "5.13.0", no_arm64_v8_msg),
        ("desktop", "arm64_v8a", "6.2.0", no_arm64_v8_msg),
        ("desktop", "wasm", "5.12.11", no_wasm_msg),  # out of range
        ("desktop", "wasm", "6.2.0", no_wasm_msg),  # out of range
        ("android", "wasm", "5.12.11", no_wasm_msg),  # in range, wrong target
        ("android", "wasm", "5.14.0", no_wasm_msg),  # in range, wrong target
        ("android", "wasm", "6.2.0", qt6_android_requires_ext_msg),
    ),
)
def test_list_invalid_extensions(
    capsys, monkeypatch, target, ext, version, expected_msg
):
    def _mock(_, rest_of_url: str) -> str:
        return ""

    monkeypatch.setattr(MetadataFactory, "fetch_http", _mock)

    cat = "qt" + version[0]
    host = "windows"
    extension_params = ["--extension", ext] if ext else []
    cli = Cli()
    cli.run(["list", cat, host, target, *extension_params, "--arch", version])
    out, err = capsys.readouterr()
    sys.stdout.write(out)
    sys.stderr.write(err)
    assert expected_msg in err


mac_qt5 = ArchiveId("qt5", "mac", "desktop")
mac_wasm = ArchiveId("qt5", "mac", "desktop", "wasm")
wrong_qt_version_msg = [
    "Please use 'aqt list qt5 mac desktop' to show versions of Qt available."
]
wrong_ext_and_version_msg = [
    "Please use 'aqt list qt5 mac desktop --extensions <QT_VERSION>' to list valid extensions.",
    "Please use 'aqt list qt5 mac desktop' to show versions of Qt available.",
]


@pytest.mark.parametrize(
    "meta, expected_message",
    (
        (MetadataFactory(mac_qt5), []),
        (
            MetadataFactory(mac_qt5, filter_minor=0),
            [
                "Please use 'aqt list qt5 mac desktop' to check that versions of qt5 exist with the minor version '0'."
            ],
        ),
        (
            MetadataFactory(ArchiveId("tools", "mac", "desktop"), tool_name="ifw"),
            [
                "Please use 'aqt list tools mac desktop' to check what tools are available."
            ],
        ),
        (
            MetadataFactory(mac_qt5, architectures_ver="1.2.3"),
            wrong_qt_version_msg,
        ),
        (
            MetadataFactory(mac_qt5, modules_ver="1.2.3"),
            wrong_qt_version_msg,
        ),
        (
            MetadataFactory(mac_qt5, extensions_ver="1.2.3"),
            wrong_qt_version_msg,
        ),
        (
            MetadataFactory(mac_wasm),
            [
                "Please use 'aqt list qt5 mac desktop --extensions <QT_VERSION>' to list valid extensions."
            ],
        ),
        (
            MetadataFactory(mac_wasm, filter_minor=0),
            [
                "Please use 'aqt list qt5 mac desktop --extensions <QT_VERSION>' to list valid extensions.",
                "Please use 'aqt list qt5 mac desktop' to check that versions of qt5 exist with the minor version '0'.",
            ],
        ),
        (
            MetadataFactory(
                ArchiveId("tools", "mac", "desktop", "wasm"), tool_name="ifw"
            ),
            [
                "Please use 'aqt list tools mac desktop --extensions <QT_VERSION>' to list valid extensions.",
                "Please use 'aqt list tools mac desktop' to check what tools are available.",
            ],
        ),
        (
            MetadataFactory(mac_wasm, architectures_ver="1.2.3"),
            wrong_ext_and_version_msg,
        ),
        (
            MetadataFactory(mac_wasm, modules_ver="1.2.3"),
            wrong_ext_and_version_msg,
        ),
        (
            MetadataFactory(mac_wasm, extensions_ver="1.2.3"),
            wrong_ext_and_version_msg,
        ),
    ),
)
def test_suggested_follow_up(meta: MetadataFactory, expected_message: str):
    assert suggested_follow_up(meta) == expected_message


def test_format_suggested_follow_up():
    suggestions = [
        "Please use 'aqt list tools mac desktop --extensions <QT_VERSION>' to list valid extensions.",
        "Please use 'aqt list tools mac desktop' to check what tools are available.",
    ]
    expected = (
        "==============================Suggested follow-up:==============================\n"
        "* Please use 'aqt list tools mac desktop --extensions <QT_VERSION>' to list valid extensions.\n"
        "* Please use 'aqt list tools mac desktop' to check what tools are available."
    )

    assert format_suggested_follow_up(suggestions) == expected


def test_format_suggested_follow_up_empty():
    assert format_suggested_follow_up([]) == ""


@pytest.mark.parametrize(
    "meta, expect",
    (
        (
            MetadataFactory(ArchiveId("qt5", "mac", "desktop"), filter_minor=42),
            "qt5/mac/desktop with minor version 42",
        ),
        (
            MetadataFactory(
                ArchiveId("qt5", "mac", "desktop", "wasm"), filter_minor=42
            ),
            "qt5/mac/desktop/wasm with minor version 42",
        ),
        (MetadataFactory(ArchiveId("qt5", "mac", "desktop")), "qt5/mac/desktop"),
        (
            MetadataFactory(ArchiveId("qt5", "mac", "desktop", "wasm")),
            "qt5/mac/desktop/wasm",
        ),
    ),
)
def test_list_describe_filters(meta: MetadataFactory, expect: str):
    assert meta.describe_filters() == expect


@pytest.mark.parametrize(
    "archive_id, filter_minor, version_str, expect",
    (
        (mac_qt5, None, "5.12.42", Version("5.12.42")),
        (
            mac_qt5,
            None,
            "6.12.42",
            CliInputError("Major version mismatch between qt5 and 6.12.42"),
        ),
        (
            mac_qt5,
            None,
            "not a version",
            CliInputError("Invalid version string: 'not a version'"),
        ),
        (mac_qt5, None, "latest", Version("5.15.2")),
        (
            mac_qt5,
            0,
            "latest",
            CliInputError(
                "There is no latest version of Qt with the criteria 'qt5/mac/desktop with minor version 0'"
            ),
        ),
    ),
)
def test_list_to_version(monkeypatch, archive_id, filter_minor, version_str, expect):
    _html = (Path(__file__).parent / "data" / "mac-desktop.html").read_text("utf-8")
    monkeypatch.setattr(MetadataFactory, "fetch_http", lambda self, _: _html)

    if isinstance(expect, Exception):
        with pytest.raises(CliInputError) as error:
            MetadataFactory(archive_id, filter_minor=filter_minor)._to_version(
                version_str
            )
        assert error.type == CliInputError
        assert str(expect) == str(error.value)
    else:
        assert (
            MetadataFactory(archive_id, filter_minor=filter_minor)._to_version(
                version_str
            )
            == expect
        )


def test_list_fetch_tool_by_simple_spec(monkeypatch):
    update_xml = (
        Path(__file__).parent / "data" / "windows-desktop-tools_vcredist-update.xml"
    ).read_text("utf-8")
    monkeypatch.setattr(MetadataFactory, "fetch_http", lambda self, _: update_xml)

    expect_json = (
        Path(__file__).parent / "data" / "windows-desktop-tools_vcredist-expect.json"
    ).read_text("utf-8")
    expected = json.loads(expect_json)["modules_data"]

    def check(actual, expect):
        for key in (
            "Description",
            "DisplayName",
            "DownloadableArchives",
            "ReleaseDate",
            "SHA1",
            "Version",
            "Virtual",
        ):
            assert actual[key] == expect[key]

    meta = MetadataFactory(ArchiveId("tools", "windows", "desktop"))
    check(
        meta.fetch_tool_by_simple_spec(
            tool_name="tools_vcredist", simple_spec=SimpleSpec("2011")
        ),
        expected["qt.tools.vcredist"],
    )
    check(
        meta.fetch_tool_by_simple_spec(
            tool_name="tools_vcredist", simple_spec=SimpleSpec("2014")
        ),
        expected["qt.tools.vcredist_msvc2013_x86"],
    )
    nonexistent = meta.fetch_tool_by_simple_spec(
        tool_name="tools_vcredist", simple_spec=SimpleSpec("1970")
    )
    assert nonexistent is None

    # Simulate a broken Updates.xml file, with invalid versions
    highest_module_info = MetadataFactory.choose_highest_version_in_spec(
        all_tools_data={"some_module": {"Version": "not_a_version"}},
        simple_spec=SimpleSpec("*"),
    )
    assert highest_module_info is None


@pytest.mark.parametrize(
    "columns, expect",
    (
        (
            120,
            (
                "Tool Variant Name        Version         Release Date          Display Name          "
                "            Description            \n"
                "====================================================================================="
                "===================================\n"
                "qt.tools.ifw.41     4.1.1-202105261132   2021-05-26     Qt Installer Framework 4.1   "
                "The Qt Installer Framework provides\n"
                "                                                                                     "
                "a set of tools and utilities to    \n"
                "                                                                                     "
                "create installers for the supported\n"
                "                                                                                     "
                "desktop Qt platforms: Linux,       \n"
                "                                                                                     "
                "Microsoft Windows, and macOS.      \n"
            ),
        ),
        (
            80,
            "Tool Variant Name        Version         Release Date\n"
            "=====================================================\n"
            "qt.tools.ifw.41     4.1.1-202105261132   2021-05-26  \n",
        ),
        (
            0,
            "Tool Variant Name        Version         Release Date          Display Name          "
            "                                                                           Descriptio"
            "n                                                                            \n"
            "====================================================================================="
            "====================================================================================="
            "=============================================================================\n"
            "qt.tools.ifw.41     4.1.1-202105261132   2021-05-26     Qt Installer Framework 4.1   "
            "The Qt Installer Framework provides a set of tools and utilities to create installers"
            " for the supported desktop Qt platforms: Linux, Microsoft Windows, and macOS.\n",
        ),
    ),
)
def test_show_list_tools_long_ifw(capsys, monkeypatch, columns, expect):
    update_xml = (
        Path(__file__).parent / "data" / "mac-desktop-tools_ifw-update.xml"
    ).read_text("utf-8")
    monkeypatch.setattr(MetadataFactory, "fetch_http", lambda self, _: update_xml)

    monkeypatch.setattr(
        shutil, "get_terminal_size", lambda fallback: os.terminal_size((columns, 24))
    )

    meta = MetadataFactory(
        ArchiveId("tools", "mac", "desktop"), tool_long_listing="tools_ifw"
    )
    assert show_list(meta) == 0
    out, err = capsys.readouterr()
    sys.stdout.write(out)
    sys.stderr.write(err)
    assert out == expect


def test_show_list_versions(monkeypatch, capsys):
    _html = (Path(__file__).parent / "data" / "mac-desktop.html").read_text("utf-8")
    monkeypatch.setattr(MetadataFactory, "fetch_http", lambda *args: _html)

    expect_file = Path(__file__).parent / "data" / "mac-desktop-expect.json"
    expected = "\n".join(json.loads(expect_file.read_text("utf-8"))["qt5"]["qt"]) + "\n"

    assert show_list(MetadataFactory(mac_qt5)) == 0
    out, err = capsys.readouterr()
    assert out == expected


def test_show_list_tools(monkeypatch, capsys):
    page = (Path(__file__).parent / "data" / "mac-desktop.html").read_text("utf-8")
    monkeypatch.setattr(MetadataFactory, "fetch_http", lambda self, _: page)

    expect_file = Path(__file__).parent / "data" / "mac-desktop-expect.json"
    expect = "\n".join(json.loads(expect_file.read_text("utf-8"))["tools"]) + "\n"

    meta = MetadataFactory(ArchiveId("tools", "mac", "desktop"))
    assert show_list(meta) == 0
    out, err = capsys.readouterr()
    sys.stdout.write(out)
    sys.stderr.write(err)
    assert out == expect


def test_fetch_http_ok(monkeypatch):
    monkeypatch.setattr("aqt.metadata.getUrl", lambda **kwargs: "some_html_content")
    assert MetadataFactory.fetch_http("some_url") == "some_html_content"


def test_fetch_http_failover(monkeypatch):
    urls_requested = set()

    def _mock(url, **kwargs):
        urls_requested.add(url)
        if len(urls_requested) <= 1:
            raise ArchiveDownloadError()
        return "some_html_content"

    monkeypatch.setattr("aqt.metadata.getUrl", _mock)

    # Require that the first attempt failed, but the second did not
    assert MetadataFactory.fetch_http("some_url") == "some_html_content"
    assert len(urls_requested) == 2


def test_fetch_http_download_error(monkeypatch):
    urls_requested = set()

    def _mock(url, **kwargs):
        urls_requested.add(url)
        raise ArchiveDownloadError()

    monkeypatch.setattr("aqt.metadata.getUrl", _mock)
    with pytest.raises(ArchiveDownloadError) as e:
        MetadataFactory.fetch_http("some_url")
    assert e.type == ArchiveDownloadError

    # Require that a fallback url was tried
    assert len(urls_requested) == 2


def test_fetch_http_conn_error(monkeypatch):
    urls_requested = set()

    def _mock(url, **kwargs):
        urls_requested.add(url)
        raise ArchiveConnectionError()

    monkeypatch.setattr("aqt.metadata.getUrl", _mock)
    with pytest.raises(ArchiveConnectionError) as e:
        MetadataFactory.fetch_http("some_url")
    assert e.type == ArchiveConnectionError

    # Require that a fallback url was tried
    assert len(urls_requested) == 2
