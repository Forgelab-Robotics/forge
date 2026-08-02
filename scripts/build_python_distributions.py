#!/usr/bin/env python3
"""Build and validate Forge Python distributions without publishing them."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from check_python_distributions import (
    PACKAGE_DIRS,
    DistributionCheckError,
    check_distributions,
)

ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "dist"
DEFAULT_OUT_DIR = DIST_ROOT / "release/python"
FAMILY_TAG = re.compile(r"^forge-([a-z0-9-]+)-v(.+)$")


class BuildError(RuntimeError):
    """Raised when the distribution build cannot be prepared safely."""


def _resolve_output(path: Path) -> Path:
    output = path if path.is_absolute() else ROOT / path
    output = output.resolve()
    try:
        relative = output.relative_to(DIST_ROOT)
    except ValueError as exc:
        raise BuildError(
            "output directory must be inside the repository dist/ directory"
        ) from exc
    if relative == Path("."):
        raise BuildError("output directory cannot be the dist/ root")
    return output


def _prepare_output(output: Path) -> None:
    if output.is_symlink() or output.is_file():
        output.unlink()
    elif output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)


def _run(command: list[str]) -> None:
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def _git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def _detected_ci_tag() -> str | None:
    gitlab_tag = os.environ.get("CI_COMMIT_TAG")
    if gitlab_tag:
        return gitlab_tag
    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        return os.environ.get("GITHUB_REF_NAME") or None
    return None


def _family_versions() -> dict[str, str]:
    try:
        with (ROOT / "versions.toml").open("rb") as handle:
            packages = tomllib.load(handle)["packages"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise BuildError(f"cannot load versions.toml: {exc}") from exc
    if not isinstance(packages, dict):
        raise BuildError("versions.toml: [packages] must be a table")
    return {str(family): str(version) for family, version in packages.items()}


def _release_family(requested_family: str | None) -> tuple[str | None, str | None]:
    ci_tag = _detected_ci_tag()
    if ci_tag is None:
        return requested_family, None

    match = FAMILY_TAG.fullmatch(ci_tag)
    if match is None or match.group(1) not in PACKAGE_DIRS:
        raise BuildError(f"unsupported package-family CI tag: {ci_tag}")
    ci_family = match.group(1)
    if requested_family is not None and requested_family != ci_family:
        raise BuildError(
            f"--release-family {requested_family} conflicts with CI tag {ci_tag}"
        )
    return ci_family, ci_tag


def _check_release_context(family: str, ci_tag: str | None) -> None:
    status = _git("status", "--porcelain", "--untracked-files=normal").stdout.strip()
    if status:
        raise BuildError("release-family builds require a clean Git working tree")

    versions = _family_versions()
    version = versions.get(family)
    if version is None:
        raise BuildError(f"versions.toml does not define family: {family}")
    expected_tag = f"forge-{family}-v{version}"
    if ci_tag is not None and ci_tag != expected_tag:
        raise BuildError(f"CI tag must be {expected_tag}, found {ci_tag}")

    head = _git("rev-parse", "HEAD").stdout.strip()
    tag_commit = _git(
        "rev-parse", "--verify", f"refs/tags/{expected_tag}^{{commit}}", check=False
    )
    if ci_tag is None:
        if tag_commit.returncode == 0:
            raise BuildError(
                f"{expected_tag} already exists; increment the family version"
            )
        return

    if tag_commit.returncode != 0:
        raise BuildError(
            f"CI release tag is not available in the checkout: {expected_tag}"
        )
    if tag_commit.stdout.strip() != head:
        raise BuildError(f"CI release tag does not point to HEAD: {expected_tag}")
        raise BuildError(
            f"CI release tag is not available in the checkout: {expected_tag}"
        )


def _write_checksums(artifacts: list[Path], output: Path) -> Path:
    checksum_path = output / "SHA256SUMS"
    lines = []
    for artifact in artifacts:
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        lines.append(f"{digest}  {artifact.name}\n")
    checksum_path.write_text("".join(lines), encoding="utf-8")
    return checksum_path


def build(out_dir: Path, requested_family: str | None = None) -> list[Path]:
    output = _resolve_output(out_dir)
    uv = shutil.which("uv")
    if uv is None:
        raise BuildError("uv is required but was not found on PATH")

    family, ci_tag = _release_family(requested_family)
    if family is not None:
        _check_release_context(family, ci_tag)
    else:
        print(
            "NOTICE: building local validation artifacts for all families; "
            "use --release-family for publishable release candidates",
            file=sys.stderr,
        )

    _run([sys.executable, str(ROOT / "scripts/check_release_versions.py")])
    _prepare_output(output)
    build_command = [uv, "build"]
    if family is None:
        build_command.append("--all-packages")
        families = None
    else:
        build_command.extend(("--package", f"forge-{family}"))
        families = (family,)
    build_command.extend(("--out-dir", str(output)))
    _run(build_command)

    artifacts = check_distributions(output, families)
    if family in (None, "kinematics"):
        _run(
            [
                sys.executable,
                str(ROOT / "packages/kinematics/scripts/check_distribution.py"),
                str(output),
            ]
        )
    checksum_path = _write_checksums(artifacts, output)
    print(f"wrote checksums: {checksum_path.relative_to(ROOT)}")
    print(f"built and validated {len(artifacts)} Python distribution archives")
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="clean build output directory below dist/ (default: dist/release/python)",
    )
    parser.add_argument(
        "--release-family",
        choices=tuple(PACKAGE_DIRS),
        help="build one publishable family; requires a clean tree and unused version tag",
    )
    arguments = parser.parse_args()
    try:
        build(arguments.out_dir, arguments.release_family)
    except (
        BuildError,
        DistributionCheckError,
        OSError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"Python distribution build failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
