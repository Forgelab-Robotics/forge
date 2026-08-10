# forge-tool

`forge-tool` is the dependency-free Python package for Forge ToolEndpoint models and
the strict UTF-8 JSON logical wire protocol identified by
`forge.tool.endpoint/v1alpha1`.

It implements Query/Action/Session endpoint SPI protocols, validated models, complete
envelope factories, response-correlation validation, registration conversion, typed
payload codecs for every alpha message, a transport-independent Query-first
`ToolEndpointHandler`, and an optional Arrow/Dora carrier binding. Query, action, and
session are descriptor semantics, not separate wire routes. A concrete Dora business
node implements the SPI and embeds these components; concrete node wiring remains
future work.

## Runtime API versus endpoint SPI/Wire

The caller-facing Tool Runtime API is the Web/Dora caller surface for discovery,
invoke, status, result, control, and events. It owns invocation/attempt creation and
hides endpoint routing identities. This package does not implement that Runtime API,
and `forge_msgs.ToolMessage` is not its caller-facing carrier.

The contracts in this package are provider-side endpoint SPI and Wire. Runtime/Gateway
endpoint routing exchanges Wire v1alpha1 messages with a binding/handler embedded in a
concrete Dora business node; the handler calls the Query/Action/Session SPI implemented
by that same node. There is no independent endpoint execution subject. A future runner
may be offered as an optional convenience wrapper, but direct embedding must
remain supported. The vertical spike will decide where Dora integration dependencies
belong without introducing a package decision here.

## Endpoint contracts

- `QueryToolEndpoint.query(...) -> ToolResult` returns a terminal result directly.
- `ActionToolEndpoint.result(key) -> ToolResultResponse` and
  `SessionToolEndpoint.result(key) -> ToolResultResponse` return lookup state:
  `pending`, `available`, or `not_found`.
- `ToolResultResponse(status="available")` requires a `ToolResult`.
  `pending` and `not_found` forbid one.
- Terminal `ToolResult.status="unknown"` means the final execution outcome cannot be
  recovered. It is not result-lookup `pending` or `not_found`.

Control, status, and result locate an execution with the flat identity:

```text
ToolExecutionKey = invocation_id + attempt_id
```

## Descriptor contract

A registration operation contains `name`, `semantics`, `cancellable`, `stoppable`,
`status_supported`, and `max_concurrency`. Operations are non-empty and uniquely
named, and capabilities obey this matrix:

| Semantics | `cancellable` | `stoppable` | `status_supported` |
| --- | --- | --- | --- |
| `query` | `false` | `false` | `false` |
| `action` | `true` or `false` | `false` | `true` |
| `session` | `false` | `true` or `false` | `true` |

`max_concurrency` must be greater than zero. The endpoint descriptor reports
capabilities; it does not replace the Runtime ToolSpec or CompletionSpec.

## Query-first logical handler

`ToolEndpointHandler` takes the descriptor, the concrete node process instance ID, and
a plain operation implementation mapping:

```python
handler = ToolEndpointHandler(
    descriptor,
    endpoint_instance_id="epinst-001",
    operations={"detect": query_endpoint},
)

response = await handler.handle_invoke(request_envelope)
```

Construction requires mapping keys to match descriptor operation names exactly and
checks the callable methods required by each operation semantics. The mapping is copied
so later caller mutation cannot retarget an operation. Query invoke handling validates
the typed envelope, endpoint and process-instance route, and operation; it then calls
`QueryToolEndpoint.query()` and returns a correlated completed or structured rejected
response. `ToolEndpointError` is only a pre-acceptance rejection; Query failures after
execution begins are terminal `ToolResult(status="failed", ...)` values. A trusted-route
request with an invalid typed payload produces a correlated non-retryable `tool.error`.

The handler owns no Dora node, execution state, deduplication cache, or private executor
handle. Action/Session implementations can be validated at construction, but their
invoke/status/result/control/event paths remain future work.

## Optional embedded Arrow/Dora binding

The base `forge-tool` installation remains dependency-free. Install the optional carrier
integration when embedding it in a Dora-capable business node:

```text
forge-tool[dora]
```

The integration is explicitly imported so base `import forge_tool` does not load
`forge_msgs` or PyArrow:

```python
from forge_tool.dora import DoraToolEndpointBinding

binding = DoraToolEndpointBinding(handler)
response_batch = await binding.handle_input(input_arrow_value)
```

`handle_input()` accepts one exact `ToolMessage` Arrow `RecordBatch`, single-batch
`Table`, `StructArray`, or IPC stream bytes, converts it to the logical envelope, awaits
the Query-first handler, and returns a response `RecordBatch`.

The binding deliberately does not import or create a Dora `Node`, choose input/output
IDs, call `asyncio.run()`, or observe/rewrite Dora event metadata. The concrete business
node owns its event loop and publishes the returned Arrow value. Its existing Dora
package supplies `dora-rs`; the optional extra only adds the `forge-msgs` carrier.

## Implemented Arrow/Dora carrier

The related `forge_msgs.ToolMessage` carrier is implemented in Python, Rust, and C++
as an exact-schema, single-row Arrow value with these 10 columns in order:

```text
protocol                utf8, non-null
message_type            utf8, non-null
request_id              utf8, nullable
invocation_id           utf8, nullable
attempt_id              utf8, nullable
endpoint_id             utf8, non-null
endpoint_instance_id    utf8, non-null
operation               utf8, nullable
sequence                int64, nullable
payload_json             utf8, non-null
```

There are no carrier columns for `tool_id` or `implementation_id`; those fields stay
inside the invoke context encoded in `payload_json`. There is no observation timestamp
or request-fingerprint column, and Wire v1alpha1 defines no Wire/Arrow fingerprint.
For `tool.event`, the logical envelope omits `request_id` and the carrier value is null.

Python↔C++ Arrow IPC read/write interop is covered. Rust coverage validates the exact
schema, model, and RecordBatch conversion; Python↔Rust IPC coverage is not claimed.
The optional Python binding bridges this carrier to the stateless Query-first handler;
it does not include a stateful endpoint execution layer, concrete Dora node wiring, or
Dora router.

## Implemented payload schemas

Payload codecs are strict: required fields must be present and unknown fields are
rejected. Mapping fields shown as `{}` are object-valued.

| Message | Exact payload shape |
| --- | --- |
| `endpoint.register` | `{"descriptor":{"protocol_version":"forge.tool.endpoint/v1alpha1","endpoint_id":"...","operations":[...]}}` |
| `endpoint.unregister` | `{}` |
| `endpoint.heartbeat` | `{}` |
| `endpoint.status` | `{"status":{"state":"ready|busy|degraded|unavailable","active_invocations":0,"details":{}}}` |
| `tool.invoke.request` | `{"arguments":{},"context":{"tool_id":"...","implementation_id":"...","metadata":{},"caller_id":"...","deadline_ms":0}}`; `caller_id` and `deadline_ms` are optional |
| `tool.invoke.response` completed | `{"outcome":"completed","result":<ToolResult>}` |
| `tool.invoke.response` accepted | `{"outcome":"accepted","accepted":{"details":{}}}` |
| `tool.invoke.response` rejected | `{"outcome":"rejected","error":<ToolError>}` |
| `tool.status.request` | `{}` |
| `tool.status.response` | `{"status":{"phase":"...","details":{},"error":<ToolError>}}`; `error` is conditional |
| `tool.result.request` | `{}` |
| `tool.result.response` pending | `{"status":"pending"}` |
| `tool.result.response` available | `{"status":"available","result":<ToolResult>}` |
| `tool.result.response` not found | `{"status":"not_found"}` |
| `tool.control.request` | `{"command":"cancel|stop","reason":"..."}`; `reason` is optional |
| `tool.control.response` | `{"response":{"command":"cancel|stop","status":"...","details":{},"error":<ToolError>}}`; `error` is conditional |
| `tool.event` | `{"type":"...","data":{}}`; `sequence` is in the envelope |
| `tool.error` | `{"error":<ToolError>}` |

`ToolError` always contains non-empty `code` and `message`, boolean `retryable`, and
object `details`.

A terminal `ToolResult` contains required `status` and object `outputs`, plus a
conditional `error`. Status is `succeeded`, `failed`, `cancelled`, `stopped`, or
`unknown`. `failed` and `unknown` require `error`; the other statuses forbid it.

Execution phase is `accepted`, `running`, `stopping`, `completed`, `failed`,
`cancelled`, `stopped`, or `unknown`. `failed` and `unknown` require `error`; all
other phases forbid it. A control response status is `accepted`, `rejected`,
`terminal`, or `unsupported`; only `rejected` requires and permits `error`.

Event type is `progress`, `heartbeat`, `executor_completed`, `executor_failed`,
`cancelled`, or `stopped`. The outer event schema is frozen; type-specific `data`
schemas remain future work.

See the repository's [ToolEndpoint protocol](https://gitlab.ex-ai.cn/meta-emt/framework/forge/-/blob/main/interfaces/forge_tool/PROTOCOL.md) for full envelope and payload examples.

## Model invariants and terminal lifecycle contract

Mapping-valued model inputs are defensively copied and validated immediately as
bounded JSON: string keys and valid Unicode, finite numbers, interoperable integers,
maximum nesting depth 64, and no unsupported Python values. The copies remain normal
mutable dictionaries for dataclass serialization, so complete wire construction
revalidates them after construction.

Wire v1alpha1 normatively defines this transition table; the implemented models and
codecs do not by themselves provide a stateful execution store:

| Semantics/current phase | Allowed next phase |
| --- | --- |
| Query initial | terminal only |
| Action/Session initial | `accepted` or terminal |
| `accepted` | `running`, `stopping`, or terminal |
| `running` | `stopping` or terminal |
| `stopping` | terminal |
| Any phase | same-phase replay |
| Terminal | no different phase |

Terminal execution phases are immutable and map exactly to terminal results:

| Phase | Result status |
| --- | --- |
| `completed` | `succeeded` |
| `failed` | `failed` |
| `cancelled` | `cancelled` |
| `stopped` | `stopped` |
| `unknown` | `unknown` |

A nonterminal status cannot pair with a terminal result.
`validate_execution_result(status, result)` validates terminality and this exact
mapping. After a terminal event, a later `progress` or `heartbeat` is invalid.
Executor completion remains separate from Runtime CompletionSpec evaluation.

For asynchronous execution, acceptance must be exposed before related events. Early
events require a configured bounded buffer, with deterministic overflow failure. A
terminal result barrier requires the matching authoritative result to be retained
before exposing a terminal phase/event. If an Action/Session side effect may have
started but an exception occurs before Accepted and the outcome cannot be recovered,
the allowed initial terminal result is `unknown`; Accepted must not be fabricated and
the side effect must not be blindly retried. Buffering, retention, and barrier
integration remain private future work in the endpoint node's embedded handler.

## Complete envelope factories

Complete `make_*_envelope` factories are the preferred public construction path.
Execution request and event factories derive route identity from `ToolContext`.
Invoke, status, result, and control response factories accept the originating request
envelope and copy its correlation identity, so an embedded endpoint handler does not
need to retain a complete invoke context merely to construct a response.
`make_error_response_envelope` uses the same request-based pattern even when the
request's typed payload failed to decode. Factories also cover registration,
heartbeat, unregister, and endpoint status; management factories expose their optional
`request_id`. A logical `tool.event` omits `request_id`; its Arrow carrier
representation uses null.

Raw payload adapters remain public for transport integration and advanced use.
`validate_response_correlation(request, response)` verifies response type and matching
`request_id`, `invocation_id`, `attempt_id`, `endpoint_id`,
`endpoint_instance_id`, and `operation`; normal control responses must also echo the
request command. A correlated `tool.error` may answer any execution request.

## Structural identity, deduplication keys, and registry contract

Wire v1alpha1 defines request identity as equality of validated, decoded structural
JSON. Object order is ignored; arrays remain ordered; strings compare exactly with no
Unicode normalization; `null` and booleans retain their JSON types; and finite numbers
compare by IEEE-754 binary64 value, so `1 == 1.0` and `-0 == 0`. Member presence
participates, so omission differs from explicit `null`. Raw JSON bytes and codec output
are never canonical identity, and no serialization fingerprint is introduced.

Exchange dedup uses `endpoint_instance_id + request_id`. Its request identity excludes
`protocol`, `request_id`, and `endpoint_instance_id`, but includes `message_type`, all
other route fields, and the complete payload. The same key/identity replays the prior
response; a different identity is `FORGE_PROTOCOL_DEDUP_CONFLICT`.

Execution dedup uses `invocation_id + attempt_id`. For `tool.invoke.request`, invoke
identity is exactly `endpoint_id + operation + payload`, excluding the execution key,
request ID, and endpoint instance. Every arguments/context field participates. The
same key/identity replays Accepted or a terminal result without restarting side
effects; a different identity conflicts.

Management idempotency remains Registry current-instance/source semantics. A Registry
has one current instance per `endpoint_id`; replacement requires a trusted transport
generation/lease, and an opaque instance ID cannot order racing registrations.
Heartbeat, status, and unregister only affect the accepted current instance/source.
The package does not implement an asynchronous dedup cache or Registry state.

## Endpoint sequence contract

The endpoint sequence scope remains
`endpoint_instance_id + invocation_id + attempt_id`. The endpoint node's embedded
handler assigns `0` first and then strict `+1`. A retained sequence with the same
structural event is a duplicate; the same sequence with a different event conflicts. A
higher-than-expected sequence is a gap requiring retained-history or status/result
recovery. A lower sequence outside retained history is expired/stale. Sequence never
wraps; assignment after `2^53-1` fails with an exhaustion error.

These are normative Wire semantics, not a claim that public sequencing/state helpers or
a production event store/router are implemented. The previous `forge_tool.host`
surface and its public P1 primitives have been removed.

## Scope

The Python endpoint contracts, models, logical codecs, complete factories, and
correlation validator are implemented. The exact 10-column Arrow/Dora carrier is also
implemented in Python, Rust, and C++, with Python↔C++ Arrow IPC interop coverage; no
Python↔Rust IPC coverage is claimed.

No independent endpoint execution service or public identity/state/sequence primitive
surface is part of the supported scope. Operation implementation mapping, the
Query-first logical request path, and the optional Arrow carrier binding are
implemented. Next comes embedding that binding in a concrete Dora business node,
followed by the first real Query, Action/Session handling, and private bounded dedup
only when needed. The spike will decide the Dora dependency
location; an optional runner may be added later but cannot be the only integration
path. Gateway/Registry, caller-facing Web/Dora
Runtime bindings, and Tool Runtime behavior remain future work. `PolicyCommand` remains
retained unchanged; migration or deprecation is not in scope.

## License

Apache-2.0.
