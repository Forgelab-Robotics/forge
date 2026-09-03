#!/usr/bin/env python3
"""Verify Forge package-family versions, dependencies, and lock files."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSIONS_PATH = Path("versions.toml")
WORKSPACE_PROJECT = Path("pyproject.toml")
FAMILY_ORDER = ("common", "msgs", "robot", "policy", "kinematics", "tool")
INTERFACE_ORDER = ("msgs",)
PYTHON_PROJECTS = {
    "common": Path("packages/common/pyproject.toml"),
    "msgs": Path("packages/msgs/pyproject.toml"),
    "robot": Path("packages/robot/pyproject.toml"),
    "policy": Path("packages/policy/pyproject.toml"),
    "kinematics": Path("packages/kinematics/pyproject.toml"),
    "tool": Path("packages/tool/pyproject.toml"),
}
RUST_CRATES = {
    "common": Path("crates/forge_common/Cargo.toml"),
    "msgs": Path("crates/forge_msgs/Cargo.toml"),
}
CPP_PROJECTS = {
    "common": Path("cpp/forge_common/CMakeLists.txt"),
    "msgs": Path("cpp/forge_msgs/CMakeLists.txt"),
    "robot": Path("cpp/forge_robot/CMakeLists.txt"),
}
EXPECTED_WORKSPACE_MEMBERS = {
    "packages/common",
    "packages/kinematics",
    "packages/msgs",
    "packages/policy",
    "packages/robot",
    "packages/tool",
}
EXPECTED_INTERNAL_REQUIREMENTS = {
    WORKSPACE_PROJECT: {
        "forge-common>=1.0.0,<2",
        "forge-msgs>=2.0.0,<3",
        "forge-policy>=2.0.0,<3",
        "forge-robot>=2.0.0,<3",
        "forge-tool>=2.0.0,<3",
    },
    Path("packages/policy/pyproject.toml"): {"forge-msgs>=2.0.0,<3"},
    Path("packages/robot/pyproject.toml"): {"forge-msgs>=2.0.0,<3"},
    Path("packages/tool/pyproject.toml"): set(),
}
EXPECTED_OPTIONAL_INTERNAL_REQUIREMENTS = {
    Path("packages/tool/pyproject.toml"): {
        "dora": {"forge-msgs>=2.0.0,<3"},
    },
}
UV_PACKAGE_FAMILIES = {
    "forge-common": "common",
    "forge-msgs": "msgs",
    "forge-robot": "robot",
    "forge-policy": "policy",
    "forge-kinematics": "kinematics",
    "forge-tool": "tool",
}
UV_PACKAGE_SOURCES = {
    "forge": ".",
    "forge-common": "packages/common",
    "forge-msgs": "packages/msgs",
    "forge-robot": "packages/robot",
    "forge-policy": "packages/policy",
    "forge-kinematics": "packages/kinematics",
    "forge-tool": "packages/tool",
}
CARGO_PACKAGE_FAMILIES = {
    "forgelab_common": "common",
    "forge_msgs": "msgs",
}
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CMAKE_VERSION = re.compile(r"\bproject\([^)]*\bVERSION\s+([^\s)]+)", re.DOTALL)
INTERFACE_VERSION = re.compile(r"^version:\s*(\d+)\s*$", re.MULTILINE)
FAMILY_TAG = re.compile(r"^forge-([a-z0-9-]+)-v(.+)$")


class ReleaseVersionError(RuntimeError):
    """Raised when release metadata cannot be read or has an invalid shape."""


def _read_text(path: Path) -> str:
    try:
        return (ROOT / path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReleaseVersionError(f"{path}: cannot read file: {exc}") from exc


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with (ROOT / path).open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseVersionError(f"{path}: cannot load TOML: {exc}") from exc
    if not isinstance(document, dict):
        raise ReleaseVersionError(f"{path}: top-level TOML value must be a table")
    return document


def _table(document: dict[str, Any], path: Path, *keys: str) -> dict[str, Any]:
    value: Any = document
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            dotted = ".".join(keys)
            raise ReleaseVersionError(f"{path}: missing [{dotted}] table")
        value = value[key]
    if not isinstance(value, dict):
        dotted = ".".join(keys)
        raise ReleaseVersionError(f"{path}: [{dotted}] must be a table")
    return value


def _strict_version(value: Any, location: str) -> str:
    if not isinstance(value, str) or not SEMVER.fullmatch(value):
        raise ReleaseVersionError(
            f"{location}: expected strict SemVer, found {value!r}"
        )
    return value


def _load_family_versions() -> dict[str, str]:
    document = _load_toml(VERSIONS_PATH)
    if document.get("schema_version") != 1:
        raise ReleaseVersionError(f"{VERSIONS_PATH}: schema_version must be 1")
    packages = _table(document, VERSIONS_PATH, "packages")
    if set(packages) != set(FAMILY_ORDER):
        raise ReleaseVersionError(
            f"{VERSIONS_PATH}: package families differ; "
            f"expected {sorted(FAMILY_ORDER)}, found {sorted(packages)}"
        )
    return {
        family: _strict_version(packages[family], f"{VERSIONS_PATH}: packages.{family}")
        for family in FAMILY_ORDER
    }


def _load_interface_versions() -> dict[str, int]:
    document = _load_toml(VERSIONS_PATH)
    interfaces = _table(document, VERSIONS_PATH, "interfaces")
    if set(interfaces) != set(INTERFACE_ORDER):
        raise ReleaseVersionError(
            f"{VERSIONS_PATH}: interfaces differ; "
            f"expected {sorted(INTERFACE_ORDER)}, found {sorted(interfaces)}"
        )

    versions: dict[str, int] = {}
    for interface in INTERFACE_ORDER:
        value = interfaces[interface]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ReleaseVersionError(
                f"{VERSIONS_PATH}: interfaces.{interface} must be a positive integer"
            )
        versions[interface] = value
    return versions


def _declared_version(path: Path, table: str) -> str:
    value = _table(_load_toml(path), path, table).get("version")
    return _strict_version(value, f"{path}: [{table}].version")


def _internal_requirements(document: dict[str, Any], path: Path) -> set[str]:
    dependencies = _table(document, path, "project").get("dependencies", [])
    if not isinstance(dependencies, list) or not all(
        isinstance(requirement, str) for requirement in dependencies
    ):
        raise ReleaseVersionError(f"{path}: project.dependencies must be strings")
    return {
        requirement for requirement in dependencies if requirement.startswith("forge-")
    }


def _optional_internal_requirements(
    document: dict[str, Any], path: Path
) -> dict[str, set[str]]:
    optional = _table(document, path, "project").get("optional-dependencies", {})
    if not isinstance(optional, dict):
        raise ReleaseVersionError(
            f"{path}: project.optional-dependencies must be a table"
        )
    internal: dict[str, set[str]] = {}
    for extra, dependencies in optional.items():
        if (
            not isinstance(extra, str)
            or not isinstance(dependencies, list)
            or not all(isinstance(requirement, str) for requirement in dependencies)
        ):
            raise ReleaseVersionError(
                f"{path}: project.optional-dependencies entries must be string lists"
            )
        requirements = {
            requirement
            for requirement in dependencies
            if requirement.startswith("forge-")
        }
        if requirements:
            internal[extra] = requirements
    return internal


def _check_workspace(findings: list[str]) -> str | None:
    try:
        document = _load_toml(WORKSPACE_PROJECT)
        project = _table(document, WORKSPACE_PROJECT, "project")
        workspace_version = _strict_version(
            project.get("version"), f"{WORKSPACE_PROJECT}: [project].version"
        )
        uv = _table(document, WORKSPACE_PROJECT, "tool", "uv")
        workspace = _table(document, WORKSPACE_PROJECT, "tool", "uv", "workspace")
        requirements = _internal_requirements(document, WORKSPACE_PROJECT)
    except ReleaseVersionError as exc:
        findings.append(str(exc))
        return None

    if uv.get("package") is not False:
        findings.append(f"{WORKSPACE_PROJECT}: [tool.uv].package must be false")

    members = workspace.get("members")
    if not isinstance(members, list) or not all(
        isinstance(item, str) for item in members
    ):
        findings.append(
            f"{WORKSPACE_PROJECT}: [tool.uv.workspace].members must be strings"
        )
    elif set(members) != EXPECTED_WORKSPACE_MEMBERS:
        findings.append(
            f"{WORKSPACE_PROJECT}: workspace members differ; "
            f"expected {sorted(EXPECTED_WORKSPACE_MEMBERS)}, found {sorted(members)}"
        )

    expected_requirements = EXPECTED_INTERNAL_REQUIREMENTS[WORKSPACE_PROJECT]
    if requirements != expected_requirements:
        findings.append(
            f"{WORKSPACE_PROJECT}: internal requirements differ; "
            f"expected {sorted(expected_requirements)}, found {sorted(requirements)}"
        )
    return workspace_version


def _check_python(findings: list[str], versions: dict[str, str]) -> None:
    for family, path in PYTHON_PROJECTS.items():
        try:
            actual = _declared_version(path, "project")
        except ReleaseVersionError as exc:
            findings.append(str(exc))
            continue
        if actual != versions[family]:
            findings.append(
                f"{path}: {family} expected {versions[family]}, found {actual}"
            )

    for path, expected in EXPECTED_INTERNAL_REQUIREMENTS.items():
        if path == WORKSPACE_PROJECT:
            continue
        try:
            actual = _internal_requirements(_load_toml(path), path)
        except ReleaseVersionError as exc:
            findings.append(str(exc))
            continue
        if actual != expected:
            findings.append(
                f"{path}: internal requirements differ; "
                f"expected {sorted(expected)}, found {sorted(actual)}"
            )

    for path, expected in EXPECTED_OPTIONAL_INTERNAL_REQUIREMENTS.items():
        try:
            actual = _optional_internal_requirements(_load_toml(path), path)
        except ReleaseVersionError as exc:
            findings.append(str(exc))
            continue
        if actual != expected:
            findings.append(
                f"{path}: optional internal requirements differ; "
                f"expected {expected}, found {actual}"
            )


def _check_rust(findings: list[str], versions: dict[str, str]) -> None:
    for family, path in RUST_CRATES.items():
        try:
            actual = _declared_version(path, "package")
        except ReleaseVersionError as exc:
            findings.append(str(exc))
            continue
        if actual != versions[family]:
            findings.append(
                f"{path}: {family} expected {versions[family]}, found {actual}"
            )


def _check_uv_lock(
    findings: list[str], versions: dict[str, str], workspace_version: str | None
) -> None:
    path = Path("uv.lock")
    try:
        packages = _load_toml(path).get("package")
    except ReleaseVersionError as exc:
        findings.append(str(exc))
        return
    if not isinstance(packages, list):
        findings.append(f"{path}: package must be an array of tables")
        return

    expected_versions = {
        name: versions[family] for name, family in UV_PACKAGE_FAMILIES.items()
    }
    if workspace_version is not None:
        expected_versions["forge"] = workspace_version

    for name, expected in expected_versions.items():
        source_path = UV_PACKAGE_SOURCES[name]
        matches = []
        for package in packages:
            if not isinstance(package, dict) or package.get("name") != name:
                continue
            source = package.get("source")
            if not isinstance(source, dict):
                continue
            actual_source = source.get("virtual", source.get("editable"))
            if actual_source == source_path:
                matches.append(package)
        if len(matches) != 1:
            findings.append(
                f"{path}: expected one local {name} package from {source_path}, "
                f"found {len(matches)}"
            )
        elif matches[0].get("version") != expected:
            findings.append(
                f"{path}: {name} expected {expected}, "
                f"found {matches[0].get('version')!r}"
            )


def _check_cargo_lock(findings: list[str], versions: dict[str, str]) -> None:
    path = Path("Cargo.lock")
    try:
        packages = _load_toml(path).get("package")
    except ReleaseVersionError as exc:
        findings.append(str(exc))
        return
    if not isinstance(packages, list):
        findings.append(f"{path}: package must be an array of tables")
        return

    for name, family in CARGO_PACKAGE_FAMILIES.items():
        matches = [
            package
            for package in packages
            if isinstance(package, dict)
            and package.get("name") == name
            and "source" not in package
        ]
        if len(matches) != 1:
            findings.append(
                f"{path}: expected one local {name} package, found {len(matches)}"
            )
        elif matches[0].get("version") != versions[family]:
            findings.append(
                f"{path}: {name} expected {versions[family]}, "
                f"found {matches[0].get('version')!r}"
            )


def _check_cpp(findings: list[str], versions: dict[str, str]) -> None:
    for family, path in CPP_PROJECTS.items():
        try:
            text = _read_text(path)
        except ReleaseVersionError as exc:
            findings.append(str(exc))
            continue
        match = CMAKE_VERSION.search(text)
        if match is None:
            findings.append(f"{path}: missing project(... VERSION ...)")
        elif match.group(1) != versions[family]:
            findings.append(
                f"{path}: {family} expected {versions[family]}, found {match.group(1)}"
            )


def _check_interface(findings: list[str], interface_versions: dict[str, int]) -> None:
    expected_major = str(interface_versions["msgs"])
    path = Path(f"interfaces/forge_msgs/forge_msgs.v{expected_major}.yaml")
    try:
        text = _read_text(path)
    except ReleaseVersionError as exc:
        findings.append(str(exc))
        return
    match = INTERFACE_VERSION.search(text)
    if match is None:
        findings.append(f"{path}: missing integer version")
    elif match.group(1) != expected_major:
        findings.append(
            f"{path}: Msgs interface version expected {expected_major}, found {match.group(1)}"
        )


def _detected_ci_tag(explicit_tag: str | None) -> str | None:
    if explicit_tag is not None:
        return explicit_tag
    gitlab_tag = os.environ.get("CI_COMMIT_TAG")
    if gitlab_tag:
        return gitlab_tag
    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        return os.environ.get("GITHUB_REF_NAME") or None
    return None


def _check_release_tag(
    findings: list[str], versions: dict[str, str], tag: str | None
) -> None:
    if tag is None:
        return
    match = FAMILY_TAG.fullmatch(tag)
    if match is None:
        findings.append(
            f"release tag {tag!r} must match forge-<family>-v<strict-semver>"
        )
        return
    family, tag_version = match.groups()
    if family not in versions:
        findings.append(
            f"release tag {tag!r} uses unknown family {family!r}; "
            f"expected one of {sorted(versions)}"
        )
        return
    if not SEMVER.fullmatch(tag_version):
        findings.append(f"release tag {tag!r} does not use strict SemVer")
        return
    if tag_version != versions[family]:
        findings.append(
            f"release tag {tag!r} does not match versions.toml: "
            f"{family} is {versions[family]}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        help=(
            "release tag to validate; defaults to GitLab CI_COMMIT_TAG or "
            "GitHub tag environment"
        ),
    )
    arguments = parser.parse_args()

    try:
        versions = _load_family_versions()
        interface_versions = _load_interface_versions()
    except ReleaseVersionError as exc:
        print(f"Forge family version validation failed:\n  - {exc}", file=sys.stderr)
        return 1

    findings: list[str] = []
    workspace_version = _check_workspace(findings)
    _check_python(findings, versions)
    _check_rust(findings, versions)
    _check_uv_lock(findings, versions, workspace_version)
    _check_cargo_lock(findings, versions)
    _check_cpp(findings, versions)
    _check_interface(findings, interface_versions)
    release_tag = _detected_ci_tag(arguments.tag)
    _check_release_tag(findings, versions, release_tag)

    if findings:
        print("Forge family version validation failed:", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding}", file=sys.stderr)
        return 1

    print("Forge package-family versions are aligned:")
    for family in FAMILY_ORDER:
        print(f"  {family}: {versions[family]}")
    for interface in INTERFACE_ORDER:
        print(f"  {interface} interface: v{interface_versions[interface]}")
    print("  Workspace, internal requirements, uv lock, and Cargo lock: aligned")
    if release_tag is not None:
        print(f"  Release tag: {release_tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
