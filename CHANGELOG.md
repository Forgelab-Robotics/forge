# Changelog

Forge package families are versioned independently. Implementations of the same logical family across Python, Rust, C++, and the language-neutral interface contract share one version and one protected GitLab tag.

## Unreleased

### Tool 0.1.0

- Add the dependency-free `forge-tool` Python package with validated endpoint descriptors, attempt-scoped `ToolExecutionKey`, authoritative terminal results, structured status/control/event/error models, and async Query/Action/Session ToolEndpoint SPI.
- Define the generic ToolEndpoint v1alpha1 invoke/status/result/control/event/error and endpoint-management message family, strict UTF-8 JSON codec, closed typed payload schemas, complete request-derived envelope factories, and response correlation validation.
- Add periodic `endpoint.register` lease renewal, `endpoint.unregister`, correlated `endpoint.registry.response`, process-local Registry revision semantics, trusted configured-route authority, and exact management identity rules.
- Add `ToolEndpointHandler`: Query returns a correlated terminal result directly; Action supports start/status/result/cancel/events, per-operation admission, bounded early events and execution retention, response-first early-event tuple ordering, terminal-result barriers, lifecycle validation, terminal `unknown` convergence, and retained-key duplicate suppression.
- Add optional `forge_tool.dora` Arrow integration for Query and Action. It bounds carriers, raw payload JSON, accepted requests, and responses; reserves correlated-error headroom; enforces an acknowledged response-before-event publication barrier; rejects IPC bytes for bounded upstream decode; and owns no Dora node, event loop, ports, or metadata.
- Add the exact ten-column `forge_msgs.ToolMessage` carrier in Python, Rust, and C++; keep message-specific payload validation in `forge-tool` and cover bidirectional Python/C++ Arrow IPC interop.
- Keep ToolEndpoint as a provider-side SPI/Wire boundary. The external Gateway and YOLO integration currently validate an experimental endpoint-oriented Query bridge, not the target ToolSpec/Runtime caller boundary; the complete caller-facing Runtime, stable Web/Dora caller contracts, Gateway Action/events, Session dispatch, SSE, and MCP remain outside Tool 0.1.0.
- Define identity and correlation without promising replay, persistent idempotency, exactly-once execution, or automatic retry. Action duplicate suppression is private, bounded, and ends on eviction or process restart.
- Prepare v1alpha1 as the first coordinated tagged/public Tool release candidate; earlier untagged prototypes are incompatible and mixed logical-package/carrier/Gateway/provider deployments are unsupported.

### Msgs 1.1.0

- Add `tool.v1.yaml` and `forge_msgs.ToolMessage` alongside `PolicyCommand` and `PolicyCommandStatus` in the canonical cross-language schema and the Python, Rust, and C++ carrier implementations.
- Define an exact ten-column, single-row Arrow carrier whose optional columns use null, whose `payload_json` contains the logical payload object, and which has no observation timestamp; Python `from_arrow()` additionally supports a caller-configured pre-validation raw payload byte limit.
- Add `endpoint.registry.response` to Python, Rust, and C++ `ToolMessage` carriers and enforce the management exchange `request_id` matrix across all three implementations.
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
- `forge-policy`: the Python package defines the stable `PolicyAdapter` plug-in protocol and Policy Operator runner contract.
- `forge-kinematics`: the Python package defines the stable FK, Jacobian, and inverse-kinematics API.
- `forge-common`: Python, Rust, and C++ provide shared utilities; Python and C++ logging use the documented `FORGE_LOG_*` environment variables.

### Compatibility policy

- Compatible bug fixes increment the affected family patch version.
- Backward-compatible additions increment the affected family minor version.
- Removing fields, changing field types or units, reinterpreting values, or breaking a family API requires that family to increment its major version.
- Historical generic tags such as `v1.0.0` predate this release model and must not be moved or reused.
