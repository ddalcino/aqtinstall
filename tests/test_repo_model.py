from typing import Dict, List

import pytest

from aqt.repo_model import RepoModel, SchemaError


@pytest.fixture
def repo_json() -> str:
    return """
{
  "qtdesignstudio": {
    "default": {
      "args": ["semver", "host"],
      "host-to-arch": {
        "windows": "windows-x86",
        "mac": "mac-x86_64",
        "linux": "linux-x86_64"
      },
      "host-to-file_ext": {
        "windows": "exe",
        "mac": "dmg",
        "linux": "run"
      },
      "url_template": "{semver}/qt-designstudio-{arch}-{semver}-community.{file_ext}"
    },
    "alt": {
      "args": ["semver", "file_ext"],
      "allowed_values": {"file_ext": ["1", "txt", "zip"]},
      "url_template": "{major_minor_semver}/{semver_underscores}/qt-designstudio.{file_ext}"
    }
  },
  "qt-installer-framework": {
    "binary": {
      "args": ["semver", "host", "bits"],
      "host-to-arch": {
        "mac": {
          "semver-to-arch": {">=4.1": "macOS-x86_64", "<4.1": "mac-x64"}
        },
        "windows": {
          "bits-to-arch": {
            "64": {"semver-to-arch": {">=4.1": "Windows-x86_64", "<4.1": "win-x64"}},
            "32": {"semver-to-arch": {">=4.1": "Windows-x86", "<4.1": "win32"}}
          }
        },
        "linux": "linux-x64"
      },
      "url_template": "{semver}/QtInstallerFramework-{arch}.zip"
    }
  }
}
"""


@pytest.mark.parametrize(
    "description, tool_name, schema, args, expected_url",
    (
        (
            "Conversion of semantic version to alternate formats",
            "qtdesignstudio",
            "alt",
            {"semver": "1.2.6", "file_ext": "txt"},
            "1.2/1_2_6/qt-designstudio.txt",
        ),
        (
            "Derivation of variables from one other variable",
            "qtdesignstudio",
            "default",
            {"semver": "1.2.6", "host": "windows"},
            "1.2.6/qt-designstudio-windows-x86-1.2.6-community.exe",
        ),
        (
            "Derivation of variables from two other variables-1",
            "qt-installer-framework",
            "binary",
            {"semver": "4.1.0", "host": "mac", "bits": "64"},
            "4.1.0/QtInstallerFramework-macOS-x86_64.zip",
        ),
        (
            "Derivation of variables from two other variables-2",
            "qt-installer-framework",
            "binary",
            {"semver": "4.0.9", "host": "mac", "bits": "64"},
            "4.0.9/QtInstallerFramework-mac-x64.zip",
        ),
        (
            "Recursive derivation of variables from three variables-1",
            "qt-installer-framework",
            "binary",
            {"semver": "4.0.9", "host": "windows", "bits": "64"},
            "4.0.9/QtInstallerFramework-win-x64.zip",
        ),
        (
            "Recursive derivation of variables from three variables-2",
            "qt-installer-framework",
            "binary",
            {"semver": "4.0.9", "host": "windows", "bits": "32"},
            "4.0.9/QtInstallerFramework-win32.zip",
        ),
        (
            "Recursive derivation of variables from three variables-3",
            "qt-installer-framework",
            "binary",
            {"semver": "4.1.9", "host": "windows", "bits": "64"},
            "4.1.9/QtInstallerFramework-Windows-x86_64.zip",
        ),
        (
            "Recursive derivation of variables from three variables-4",
            "qt-installer-framework",
            "binary",
            {"semver": "4.1.9", "host": "windows", "bits": "32"},
            "4.1.9/QtInstallerFramework-Windows-x86.zip",
        ),
    ),
)
def test_repo_model_structure(repo_json, description: str, tool_name: str, schema: str, args: Dict, expected_url: str):
    schema = RepoModel(repo_json).get_schema(tool_name, schema)
    actual_url = schema.fill_template(args)
    assert expected_url == actual_url


@pytest.mark.parametrize(
    "tool_name, schema, args_key, expected_values",
    (
        ("qtdesignstudio", "alt", "file_ext", ["1", "txt", "zip"]),
        ("qtdesignstudio", "alt", "host", ["windows", "linux", "mac"]),
    ),
)
def test_repo_model_allowed_values(repo_json, tool_name: str, schema: str, args_key: str, expected_values: List[str]):
    schema = RepoModel(repo_json).get_schema(tool_name, schema)
    assert expected_values == schema.list_allowed_values_for(args_key)


def test_repo_model_list_tool_names(repo_json):
    assert ["qtdesignstudio", "qt-installer-framework"] == RepoModel(repo_json).list_tool_names()


def test_repo_model_list_schemas(repo_json):
    assert ["default", "alt"] == RepoModel(repo_json).list_schemas("qtdesignstudio")


@pytest.mark.parametrize(
    "expected_error_msg, repo_def",
    (
        (
            "Schema contains unrecognized key",
            """{ "qtdesignstudio": { "default": {
                      "args": [],
                      "unrecognized_key": {},
                      "url_template": ""
                }}}""",
        ),
        (
            "Schema contains no resolution for version 1.0.0",
            """{ "qtdesignstudio": { "default": {
                      "args": ["semver"],
                      "semver-to-ext": { ">1.0.0": "" },
                      "url_template": ""
                }}}""",
        ),
        (
            "Translator object is neither a string nor a dictionary",
            """{ "qtdesignstudio": { "default": {
                      "args": ["semver"],
                      "semver-to-ext": {"1.0.0": []},
                      "url_template": ""
                }}}""",
        ),
    ),
)
def test_repo_model_bad_schemas(expected_error_msg, repo_def):
    model = RepoModel(repo_def)
    with pytest.raises(SchemaError) as e:
        model.get_schema("qtdesignstudio", "default").fill_template({"semver": "1.0.0"})
    assert expected_error_msg == str(e.value)
