# Releasing Forge Package Families

Forge is a Monorepo with independently versioned logical package families. Implementations of one family across languages remain synchronized, while unrelated families can release at different rates.

## Version source of truth

`versions.toml` records the current family versions:

```toml
[packages]
common = "1.0.0"
msgs = "1.0.0"
robot = "1.0.0"
policy = "1.0.0"
kinematics = "1.0.0"
```

The root `pyproject.toml` is a virtual uv workspace, not a published `forge` Python distribution. Its project version is workspace tooling metadata and is not a package-family release version.

## Family boundaries and tags

| Family | Synchronized implementations | Protected tag pattern |
|---|---|---|
| Common | `packages/common`, `crates/forge_common`, `cpp/forge_common` | `forge-common-v<semver>` |
| Msgs | `interfaces/forge_msgs`, `packages/msgs`, `crates/forge_msgs`, `cpp/forge_msgs` | `forge-msgs-v<semver>` |
| Robot | `packages/robot`, `cpp/forge_robot` | `forge-robot-v<semver>` |
| Policy | `packages/policy` | `forge-policy-v<semver>` |
| Kinematics | `packages/kinematics` | `forge-kinematics-v<semver>` |

Do not create separate Python/Rust/C++ tags for one family. `forge-msgs-v1.0.0`, for example, identifies the v1 schema plus all three language implementations at the tagged commit.

Do not use or move historical generic tags such as `v1.0.0`. They belong to an earlier repository layout. All new release tags must use a family namespace.

The initial five `1.0.0` tags may point to the same clean commit. Later releases can be independent, for example:

```text
forge-common-v1.0.1
forge-msgs-v1.2.0
forge-robot-v1.0.0
forge-policy-v1.1.0
forge-kinematics-v1.0.2
```

## Downstream dependencies

Use the tag for the exact family being consumed:

```toml
[tool.uv.sources]
forge-msgs = { git = "https://gitlab.ex-ai.cn/meta-emt/framework/forge.git", tag = "forge-msgs-v1.0.0", subdirectory = "packages/msgs" }
forge-common = { git = "https://gitlab.ex-ai.cn/meta-emt/framework/forge.git", tag = "forge-common-v1.0.0", subdirectory = "packages/common" }
```

A downstream `uv.lock` or `Cargo.lock` records the exact commit resolved from each protected tag. Protected release tags must never be moved.

## Changing a family version

1. Change only the affected family in `versions.toml`.
2. Update every language implementation belonging to that family.
3. Update compatible internal dependency constraints only when their supported range changes.
4. Regenerate `uv.lock` and/or `Cargo.lock` as applicable.
5. Add a family-specific entry to `CHANGELOG.md`.
6. Run the version gate and relevant tests before review.

`./scripts/check_release_versions.py` verifies family synchronization, workspace membership, internal Python requirements, uv/Cargo locks, and the Msgs interface major. In GitLab and GitHub tag pipelines it also reads `CI_COMMIT_TAG` or `GITHUB_REF_NAME` and rejects unknown families, non-SemVer tags, and tags whose version differs from `versions.toml`.

A tag can be checked locally before creation:

```bash
./scripts/check_release_versions.py --tag forge-msgs-v1.0.0
```

## Release requirements

Before creating any family tag:

1. `versions.toml`, all implementations in that family, internal requirements, and lock files are aligned.
2. `CHANGELOG.md` identifies the family version and release date.
3. The repository working tree is clean.
4. Relevant Python, Rust, C++, and cross-language interoperability tests pass.
5. Affected Python distributions and Rust packages build from the clean revision.
6. The exact protected GitLab tag does not already exist.

For a coordinated initial baseline, run the complete repository validation and create all five tags only after it passes.

## Validation

From the repository root:

```bash
./scripts/check_release_versions.py
uv lock --check
cargo check --workspace --locked

uv sync --locked --all-packages --all-extras --dev
uv run ruff check .
uv run python scripts/check_forge_msgs_schema.py
uv run pytest \
  packages/msgs/tests \
  packages/policy/tests \
  packages/robot/tests \
  packages/kinematics/tests

cargo test --workspace --locked
```

Build language packages:

```bash
rm -rf dist/release
uv build --all-packages --out-dir dist/release/python
uv run python packages/kinematics/scripts/check_distribution.py \
  dist/release/python

cargo package --workspace --locked
```

Configure, build, and test C++ with the same Python environment used for PyArrow:

```bash
cmake -S cpp/forge_common -B build/release/forge_common \
  -DFORGE_COMMON_CPP_BUILD_TESTS=ON
cmake --build build/release/forge_common
ctest --test-dir build/release/forge_common --output-on-failure

cmake -S cpp/forge_msgs -B build/release/forge_msgs \
  -DFORGE_MSGS_CPP_BUILD_TESTS=ON \
  -DPython3_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build build/release/forge_msgs
ctest --test-dir build/release/forge_msgs --output-on-failure

cmake -S cpp/forge_robot -B build/release/forge_robot \
  -DFORGE_ROBOT_CPP_BUILD_TESTS=ON \
  -DPython3_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build build/release/forge_robot
ctest --test-dir build/release/forge_robot --output-on-failure
```

`cargo package --allow-dirty` may be used while preparing a release candidate. Final package verification and tag creation must use a clean working tree without `--allow-dirty`.

## GitLab release procedure

After review:

1. Replace the affected family entry's `Unreleased` marker with the release date.
2. Commit the release changes.
3. Run the required validation again from the clean commit.
4. Create the protected annotated family tag or tags at that exact commit.
5. Push the commit and tags to GitLab.
6. Attach checksums or package registry links to the corresponding GitLab Release if artifacts are uploaded.
7. Update downstream nodes to use the family tags and regenerate their locks.

For the initial baseline, the intended tags are:

```text
forge-common-v1.0.0
forge-msgs-v1.0.0
forge-robot-v1.0.0
forge-policy-v1.0.0
forge-kinematics-v1.0.0
```

Do not create or move release tags before clean-commit validation completes.
