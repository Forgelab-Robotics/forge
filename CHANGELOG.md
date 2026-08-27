# Changelog

Forge package families are versioned independently. Implementations of the same logical family across Python, Rust, C++, and the language-neutral interface contract share one version and one protected GitLab tag.

## Unreleased

### Tool 0.1.0

- Add the dependency-free `forge-tool` Python package family.
- Define endpoint descriptors, attempt-scoped `ToolExecutionKey`, authoritative terminal results, structured control/error/status/event models, and async Query/Action/Session Endpoint protocols.
- Add the generic ToolEndpoint v1alpha1 invoke/status/result/control/event message family, strict deterministic UTF-8 JSON codec, typed payload adapters, endpoint instance identity, event sequence, and descriptor registration conversion.
- Define ToolEndpoint as a provider-side SPI/Wire boundary for embedding a binding/handler in concrete Dora business nodes; identity/correlation, lifecycle, terminal-result, and endpoint-sequence value rules remain protocol semantics, while P0 provides no stateful replay, deduplication, retention, retry, or exactly-once execution guarantee.
- Build normal execution responses directly from their originating request envelope so endpoint nodes do not need to retain a complete invoke context solely for correlation.
- Add correlated `endpoint.registry.response` management acknowledgements with strict `EndpointRegistryResponse` lease/revision/error invariants, request-derived factories, and management response correlation validation; require `request_id` for register, unregister, and Registry response while forbidding it on unsolicited endpoint health status.
- Simplify endpoint management to periodic `endpoint.register` announce/upsert/lease renewal plus `endpoint.unregister` and `endpoint.registry.response`; remove `endpoint.heartbeat` and its factory API.
- Allow every `tool.*` logical envelope to omit `endpoint_instance_id` before provider routing, including correlated invoke responses/errors when Gateway selection fails; require it on every `endpoint.*` message, keep `None` response correlation exact, and make the cross-language Arrow carrier column nullable accordingly.
- Align Registry semantics with the current Gateway: a static configured/trusted route authorizes `endpoint_id` and owns at most one current instance; descriptor-equal same-instance register renews without a revision, a new instance atomically replaces current with one revision, same-instance descriptor changes are rejected, matching unregister and expiry remove current with one revision, absent unregister is effect-idempotently accepted, and a stale instance cannot remove current.
- Define `registry_revision` only as a process-local availability-state revision reported after the current decision; Gateway restart begins empty and periodic register restores availability.
- Document the current Query-only Gateway scope: it routes invoke and correlates only terminal response/`tool.error`; `endpoint.status` and `tool.event` remain protocol/model messages but are not accepted or routed. Status validation is deferred to future availability/health needs, and event correlation to future Action/Session needs.
- Document the existing simple experimental HTTP Query discovery/invoke bridge and Dora logical caller vertical bridge, plus the completed concrete YOLO Dora provider-node embedding and first real Query vertical; additional providers, a general runner, the complete caller-facing Tool Runtime API, stable Dora caller contract, Action/Session, SSE, and MCP remain future work.
- Narrow execution guarantees to identity and correlation: `request_id` identifies one exchange, while `invocation_id + attempt_id` identifies one execution attempt. P0 provides no replay/dedup/exactly-once behavior and does not automatically retry Query; Action/retry and any bounded stateful deduplication remain future requirement-driven design.
- Declare this v1alpha1 contract the first atomic tagged/public Tool release contract; earlier untagged prototypes are incompatible and mixed Python/Rust/C++/Gateway/provider deployments are unsupported.
- Add a transport-independent Query-first `ToolEndpointHandler` with exact descriptor-to-implementation mapping validation, endpoint-instance route checks, correlated terminal results, and structured endpoint rejection handling; it owns no Dora node or execution state.
- Add an optional `forge_tool.dora` in-memory Arrow carrier binding that bridges one `forge_msgs.ToolMessage` input to the logical Query handler and returns a response `RecordBatch` without owning a Dora node, event loop, or metadata; it bounds raw carriers, raw payload JSON, accepted logical requests, and responses, reserves correlated-error headroom, rejects IPC bytes for upstream bounded decode, and keeps the base `forge-tool` install dependency-free.
- Keep message-specific logical payload validation in `forge-tool`; the cross-language `forge_msgs.ToolMessage` is its Arrow transport carrier.
- Keep the complete caller-facing Tool Runtime API, stable caller contracts, Gateway implementation, concrete provider-node Dora I/O wiring, ToolSpec, and concrete endpoint adapters outside this initial protocol package; the completed external YOLO provider wiring and current Gateway Query bridges do not change the package boundary, and a future general runner is optional rather than the only integration path.

### Msgs 1.1.0

- Add `tool.v1.yaml` and `forge_msgs.ToolMessage` alongside `PolicyCommand` and `PolicyCommandStatus` in the canonical cross-language schema and the Python, Rust, and C++ carrier implementations.
- Define an exact ten-column, single-row Arrow carrier whose optional columns use null, whose `payload_json` contains the logical payload object, and which has no observation timestamp; Python `from_arrow()` additionally supports a caller-configured pre-validation raw payload byte limit.
- Add `endpoint.registry.response` to Python, Rust, and C++ `ToolMessage` carriers and enforce the management exchange `request_id` matrix across all three implementations.
- Add bidirectional Python/C++ Arrow IPC compatibility coverage for the carrier; Rust provides Arrow `RecordBatch` conversion without a claimed Rust/Python IPC interop test.
- Require C++20 for `forge_msgs_cpp` and propagate that requirement to CMake consumers with `cxx_std_20`.

## forge-msgs 1.1.0 - 2026-08-22

Protected tag: `forge-msgs-v1.1.0`

- Add Python `PointCloudBatch.from_numpy()` and `PointCloudView.from_arrow()` APIs with explicit NumPy copy/casting policies, read-only Arrow-backed field views, and local payload-buffer sharing for high-throughput producers and consumers.
- Align the Python `PointCloud` writer with the canonical non-nullable top-level Arrow schema already emitted by Rust and C++; field names, order, physical value types, payload values, and the canonical v1 contract are unchanged, and readers remain compatible with prior nullable schemas.
- Harden `PointCloud` readers across Python, Rust, and C++ with exact single-row validation, stricter malformed-payload checks, duplicate-field rejection, complete IPC stream consumption, and expanded Python/C++ interoperability coverage.
- Document organized-cloud ordering, invalid-point, frame/time, buffer ownership, and future packed-format semantics without changing the v1 fields.

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
- Make CI validate all six Python distributions instead of only `forge-kinematics`.
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
