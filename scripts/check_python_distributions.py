#!/usr/bin/env python3
"""Validate Forge Python wheels and source distributions."""

from __future__ import annotations

import argparse
import sys
import tarfile
import tomllib
import zipfile
from collections.abc import Iterable
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIRS = {
    "common": Path("packages/common"),
    "msgs": Path("packages/msgs"),
    "robot": Path("packages/robot"),
    "policy": Path("packages/policy"),
    "kinematics": Path("packages/kinematics"),
    "tool": Path("packages/tool"),
}
_TOOL_EXTRAS = {"dora"}
_TOOL_REQUIREMENTS = {"forge-msgs>=2.0.0,<3 ; extra == 'dora'"}
_RUNTIME_REQUIREMENTS = {
    "forge-policy": {"dora-rs==1.0.0", "forge-msgs>=2.0.0,<3"},
    "forge-robot": {"dora-rs==1.0.0", "forge-msgs>=2.0.0,<3"},
}


class DistributionCheckError(RuntimeError):
    """Raised when a built distribution does not satisfy release requirements."""


def _load_project(package_dir: Path) -> dict[str, Any]:
    pyproject = ROOT / package_dir / "pyproject.toml"
    try:
        with pyproject.open("rb") as handle:
            document = tomllib.load(handle)
        project = document["project"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise DistributionCheckError(
            f"cannot load {pyproject.relative_to(ROOT)}: {exc}"
        ) from exc
    if not isinstance(project, dict):
        raise DistributionCheckError(
            f"{pyproject.relative_to(ROOT)}: [project] must be a table"
        )
    return project


def _project_identity(package_dir: Path) -> tuple[str, str]:
    project = _load_project(package_dir)
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not name:
        raise DistributionCheckError(
            f"{package_dir}/pyproject.toml: project.name must be a non-empty string"
        )
    if not isinstance(version, str) or not version:
        raise DistributionCheckError(
            f"{package_dir}/pyproject.toml: project.version must be a non-empty string"
        )
    if project.get("license") != "Apache-2.0":
        raise DistributionCheckError(
            f"{package_dir}/pyproject.toml: project.license must be Apache-2.0"
        )
    if project.get("license-files") != ["LICENSE"]:
        raise DistributionCheckError(
            f'{package_dir}/pyproject.toml: project.license-files must be ["LICENSE"]'
        )
    return name, version


def _expected_license(package_dir: Path) -> bytes:
    root_license = (ROOT / "LICENSE").read_bytes()
    package_license_path = ROOT / package_dir / "LICENSE"
    try:
        package_license = package_license_path.read_bytes()
    except OSError as exc:
        raise DistributionCheckError(
            f"cannot read {package_license_path.relative_to(ROOT)}: {exc}"
        ) from exc
    if package_license != root_license:
        raise DistributionCheckError(
            f"{package_license_path.relative_to(ROOT)} must exactly match LICENSE"
        )
    return root_license


def _select_artifacts(dist_dir: Path, name: str, version: str) -> tuple[Path, Path]:
    artifact_stem = name.replace("-", "_").replace(".", "_")
    wheel_prefix = f"{artifact_stem}-{version}-"
    wheels = sorted(
        path
        for path in dist_dir.iterdir()
        if path.is_file()
        and path.name.startswith(wheel_prefix)
        and path.suffix == ".whl"
    )
    sdist = dist_dir / f"{artifact_stem}-{version}.tar.gz"
    if len(wheels) != 1:
        found = ", ".join(path.name for path in wheels) or "none"
        raise DistributionCheckError(
            f"expected exactly one {wheel_prefix}*.whl, found: {found}"
        )
    if not sdist.is_file():
        raise DistributionCheckError(f"expected source distribution: {sdist.name}")
    return wheels[0], sdist


def _parse_metadata(content: bytes, archive_name: str) -> Message:
    metadata = BytesParser(policy=policy.default).parsebytes(content)
    if metadata.defects:
        raise DistributionCheckError(
            f"{archive_name}: malformed package metadata: {metadata.defects}"
        )
    return metadata


def _check_metadata(
    metadata: Message, archive_name: str, name: str, version: str
) -> None:
    if metadata["Name"] != name or metadata["Version"] != version:
        raise DistributionCheckError(
            f"{archive_name}: unexpected identity {metadata['Name']} {metadata['Version']}"
        )
    if metadata["License-Expression"] != "Apache-2.0":
        raise DistributionCheckError(
            f"{archive_name}: License-Expression must be Apache-2.0"
        )
    if "LICENSE" not in metadata.get_all("License-File", []):
        raise DistributionCheckError(
            f"{archive_name}: metadata must declare License-File: LICENSE"
        )
    requirements = set(metadata.get_all("Requires-Dist", []))
    expected_runtime = _RUNTIME_REQUIREMENTS.get(name)
    if expected_runtime is not None and requirements != expected_runtime:
        raise DistributionCheckError(
            f"{archive_name}: {name} requirements must equal "
            f"{sorted(expected_runtime)}"
        )
    if name == "forge-tool":
        extras = set(metadata.get_all("Provides-Extra", []))
        if extras != _TOOL_EXTRAS:
            raise DistributionCheckError(
                f"{archive_name}: forge-tool extras must equal {sorted(_TOOL_EXTRAS)}"
            )
        if requirements != _TOOL_REQUIREMENTS:
            raise DistributionCheckError(
                f"{archive_name}: forge-tool requirements must equal "
                f"{sorted(_TOOL_REQUIREMENTS)}"
            )


def _check_wheel(wheel: Path, name: str, version: str, expected_license: bytes) -> None:
    artifact_stem = name.replace("-", "_").replace(".", "_")
    dist_info = f"{artifact_stem}-{version}.dist-info"
    metadata_path = f"{dist_info}/METADATA"
    license_path = f"{dist_info}/licenses/LICENSE"

    with zipfile.ZipFile(wheel) as archive:
        corrupt_member = archive.testzip()
        if corrupt_member is not None:
            raise DistributionCheckError(
                f"{wheel.name}: corrupt member: {corrupt_member}"
            )
        names = archive.namelist()
        for expected_path in (metadata_path, license_path):
            if names.count(expected_path) != 1:
                raise DistributionCheckError(
                    f"{wheel.name}: expected exactly one {expected_path}"
                )
        if archive.read(license_path) != expected_license:
            raise DistributionCheckError(
                f"{wheel.name}: {license_path} does not match the repository LICENSE"
            )
        metadata = _parse_metadata(archive.read(metadata_path), wheel.name)
        _check_metadata(metadata, wheel.name, name, version)


def _check_sdist(sdist: Path, name: str, version: str, expected_license: bytes) -> None:
    artifact_stem = name.replace("-", "_").replace(".", "_")
    archive_root = f"{artifact_stem}-{version}"
    metadata_path = f"{archive_root}/PKG-INFO"
    license_path = f"{archive_root}/LICENSE"

    with tarfile.open(sdist, mode="r:gz") as archive:
        members_by_name = {
            expected_path: [
                member
                for member in archive.getmembers()
                if member.name == expected_path and member.isfile()
            ]
            for expected_path in (metadata_path, license_path)
        }
        for expected_path, members in members_by_name.items():
            if len(members) != 1:
                raise DistributionCheckError(
                    f"{sdist.name}: expected exactly one {expected_path}"
                )

        license_file = archive.extractfile(members_by_name[license_path][0])
        metadata_file = archive.extractfile(members_by_name[metadata_path][0])
        if license_file is None or license_file.read() != expected_license:
            raise DistributionCheckError(
                f"{sdist.name}: {license_path} does not match the repository LICENSE"
            )
        if metadata_file is None:
            raise DistributionCheckError(f"{sdist.name}: cannot read {metadata_path}")
        metadata = _parse_metadata(metadata_file.read(), sdist.name)
        _check_metadata(metadata, sdist.name, name, version)


def check_distributions(
    dist_dir: Path, families: Iterable[str] | None = None
) -> list[Path]:
    """Validate selected distributions and return their artifact paths."""
    if not dist_dir.is_dir():
        raise DistributionCheckError(
            f"distribution directory does not exist: {dist_dir}"
        )

    selected_families = tuple(families) if families is not None else tuple(PACKAGE_DIRS)
    unknown_families = sorted(set(selected_families) - set(PACKAGE_DIRS))
    if unknown_families:
        raise DistributionCheckError(
            f"unknown package families: {', '.join(unknown_families)}"
        )
    if not selected_families:
        raise DistributionCheckError("at least one package family must be selected")

    artifacts: list[Path] = []
    for family in selected_families:
        package_dir = PACKAGE_DIRS[family]
        name, version = _project_identity(package_dir)
        expected_license = _expected_license(package_dir)
        wheel, sdist = _select_artifacts(dist_dir, name, version)
        _check_wheel(wheel, name, version, expected_license)
        _check_sdist(sdist, name, version, expected_license)
        artifacts.extend((wheel, sdist))
        print(f"validated {name} {version}: {wheel.name}, {sdist.name}")

    expected_paths = set(artifacts)
    allowed_names = {path.name for path in expected_paths} | {
        ".gitignore",
        "SHA256SUMS",
    }
    unexpected = sorted(
        path.name for path in dist_dir.iterdir() if path.name not in allowed_names
    )
    if unexpected:
        raise DistributionCheckError(
            f"unexpected distribution directory entries: {', '.join(unexpected)}"
        )
    return sorted(artifacts, key=lambda path: path.name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dist_dir",
        nargs="?",
        type=Path,
        default=ROOT / "dist/release/python",
        help="directory containing built distributions (default: dist/release/python)",
    )
    parser.add_argument(
        "--family",
        choices=tuple(PACKAGE_DIRS),
        action="append",
        dest="families",
        help="validate only this package family; may be repeated",
    )
    arguments = parser.parse_args()
    dist_dir = arguments.dist_dir
    if not dist_dir.is_absolute():
        dist_dir = ROOT / dist_dir

    try:
        check_distributions(dist_dir.resolve(), arguments.families)
    except (
        DistributionCheckError,
        OSError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as exc:
        print(f"distribution check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
