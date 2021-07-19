#!/usr/bin/env python3

import argparse
import json
import logging
import os
import re
import textwrap
from pathlib import Path
from typing import (
    Callable,
    Dict,
    Generator,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

from git import Repo
from github import Github
from tqdm import tqdm as base_tqdm

from aqt.exceptions import ArchiveConnectionError, ArchiveDownloadError
from aqt.helper import Settings, setup_logging
from aqt.metadata import ArchiveId, MetadataFactory, Versions


def is_blacklisted_tool(tool_name: str) -> bool:
    for prefix in ("tools_qt3dstudio_",):
        if tool_name.startswith(prefix):
            return True
    for suffix in ("_preview", "_early_access"):
        if tool_name.endswith(suffix):
            return True
    return False


def iter_archive_ids(
    *,
    categories: Iterator[str] = ArchiveId.CATEGORIES,
    hosts: Iterator[str] = ArchiveId.HOSTS,
    targets: Optional[Iterator[str]] = None,
    add_extensions: bool = False,
) -> Generator[ArchiveId, None, None]:
    def iter_extensions() -> Generator[str, None, None]:
        if add_extensions:
            if cat == "qt6" and target == "android":
                yield from ("x86_64", "x86", "armv7", "arm64_v8a")
                return
            elif cat == "qt5" and target == "desktop":
                yield from ("wasm", "")
                return
        yield ""

    for cat in categories:
        for host in sorted(hosts):
            use_targets = targets
            if use_targets is None:
                use_targets = ArchiveId.TARGETS_FOR_HOST[host]
            for target in use_targets:
                if target == "winrt" and cat == "qt6":
                    # there is no qt6 for winrt
                    continue
                for ext in iter_extensions():
                    yield ArchiveId(cat, host, target, ext)


def iter_arches() -> Generator[dict, None, None]:
    logger.info("Fetching arches")
    archive_ids = list(iter_archive_ids(categories=("qt5", "qt6"), add_extensions=True))
    for archive_id in tqdm(archive_ids):
        versions = (
            ("latest",)
            if archive_id.category == "qt6"
            else ("latest", "5.13.2", "5.9.9")
        )
        for version in versions:
            if version == "5.9.9" and archive_id.extension == "wasm":
                continue
            for arch_name in MetadataFactory(
                archive_id, architectures_ver=version
            ).getList():
                yield {
                    "os_name": archive_id.host,
                    "target": archive_id.target,
                    "arch": arch_name,
                }


def iter_tool_variants() -> Generator[dict, None, None]:
    for archive_id in iter_archive_ids(categories=("tools",)):
        logger.info("Fetching tool variants for {}".format(archive_id))
        for tool_name in tqdm(sorted(MetadataFactory(archive_id).getList())):
            if is_blacklisted_tool(tool_name):
                continue
            for tool_variant in MetadataFactory(
                archive_id, tool_name=tool_name
            ).getList():
                yield {
                    "os_name": archive_id.host,
                    "target": archive_id.target,
                    "tool_name": tool_name,
                    "arch": tool_variant,
                }


def iter_qt_minor_groups(
    host: str = "linux", target: str = "desktop"
) -> Generator[Tuple[int, int], None, None]:
    for cat in (
        "qt5",
        "qt6",
    ):
        versions: Versions = MetadataFactory(ArchiveId(cat, host, target)).getList()
        for minor_group in versions:
            v = minor_group[0]
            yield v.major, v.minor


def iter_modules_for_qt_minor_groups(
    host: str = "linux", target: str = "desktop"
) -> Generator[Dict, None, None]:
    logger.info("Fetching qt modules for {}/{}".format(host, target))
    for major, minor in tqdm(list(iter_qt_minor_groups(host, target))):
        cat = f"qt{major}"
        yield {
            "qt_version": f"{major}.{minor}",
            "modules": MetadataFactory(
                ArchiveId(cat, host, target), modules_ver=f"{major}.{minor}.0"
            ).getList(),
        }


def list_qt_versions(host: str = "linux", target: str = "desktop") -> List[str]:
    all_versions = list()
    for cat in (
        "qt5",
        "qt6",
    ):
        versions: Versions = MetadataFactory(ArchiveId(cat, host, target)).getList()
        for minor_group in versions:
            all_versions.extend([str(ver) for ver in minor_group])
    return all_versions


def merge_records(arch_records) -> List[Dict]:
    all_records: List[Dict] = []
    hashes = set()
    for record in arch_records:
        _hash = record["os_name"], record["target"], record["arch"]
        if _hash not in hashes:
            all_records.append(record)
            hashes.add(_hash)
    for sorting_key in ("arch", "target", "os_name"):
        all_records = sorted(all_records, key=lambda d: d[sorting_key])
    return all_records


def generate_combos(new_archive: List[str]):
    return {
        "qt": merge_records(iter_arches()),
        "tools": list(iter_tool_variants()),
        "modules": list(iter_modules_for_qt_minor_groups()),
        "versions": list_qt_versions(),
        "new_archive": new_archive,
    }


def pretty_print_combos(combos: Dict[str, Union[List[Dict], List[str]]]) -> str:
    """
    Attempts to mimic the formatting of the existing combinations.json.
    """

    def fmt_dict_entry(entry: Dict, depth: int) -> str:
        return '{}{{"os_name": {:<10} "target": {:<10} {}"arch": "{}"}}'.format(
            "  " * depth,
            f'"{entry["os_name"]}",',
            f'"{entry["target"]}",',
            (
                f'"tool_name": "{entry["tool_name"]}", '
                if "tool_name" in entry.keys()
                else ""
            ),
            entry["arch"],
        )

    def span_multiline(line: str, max_width: int, depth: int) -> str:
        window = (0, max_width)
        indent = "  " * (depth + 1)
        while len(line) - window[0] > max_width:
            break_loc = line.rfind(" ", window[0], window[1])
            line = line[:break_loc] + "\n" + indent + line[break_loc + 1 :]
            window = (break_loc + len(indent), break_loc + len(indent) + max_width)
        return line

    def fmt_module_entry(entry: Dict, depth: int = 0) -> str:
        line = '{}{{"qt_version": "{}", "modules": [{}]}}'.format(
            "  " * depth,
            entry["qt_version"],
            ", ".join([f'"{s}"' for s in entry["modules"]]),
        )
        return span_multiline(line, 120, depth)

    def fmt_version_list(entry: List[str], depth: int) -> str:
        assert isinstance(entry, list)
        minor_pattern = re.compile(r"^\d+\.(\d+)(\.\d+)?")

        def iter_minor_versions():
            if len(entry) == 0:
                return
            begin_index = 0
            current_minor_ver = int(minor_pattern.match(entry[begin_index]).group(1))
            for i, ver in enumerate(entry):
                minor = int(minor_pattern.match(ver).group(1))
                if minor != current_minor_ver:
                    yield entry[begin_index:i]
                    begin_index = i
                    current_minor_ver = minor
            yield entry[begin_index:]

        joiner = ",\n" + "  " * depth
        line = joiner.join(
            [
                ", ".join([f'"{ver}"' for ver in minor_group])
                for minor_group in iter_minor_versions()
            ]
        )

        return line

    root_element_strings = [
        f'"{key}": [\n'
        + ",\n".join([item_formatter(item, depth=1) for item in combos[key]])
        + "\n]"
        for key, item_formatter in (
            ("qt", fmt_dict_entry),
            ("tools", fmt_dict_entry),
            ("modules", fmt_module_entry),
        )
    ] + [
        f'"{key}": [\n  ' + fmt_version_list(combos[key], depth=1) + "\n]"
        for key in ("versions", "new_archive")
    ]

    return "[{" + ", ".join(root_element_strings) + "}]"


def compare_combos(
    actual_combos: Dict[str, Union[List[str], List[Dict]]],
    expected_combos: Dict[str, Union[List[str], List[Dict]]],
    actual_name: str,
    expect_name: str,
    printer: Callable,
) -> bool:
    # list_of_str_keys: the values attached to these keys are List[str]
    list_of_str_keys = "versions", "new_archive"

    has_difference = False

    # Don't compare data pulled from previous file
    skipped_keys = ("new_archive",)

    def compare_modules_entry(actual_mod_item: Dict, expect_mod_item: Dict) -> bool:
        """Return True if difference detected. Print description of difference."""
        version = actual_mod_item["qt_version"]
        actual_modules, expect_modules = set(actual_mod_item["modules"]), set(
            expect_mod_item["modules"]
        )
        mods_missing_from_actual = expect_modules - actual_modules
        mods_missing_from_expect = actual_modules - expect_modules
        if mods_missing_from_actual:
            printer(
                f"{actual_name}['modules'] for Qt {version} is missing {mods_missing_from_actual}"
            )
        if mods_missing_from_expect:
            printer(
                f"{expect_name}['modules'] for Qt {version} is missing {mods_missing_from_expect}"
            )
        return bool(mods_missing_from_actual) or bool(mods_missing_from_expect)

    def to_set(a_list: Union[List[str], List[Dict]]) -> Set:
        if len(a_list) == 0:
            return set()
        if isinstance(a_list[0], str):
            return set(a_list)
        assert isinstance(a_list[0], Dict)
        return set([str(a_dict) for a_dict in a_list])

    def report_difference(
        superset: Set, subset: Set, subset_name: str, key: str
    ) -> bool:
        """Return True if difference detected. Print description of difference."""
        missing_from_superset = sorted(superset - subset)
        if not missing_from_superset:
            return False
        printer(f"{subset_name}['{key}'] is missing these entries:")
        if key in list_of_str_keys:
            printer(format(missing_from_superset))
            return True
        for el in missing_from_superset:
            printer(format(el))
        return True

    for root_key in actual_combos.keys():
        if root_key in skipped_keys:
            continue

        printer(f"\nComparing {root_key}:\n{'-' * 40}")
        if root_key == "modules":
            for actual_row, expect_row in zip(
                actual_combos[root_key], expected_combos[root_key]
            ):
                assert actual_row["qt_version"] == expect_row["qt_version"]
                has_difference |= compare_modules_entry(actual_row, expect_row)
            continue

        actual_set = to_set(actual_combos[root_key])
        expected_set = to_set(expected_combos[root_key])
        has_difference |= report_difference(
            expected_set, actual_set, actual_name, root_key
        )
        has_difference |= report_difference(
            actual_set, expected_set, expect_name, root_key
        )

    return has_difference


def alphabetize_modules(combos: Dict[str, Union[List[Dict], List[str]]]):
    for i, item in enumerate(combos["modules"]):
        combos["modules"][i]["modules"] = sorted(item["modules"])


def write_combinations_json(
    combos: Dict[str, Union[List[Dict], List[str]]], filename: Path
):
    logger.info(f"Write file {filename}")
    json_text = json.dumps(combos, sort_keys=True, indent=2)
    if filename.write_text(json_text, encoding="utf_8") == 0:
        raise RuntimeError("Failed to write file!")


def describe_env():
    token = os.getenv("GITHUB_TOKEN")
    repo_name = os.getenv("GITHUB_REPOSITORY")
    run_id = os.getenv("GITHUB_RUN_ID")

    logger.info(
        textwrap.dedent(
            f"""
        Environment:
        Token: {token}
        Repo name: {repo_name}
        Run id: {run_id}
        """
        )
    )


def commit_changes(file_to_commit: Path):
    """
    $ git add aqt/combinations.json
    $ git commit -m "Update aqt/combinations.json"
    """
    logger.info(f"Commit {file_to_commit}")
    working_tree_directory = os.getenv("GITHUB_WORKSPACE")
    repo = Repo(working_tree_directory)
    assert not repo.bare
    assert repo.is_dirty()

    repo.git.add(file_to_commit)
    commit_result = repo.git.commit(m=f"Update `{file_to_commit}`")

    logger.info(commit_result)

    if not commit_result:
        raise RuntimeError("Failed to commit changes!")

    logger.info(repo.git.log(n="3"))


def open_pull_request(changes_report: str):
    logger.info(f"Make PR")
    token = os.getenv("GITHUB_TOKEN")
    g = Github(token)

    repo_name = os.getenv("GITHUB_REPOSITORY")
    repo = g.get_repo(repo_name)

    run_id = os.getenv("GITHUB_RUN_ID")
    body = textwrap.dedent(
        f"""\
    SUMMARY
    The `aqt/generate_combinations` script has detected changes to the repo at https://download.qt.io.
    This PR will update `aqt/combinations.json` to account for those changes.
    
    Posted from [the `generate_combinations` action](https://github.com/{repo_name}/actions/runs/{run_id})
    
    {changes_report}
    """
    )
    pr = repo.create_pull(
        title="Update combinations.json",
        body=body,
        head="develop",
        base="master",
        maintainer_can_modify=True,
    )
    if not pr:
        raise RuntimeError("Failed to create pull request!")


def main(filename: Path, is_make_pull_request: bool) -> int:

    changes_report = []

    def combo_printer(msg: str):
        changes_report.append(msg)
        print(msg)

    try:
        expect = json.loads(filename.read_text())
        alphabetize_modules(expect[0])
        actual = generate_combos(new_archive=expect[0]["new_archive"])

        print("=" * 80)
        print("Program Output:")
        print(pretty_print_combos(actual))

        print("=" * 80)
        print(f"Comparison with existing '{filename}':")
        diff = compare_combos(actual, expect[0], "program_output", str(filename), combo_printer)

        if not diff:
            print(f"{filename} is up to date! No PR is necessary this time!")
            return 0  # no difference
        if is_make_pull_request:
            print(f"{filename} has changed; making commit and PR...")
            write_combinations_json(actual, filename)
            commit_changes(filename)
            open_pull_request(changes_report)
            return 0  # PR request made successfully
        return 1  # difference reported

    except (ArchiveConnectionError, ArchiveDownloadError) as e:
        logger.error("{}".format(e))
        return 1


def local_tqdm(disable: bool):
    return lambda *args: base_tqdm(*args, disable=disable)


if __name__ == "__main__":
    Settings.load_settings()
    setup_logging()
    logger = logging.getLogger("aqt.generate_combos")

    describe_env()
    combos_json_filename = Path(__file__).parent.parent / "aqt/combinations.json"
    logger.info(f"File to modify: {combos_json_filename}")

    parser = argparse.ArgumentParser(
        description="Generate combinations.json from download.qt.io, "
        "compare with existing file, and open PR to correct differences"
    )
    parser.add_argument(
        "--pr",
        help="make a pull request if combinations.json is out of date",
        action="store_true",
    )
    parser.add_argument(
        "--no_tqdm",
        help="disable progress bars (makes CI logs easier to read)",
        action="store_true",
    )
    args = parser.parse_args()

    logger.info(f"Disable tqdm: {args.no_tqdm}\nMake PR: {args.pr}")

    tqdm = local_tqdm(args.no_tqdm)

    exit(main(filename=combos_json_filename, is_make_pull_request=args.pr))
