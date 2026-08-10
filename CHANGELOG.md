# Changelog

Forge package families are versioned independently. Implementations of the same logical family across Python, Rust, C++, and the language-neutral interface contract share one version and one protected GitLab tag.

## Unreleased

### Tool 0.1.0

- Add the dependency-free `forge-tool` Python package family.
- Define endpoint descriptors, attempt-scoped `ToolExecutionKey`, authoritative terminal results, structured control/error/status/event models, and async Query/Action/Session Endpoint protocols.
- Add the generic ToolEndpoint v1alpha1 invoke/status/result/control/event message family, strict deterministic UTF-8 JSON codec, typed payload adapters, endpoint instance identity, event sequence, and descriptor registration conversion.
- Define ToolEndpoint as a provider-side SPI/Wire boundary for embedding a binding/handler in concrete Dora business nodes; structural identity, lifecycle, terminal-result, deduplication, and endpoint-sequence rules remain normative protocol semantics, while stateful embedded handling remains future work.
- Build normal execution responses directly from their originating request envelope so endpoint nodes do not need to retain a complete invoke context solely for correlation.
- Add a transport-independent Query-first `ToolEndpointHandler` with exact descriptor-to-implementation mapping validation, endpoint-instance route checks, correlated terminal results, and structured endpoint rejection handling; it owns no Dora node or execution state.
- Add an optional `forge_tool.dora` Arrow carrier binding that bridges one `forge_msgs.ToolMessage` input to the logical Query handler and returns a response `RecordBatch` without owning a Dora node, event loop, or metadata; the base `forge-tool` install remains dependency-free.
- Keep message-specific logical payload validation in `forge-tool`; the cross-language `forge_msgs.ToolMessage` is its Arrow transport carrier.
- Keep the caller-facing Tool Runtime API, Gateway routing, concrete endpoint-node Dora I/O wiring, ToolSpec, and concrete endpoint adapters outside this initial protocol package; a future runner is optional rather than the only integration path.

### Msgs 1.1.0

- Add `tool.v1.yaml` and `forge_msgs.ToolMessage` alongside `PolicyCommand` and `PolicyCommandStatus` in the canonical cross-language schema and the Python, Rust, and C++ carrier implementations.
- Define an exact ten-column, single-row Arrow carrier whose optional columns use null, whose `payload_json` contains the logical payload object, and which has no observation timestamp.
- Add bidirectional Python/C++ Arrow IPC compatibility coverage for the carrier; Rust provides Arrow `RecordBatch` conversion without a claimed Rust/Python IPC interop test.
- Require C++20 for `forge_msgs_cpp` and propagate that requirement to CMake consumers with `cxx_std_20`.

### Release tooling

- Include the complete Apache-2.0 `LICENSE` in every Python wheel and source distribution.
- Add one repository-level command to cleanly build and validate all Python distributions and generate `SHA256SUMS`.
- Validate wheel and sdist identity, Apache-2.0 metadata, exact license layout, and unexpected output entries.
- Add guarded, single-family release candidate builds while retaining all-family local validation.
- Make CI validate all Python distributions instead of only `forge-kinematics`.

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
