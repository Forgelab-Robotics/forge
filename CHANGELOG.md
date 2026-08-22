# Changelog

Forge package families are versioned independently. Implementations of the same logical family across Python, Rust, C++, and the language-neutral interface contract share one version and one protected GitLab tag.

## Unreleased

### forge-msgs

- Align the Python `PointCloud` writer with the canonical non-nullable top-level Arrow schema already emitted by Rust and C++; field names, order, and physical value types are unchanged, and readers remain compatible with prior nullable schemas.
- Harden `PointCloud` readers across Python, Rust, and C++ with exact single-row validation, stricter malformed-payload checks, duplicate-field rejection, and Python/C++ IPC coverage.
- Document organized-cloud ordering, invalid-point, frame/time, and future packed-format semantics without changing the v1 fields.

## Package-family 1.0.1 releases - 2026-08-13

| Package family | Version | Protected tag |
|---|---:|---|
| Common | `1.0.1` | `forge-common-v1.0.1` |
| Msgs | `1.0.1` | `forge-msgs-v1.0.1` |
| Robot | `1.0.1` | `forge-robot-v1.0.1` |
| Policy | `1.0.1` | `forge-policy-v1.0.1` |
| Kinematics | `1.0.1` | `forge-kinematics-v1.0.1` |

### Packaging

- Include the complete Apache-2.0 `LICENSE` in every Python wheel and source distribution.
- Add one repository-level command to cleanly build and validate all Python distributions and generate `SHA256SUMS`.
- Validate wheel and sdist identity, Apache-2.0 metadata, exact license layout, and unexpected output entries.
- Add guarded, single-family release candidate builds while retaining all-family local validation.
- Make CI validate all five Python distributions instead of only `forge-kinematics`.
- Add repository, changelog, and issue tracker links to the published Python package metadata.

## Initial package-family 1.0 releases - 2026-08-02

| Package family | Version | Protected tag |
|---|---:|---|
| Common | `1.0.0` | `forge-common-v1.0.0` |
| Msgs | `1.0.0` | `forge-msgs-v1.0.0` |
| Robot | `1.0.0` | `forge-robot-v1.0.0` |
| Policy | `1.0.0` | `forge-policy-v1.0.0` |
| Kinematics | `1.0.0` | `forge-kinematics-v1.0.0` |

The initial tags may all point to the same clean, fully validated commit. A family can use an independent version and tag in later releases.

### Stable contracts

- `forge-msgs`: `interfaces/forge_msgs/*.v1.yaml` is the canonical cross-language message contract; Python, Rust, and C++ implementations use compatible Apache Arrow schemas and validation semantics.
- `forge-msgs`: existing field names, field order, Arrow types, null behavior, units, and sparse command semantics are stable for the `1.x` line.
- `forge-robot`: the Python and C++ implementations define the stable robot driver protocol, safety helpers, Dora runner inputs, and outputs.
- `forge-policy`: the Python package defines the stable policy adapter and Dora runner contract.
- `forge-kinematics`: the Python package defines the stable FK, Jacobian, and inverse-kinematics API.
- `forge-common`: Python, Rust, and C++ provide shared utilities; Python and C++ logging use the documented `FORGE_LOG_*` environment variables.

### Compatibility policy

- Compatible bug fixes increment the affected family patch version.
- Backward-compatible additions increment the affected family minor version.
- Removing fields, changing field types or units, reinterpreting values, or breaking a family API requires that family to increment its major version.
- Historical generic tags such as `v1.0.0` predate this release model and must not be moved or reused.
