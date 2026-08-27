# forge-tool

`forge-tool` is the dependency-free Python package for Forge ToolEndpoint models and
the strict UTF-8 JSON logical wire protocol identified by
`forge.tool.endpoint/v1alpha1`.

It implements Query/Action/Session endpoint SPI protocols, validated models, complete
envelope factories, response-correlation validation, registration conversion, typed
payload codecs for every alpha message, a transport-independent Query/Action
`ToolEndpointHandler`, and an optional Arrow/Dora carrier binding. Query, action, and
session are descriptor semantics, not separate wire routes. A concrete Dora business
node implements the SPI and embeds these components; the first YOLO provider-node
embedding and real Query vertical are implemented. Outside this package, the current
Query-only Gateway also has a simple experimental HTTP Query discovery/invoke bridge
and a Dora logical caller vertical bridge.

This is the first tagged/public Tool protocol contract for
`forge.tool.endpoint/v1alpha1`. Earlier untagged prototypes are not compatible and no
backward compatibility is claimed for them. `forge-tool`, Python/Rust/C++
`forge_msgs.ToolMessage` bindings, and Gateway/provider implementations must deploy
this contract atomically; mixed prototype/current deployments are unsupported.

## Runtime API versus endpoint SPI/Wire

The target caller-facing Tool Runtime API is the stable Web/Dora caller surface for
discovery, invoke, status, result, control, and events. It owns invocation/attempt
creation and hides endpoint routing identities. This package does not implement that
Runtime API, and `forge_msgs.ToolMessage` is not its caller-facing carrier. The current
Gateway's simple experimental HTTP Query discovery/invoke bridge and Dora logical
caller vertical bridge exercise only the Query path; neither is the complete Runtime API
or a stable Dora caller contract.

The contracts in this package are provider-side endpoint SPI and Wire. Runtime/Gateway
endpoint routing exchanges Wire v1alpha1 messages with a binding/handler embedded in a
concrete Dora business node; the handler calls the Query/Action/Session SPI implemented
by that same node. There is no independent endpoint execution subject. The YOLO
provider is the first completed concrete direct embedding and real Query vertical.
Additional providers may embed the same boundary directly; a future general runner may
be offered as an optional convenience wrapper, but direct embedding must remain
supported.

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

## Query and Action logical handler

`ToolEndpointHandler` takes the descriptor, the concrete node process instance ID, and
a plain operation implementation mapping:

```python
handler = ToolEndpointHandler(
    descriptor,
    endpoint_instance_id="epinst-001",
    operations={"detect": query_endpoint},
    max_early_events=32,
    max_retained_executions=1024,
)

response = await handler.handle_invoke(request_envelope)
```

Construction requires mapping keys to match descriptor operation names exactly and
checks the callable methods required by each operation semantics. The mapping is copied
so later caller mutation cannot retarget an operation. The legacy `handle_invoke()` API
remains strictly Query-only: it calls `QueryToolEndpoint.query()` and returns a correlated
terminal result or structured rejection. Action invoke/status/result/control must use
`dispatch()`, which calls `ActionToolEndpoint.start()` and returns a response-first tuple
containing any events buffered during `start()`.

The handler's Action execution records, event sequence, early-event buffer, terminal
barrier, and same-execution-key duplicate suppression are private transport state, not a
public execution-store API. Provider status/result/control methods remain authoritative.
The early-event bound defaults to 32. Execution retention defaults to 1024 records and
evicts completed/pre-acceptance records under pressure; both bounds are configurable.
Each operation's descriptor `max_concurrency` is enforced for newly admitted Actions,
and its permit is released exactly once at pre-acceptance rejection or authoritative
terminal establishment.
Terminal events and phases are not exposed until a matching authoritative result is
retained. If dispatch may have started a side effect but acceptance cannot be
established, including cancellation of `start()`, the retained terminal outcome is
`unknown`, duplicate waiters are released, and the handler does not retry. Complete
phase transitions are checked and terminal establishment closes event progression.
Session invocation and execution dispatch remain deferred.

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

binding = DoraToolEndpointBinding(
    handler,
    max_message_bytes=1_048_576,
    max_carrier_bytes=1_114_112,
    event_sink=publish_action_message,
)
response_batch = await binding.handle_input(input_arrow_value)
await binding.dispatch_input(action_input_arrow_value)
```

`handle_input()` accepts one exact `ToolMessage` Arrow `RecordBatch`, single-batch
`Table`, or `StructArray`, preserves the existing Query-only single-response API, and
returns one response `RecordBatch`; it rejects Action without starting it.
`dispatch_input()` accepts implemented execution requests. Action invoke requires the
async `event_sink`, which is the acknowledged publisher for both its response and events:
the binding awaits physical publication of the response before opening the event gate,
then serializes all events in strict sequence order. It returns an empty tuple after
publishing an Action exchange; non-Action requests retain the response-first tuple API.
Event encoding failures propagate to the emitter and never fabricate a second correlated
invoke error. IPC bytes must be decoded upstream under
transport-owned framing and decompression limits; the binding rejects them to prevent a
small compressed frame from allocating an unbounded decoded batch. The outbound logical
encoded-message limit defaults to 1 MiB and is configurable, with a binding minimum of
1 KiB. Accepted requests use 512 bytes less than that limit so a later endpoint or
response-encoding failure has correlated-error headroom. Raw `payload_json` is bounded
before model validation, and the Arrow carrier has a separate configurable pre-decode
limit that defaults to the logical maximum plus 64 KiB of Arrow framing overhead.
Carriers rejected before route trust receive no response. Once a request is accepted,
endpoint exceptions and invalid/oversized responses produce a bounded correlated
`tool.error` with fixed fallback text instead of copying unbounded validation content or
silently dropping the response.

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
endpoint_instance_id    utf8, nullable
operation               utf8, nullable
sequence                int64, nullable
payload_json             utf8, non-null
```

There are no carrier columns for `tool_id` or `implementation_id`; those fields stay
inside the invoke context encoded in `payload_json`. There is no observation timestamp
or request-fingerprint column, and Wire v1alpha1 defines no Wire/Arrow fingerprint.
For `tool.event` and unsolicited `endpoint.status`, the logical envelope omits
`request_id` and the carrier value must be null. Registration, unregister, and
`endpoint.registry.response` require a non-null carrier value. `endpoint_instance_id`
may be null on any `tool.*` message before provider routing; every `endpoint.*` message,
including `endpoint.status`, requires it.

Python↔C++ Arrow IPC read/write interop is covered. Rust coverage validates the exact
schema, model, and RecordBatch conversion; Python↔Rust IPC coverage is not claimed.
The optional Python binding bridges this carrier to the embedded handler. It owns no
concrete Dora node wiring or Dora router; Action transport execution state remains
private to the handler. The completed YOLO provider node supplies its Query wiring
outside the binding.

## Implemented payload schemas

Payload codecs are strict: required fields must be present and unknown fields are
rejected. Mapping fields shown as `{}` are object-valued.

| Message variant | Valid payload example |
| --- | --- |
| `endpoint.register` | `{"descriptor":{"protocol_version":"forge.tool.endpoint/v1alpha1","endpoint_id":"vision.yolo","operations":[{"name":"detect","semantics":"query","cancellable":false,"stoppable":false,"status_supported":false,"max_concurrency":1}]}}` |
| `endpoint.unregister` | `{}` |
| Registry accepted register | `{"operation":"register","status":"accepted","registry_revision":1,"lease_ttl_ms":30000}` |
| Registry accepted unregister | `{"operation":"unregister","status":"accepted","registry_revision":2}` |
| Registry rejected | `{"operation":"unregister","status":"rejected","registry_revision":2,"error":{"code":"STALE_ENDPOINT_INSTANCE","message":"endpoint instance is not current","retryable":false,"details":{}}}` |
| `endpoint.status` | `{"status":{"state":"ready","active_invocations":0,"details":{}}}` |
| `tool.invoke.request` | `{"arguments":{},"context":{"tool_id":"forge.tool.detect","implementation_id":"yolo","metadata":{}}}` |
| Invoke completed | `{"outcome":"completed","result":{"status":"succeeded","outputs":{}}}` |
| Invoke accepted | `{"outcome":"accepted","accepted":{"details":{}}}` |
| Invoke rejected | `{"outcome":"rejected","error":{"code":"INVOKE_REJECTED","message":"execution was not accepted","retryable":false,"details":{}}}` |
| `tool.status.request` | `{}` |
| `tool.status.response` | `{"status":{"phase":"running","details":{}}}` |
| `tool.result.request` | `{}` |
| Result pending | `{"status":"pending"}` |
| Result available | `{"status":"available","result":{"status":"succeeded","outputs":{}}}` |
| Result not found | `{"status":"not_found"}` |
| Control cancel request | `{"command":"cancel"}` |
| Control stop request | `{"command":"stop","reason":"operator requested stop"}` |
| Control accepted response | `{"response":{"command":"cancel","status":"accepted","details":{}}}` |
| `tool.event` | `{"type":"progress","data":{}}` |
| `tool.error` | `{"error":{"code":"TRANSPORT_FAILURE","message":"request exchange failed","retryable":true,"details":{}}}` |

`ToolError` always contains non-empty `code` and `message`, boolean `retryable`, and
object `details`.

A terminal `ToolResult` contains required `status` and object `outputs`, plus a
conditional `error`. Status is `succeeded`, `failed`, `cancelled`, `stopped`, or
`unknown`. `failed` and `unknown` require `error`; the other statuses forbid it.

Execution phase is `accepted`, `running`, `stopping`, `completed`, `failed`,
`cancelled`, `stopped`, or `unknown`. `failed` and `unknown` require `error`; all
other phases forbid it. A control response status is `accepted`, `rejected`,
`terminal`, or `unsupported`; only `rejected` requires and permits `error`.

`EndpointRegistryResponse` has operation `register` or `unregister`, status `accepted`
or `rejected`, and a required non-negative interoperable `registry_revision`. Accepted
register responses require a positive `lease_ttl_ms` duration; accepted unregister
responses forbid it. Accepted responses
forbid `error`; rejected responses forbid the lease and require a `ToolError`.
Forbidden conditional members must be absent: explicit `lease_ttl_ms: null` and
`error: null` are invalid. The lease is a duration, not an observation timestamp.

Event type is `progress`, `heartbeat`, `executor_completed`, `executor_failed`,
`cancelled`, or `stopped`. The outer event schema is frozen; type-specific `data`
schemas remain future work. `endpoint.status` and `tool.event` remain implemented
protocol/model messages, but the current Query-only Gateway does not accept or route
either one. It performs no current-instance validation for `endpoint.status` and no
event correlation for `tool.event`; current execution routing handles only the invoke
terminal response or correlated `tool.error`.

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
| Any phase | repeated observation of the same phase |
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
unregister, Registry response, and endpoint status. Registration and unregister require
`request_id`; unsolicited endpoint status always omits it.
`make_endpoint_registry_response_envelope` copies request and endpoint identities from
the originating management request. `make_invoke_request_envelope` accepts
`endpoint_instance_id=None` so a logical caller can request Gateway resolution. Invoke
response and error factories copy an unresolved identity unchanged, preserving exact
`None` correlation; non-P0 status/result/control request factory APIs remain concrete.
Provider-routed requests and responses carry concrete instance IDs. A logical
`tool.event` omits `request_id`; its Arrow carrier representation uses null.

Raw payload adapters remain public for transport integration and advanced use.
`validate_management_response_correlation(request, response)` verifies Registry
response type, `request_id`, endpoint identities, and operation.
`validate_response_correlation(request, response)` verifies execution response type and matching
`request_id`, `invocation_id`, `attempt_id`, `endpoint_id`,
`endpoint_instance_id`, and `operation`; normal control responses must also echo the
request command. A correlated `tool.error` may answer any execution request.

## Execution identity, correlation, and Registry contract

`request_id` is the correlation identity for one request/response exchange; response
factories copy it from the paired request. `invocation_id + attempt_id` is the execution
identity (`ToolExecutionKey`) used to associate invoke, status, result, control, and
event messages with one attempt. `endpoint_instance_id` identifies the selected
provider route. These are identity/correlation definitions, not delivery guarantees.

Wire v1alpha1 provides no response replay, public retention window, idempotency, or exactly-once
guarantee and freezes no structural fingerprint or public deduplication contract. The
embedded Action handler does bounded, module-private duplicate suppression while an
execution key remains in its configured retention ledger, so duplicate delivery does
not restart a retained side effect. Evicted keys and process restart carry no guarantee.
This does not add a Wire field or caller-facing replay guarantee. P0 does not
automatically retry Query, and `ToolError.retryable` remains descriptive metadata.

The current Gateway uses statically configured, trusted routes. A route authorizes its
configured `endpoint_id`; the envelope and registration descriptor must match it. The
Registry stores at most one current instance, exact descriptor, and lease for each
configured endpoint. `endpoint.register` is sent periodically and acts as
announce/upsert/renew:

- no current instance: accept and create current state, incrementing revision once;
- same route, same instance, exactly equal descriptor: renew without incrementing;
- same instance, changed descriptor: reject without renewing or incrementing;
- same route, new instance: atomically replace current and increment exactly once.

A matching unregister removes current and increments revision. With no current
instance, unregister is effect-idempotently accepted without state or revision change.
An unregister from a stale instance is rejected and cannot remove a different current
instance. Lease expiry removes current and increments revision. The current Registry
path does not process `endpoint.status`; Gateway handling is deferred until a concrete
availability/health requirement exists.

`registry_revision` is only a process-local availability-state revision. Responses
report the process-local revision after the current decision. Gateway restart begins
with empty current state and a fresh revision, and periodic `endpoint.register` restores
availability. The `forge-tool` package does
not implement this stateful Gateway Registry.

## Endpoint sequence contract

The endpoint sequence scope remains
`endpoint_instance_id + invocation_id + attempt_id`. An endpoint event producer assigns
`0` first and then strict `+1`; sequence never wraps and no event may be assigned after
`2^53-1`. Sequence communicates producer order only. P0 provides no retained event
history, duplicate suppression, gap recovery, or event replay guarantee.

This is a Wire value/ordering rule, not a public sequencing/state helper or production
event store/router. The previous `forge_tool.host` surface and its public P1 primitives
have been removed.

## Scope

The Python endpoint contracts, models, logical codecs, complete factories, and
correlation validator are implemented. The exact 10-column Arrow/Dora carrier is also
implemented in Python, Rust, and C++, with Python↔C++ Arrow IPC interop coverage; no
Python↔Rust IPC coverage is claimed.

No independent endpoint execution service or public identity/state/sequence/replay/
deduplication primitive surface is part of the supported scope. Operation mapping,
Query handling, Action invoke/status/result/control/event handling, and the optional
Arrow carrier binding are implemented. The first concrete YOLO provider-node embedding
and real Query vertical are also complete. Additional providers, a general runner, and
Session handling remain future work. A runner cannot become the only integration path.

Outside this package, the current Query-only Gateway implements the configured-route Registry, invoke terminal response/error
correlation, a simple experimental HTTP Query discovery/invoke bridge, and a Dora
logical caller vertical bridge. `endpoint.status` handling, `tool.event` correlation,
the complete caller-facing Tool Runtime API, a stable Dora caller contract,
Gateway-side Action/Session routing, SSE, and MCP remain future work. `PolicyCommand` remains retained
unchanged; migration or deprecation is not in scope.

## License

Apache-2.0.
