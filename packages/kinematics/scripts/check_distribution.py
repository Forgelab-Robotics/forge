"""Validate forge-kinematics wheel and source distribution contents."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]


class DistributionCheckError(RuntimeError):
    """Raised when a built distribution does not satisfy release requirements."""


def project_metadata() -> tuple[str, str]:
    with (PACKAGE_ROOT / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]
    return project["name"], project["version"]


def select_artifacts(dist_dir: Path, name: str, version: str) -> tuple[Path, Path]:
    if not dist_dir.is_dir():
        raise DistributionCheckError(
            f"distribution directory does not exist: {dist_dir}"
        )

    wheel_name = name.replace("-", "_").replace(".", "_")
    wheel_prefix = f"{wheel_name}-{version}-"
    wheels = sorted(
        path
        for path in dist_dir.iterdir()
        if path.is_file()
        and path.name.startswith(wheel_prefix)
        and path.name.endswith(".whl")
    )
    sdist = dist_dir / f"{wheel_name}-{version}.tar.gz"

    if len(wheels) != 1:
        found = ", ".join(path.name for path in wheels) or "none"
        raise DistributionCheckError(
            f"expected exactly one {wheel_prefix}*.whl, found: {found}"
        )
    if not sdist.is_file():
        raise DistributionCheckError(f"expected source distribution: {sdist.name}")
    return wheels[0], sdist


def expected_license() -> bytes:
    content = (PACKAGE_ROOT / "LICENSE").read_bytes()
    required_markers = (b"Apache License", b"END OF TERMS AND CONDITIONS")
    if not all(marker in content for marker in required_markers):
        raise DistributionCheckError("package LICENSE is not the Apache-2.0 text")
    return content


def check_wheel_license(archive: zipfile.ZipFile, expected: bytes) -> None:
    candidates = [
        name for name in archive.namelist() if PurePosixPath(name).name == "LICENSE"
    ]
    if not any(archive.read(name) == expected for name in candidates):
        raise DistributionCheckError(
            "wheel does not contain a LICENSE matching packages/kinematics/LICENSE"
        )


def check_sdist_license(sdist: Path, expected: bytes) -> None:
    with tarfile.open(sdist, mode="r:gz") as archive:
        candidates = [
            member
            for member in archive.getmembers()
            if member.isfile() and PurePosixPath(member.name).name == "LICENSE"
        ]
        for member in candidates:
            extracted = archive.extractfile(member)
            if extracted is not None and extracted.read() == expected:
                return
    raise DistributionCheckError(
        "sdist does not contain a LICENSE matching packages/kinematics/LICENSE"
    )


def parse_requirement(requirement: str) -> tuple[str, str, str | None]:
    requirement_part, separator, marker_part = requirement.partition(";")
    match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)(.*)", requirement_part.strip())
    if match is None:
        raise DistributionCheckError(f"cannot parse Requires-Dist: {requirement}")
    canonical_name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
    constraints = match.group(2).replace(" ", "")
    if constraints.startswith("(") and constraints.endswith(")"):
        constraints = constraints[1:-1]
    marker = marker_part.replace(" ", "").replace('"', "'") if separator else None
    return canonical_name, constraints, marker


def check_wheel_metadata(archive: zipfile.ZipFile, name: str, version: str) -> None:
    metadata_files = [
        member
        for member in archive.namelist()
        if member.endswith(".dist-info/METADATA")
    ]
    if len(metadata_files) != 1:
        raise DistributionCheckError(
            f"expected exactly one wheel METADATA file, found {len(metadata_files)}"
        )

    metadata = BytesParser(policy=policy.default).parsebytes(
        archive.read(metadata_files[0])
    )
    if metadata["Name"] != name or metadata["Version"] != version:
        raise DistributionCheckError(
            f"unexpected wheel identity: {metadata['Name']} {metadata['Version']}"
        )
    if metadata["License-Expression"] != "Apache-2.0":
        raise DistributionCheckError("wheel License-Expression must be Apache-2.0")
    license_files = metadata.get_all("License-File", [])
    if "LICENSE" not in license_files:
        raise DistributionCheckError(
            "wheel METADATA must declare License-File: LICENSE"
        )
    if metadata["Requires-Python"] != ">=3.12":
        raise DistributionCheckError("wheel Requires-Python must be >=3.12")

    requirements = {
        name: (constraints, marker)
        for name, constraints, marker in (
            parse_requirement(requirement)
            for requirement in metadata.get_all("Requires-Dist", [])
        )
    }
    if set(requirements) != {"numpy", "pin", "scipy"}:
        raise DistributionCheckError(
            f"unexpected wheel dependencies: {sorted(requirements)}"
        )
    if requirements["numpy"] != (">=2.0", None):
        raise DistributionCheckError("wheel must require numpy>=2.0")
    pin_constraints, pin_marker = requirements["pin"]
    if set(pin_constraints.split(",")) != {">=3.0", "<5"} or pin_marker is not None:
        raise DistributionCheckError("wheel must require pin>=3.0,<5")
    scipy_constraints, scipy_marker = requirements["scipy"]
    if set(scipy_constraints.split(",")) != {">=1.16", "<2"}:
        raise DistributionCheckError(
            "wheel least-squares extra must require scipy>=1.16,<2"
        )
    if scipy_marker != "extra=='least-squares'":
        raise DistributionCheckError(
            "wheel scipy dependency must be guarded by extra == 'least-squares'"
        )
    if metadata.get_all("Provides-Extra", []) != ["least-squares"]:
        raise DistributionCheckError("wheel must provide the least-squares extra")


def check_wheel_import(wheel: Path) -> None:
    code = """
import sys

wheel = sys.argv[1].replace("\\\\", "/").rstrip("/")
sys.path.insert(0, sys.argv[1])
import forge_kinematics

origin = forge_kinematics.__file__.replace("\\\\", "/")
if not origin.startswith(wheel + "/"):
    raise RuntimeError(f"forge_kinematics was not imported from the wheel: {origin}")
print(f"imported forge_kinematics from {origin}")
"""
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", code, str(wheel.resolve())],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        details = error.stderr.strip() or error.stdout.strip()
        raise DistributionCheckError(f"wheel import failed:\n{details}") from error
    print(result.stdout.strip())


def check_distributions(dist_dir: Path) -> None:
    name, version = project_metadata()
    wheel, sdist = select_artifacts(dist_dir, name, version)
    license_content = expected_license()

    with zipfile.ZipFile(wheel) as archive:
        check_wheel_license(archive, license_content)
        check_wheel_metadata(archive, name, version)
    check_sdist_license(sdist, license_content)
    check_wheel_import(wheel)
    print(f"validated wheel: {wheel}")
    print(f"validated sdist: {sdist}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dist_dir",
        nargs="?",
        type=Path,
        default=REPOSITORY_ROOT / "dist",
        help="directory containing built distributions (default: repository dist/)",
    )
    arguments = parser.parse_args()

    try:
        check_distributions(arguments.dist_dir.resolve())
    except (
        DistributionCheckError,
        OSError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as error:
        print(f"distribution check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
