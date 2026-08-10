# Forge ToolEndpoint Wire Protocol v1alpha1

Status: implemented alpha endpoint models, logical contract, complete factories,
Query-first operation handling, exact Arrow/Dora carrier schema, and an optional Python
Arrow carrier binding. `DoraToolEndpointBinding` converts one Arrow input through the
logical Query handler into an Arrow response without owning a Dora node, event loop,
metadata, or execution state. Concrete Dora node embedding, Action/Session handling,
Registry/Gateway, Web, and Tool Runtime remain future work; no public
identity/state/sequence primitives are claimed.

This contract defines low-rate endpoint registration and Tool execution lifecycle
messages. It does not carry images, joint state, joint commands, trajectory feedback,
or other high-rate Dora data.

## Boundary: Runtime API, endpoint SPI, and Wire

This is the endpoint SPI/Wire contract, not the caller-facing Tool Runtime API. Web and
Dora callers use the Runtime's discovery/invoke/status/result/control/events API; they
do not supply internal attempt or endpoint routing identities and do not call endpoint
SPI directly.

On the provider side, a concrete Dora business node implements the Query/Action/Session
endpoint SPI and embeds a ToolEndpoint binding/handler. Runtime/Gateway endpoint routing
uses this Wire contract to communicate with that embedded handler, which binds the
selected operation to the node's SPI implementation. A future optional runner may wrap
this integration for convenience, but it is not the only implementation path. The
location of Dora integration dependencies is intentionally left to the vertical spike.

## Version and logical encoding

- Protocol identifier: `forge.tool.endpoint/v1alpha1`
- Logical encoding: one UTF-8 JSON object per message
- Object keys must be strings and strings must contain valid Unicode scalar values
- Numbers must be finite; `NaN` and infinities are invalid
- Integer values are limited to the interoperable JSON range `±(2^53-1)`
- Payload nesting is limited to 64 levels
- The default encoded message limit is 1 MiB and is codec/transport-configurable
- Duplicate JSON keys, unknown top-level envelope fields, and explicit `null` ID
  fields are invalid
- The Python codec emits deterministic compact JSON with sorted keys; this output is
  a convenience encoding, not a canonical identity representation

### First-release deployment contract

`forge.tool.endpoint/v1alpha1` remains the protocol identifier. No tagged or public
Forge Tool protocol release predates this contract; this is the first atomic release
of the identifier. Earlier untagged prototypes are not compatible with this contract,
and this release makes no backward-compatibility claim for them.

The `forge-tool` logical package, Python/Rust/C++ `forge_msgs.ToolMessage` bindings,
and every Gateway and provider using this protocol must be deployed as one coordinated
version set. Mixed deployment with an earlier untagged prototype is unsupported and
must not be treated as compatible merely because the protocol identifier is also
`forge.tool.endpoint/v1alpha1`.

The exact Arrow carrier schema used by the Dora binding is part of this contract and
is implemented as documented below. It carries the logical message without changing
its identities or semantics. The optional Python Arrow carrier binding is implemented. It enforces a configurable
logical encoded-message limit, reserves bounded correlated-error headroom before
accepting requests, and applies separate pre-parse raw payload and in-memory Arrow
carrier limits. IPC bytes must be decoded by the upstream transport under bounded
framing and decompression limits before entering the binding; concrete Dora node I/O
wiring and Web framing remain future work.

## Logical envelope

A Tool execution request has this shape:

```json
{
  "protocol": "forge.tool.endpoint/v1alpha1",
  "message_type": "tool.invoke.request",
  "request_id": "req_001",
  "invocation_id": "inv_001",
  "attempt_id": "att_001",
  "endpoint_id": "policy.lerobot",
  "endpoint_instance_id": "epinst_001",
  "operation": "execute",
  "payload": {
    "arguments": {},
    "context": {
      "tool_id": "robot.execute",
      "implementation_id": "lerobot.primary",
      "metadata": {},
      "deadline_ms": 1786200000000
    }
  }
}
```

The exact top-level field set is:

```text
protocol
message_type
request_id             required for request/response exchanges; forbidden for endpoint.status and tool.event
invocation_id          Tool execution messages only
attempt_id             Tool execution messages only
endpoint_id
endpoint_instance_id
operation               Tool execution messages only
sequence                tool.event only
payload
```

Absent optional fields are omitted, not encoded as `null`. Every message requires
`protocol`, `message_type`, `endpoint_id`, `endpoint_instance_id`, and an object-valued
`payload`. Logical `tool.event` and unsolicited `endpoint.status` messages omit
`request_id`; their nullable Arrow carrier column is null.

The logical envelope has no observation timestamp. In particular, it has no
`timestamp_ms`, receive-time, or observed-at field. Observation time comes from the
transport context:

- Dora uses Dora event context;
- Web uses Gateway request/event context;
- endpoint liveness uses the Gateway's monotonic receive time.

`deadline_ms` remains execution-semantic context. It is an absolute Unix epoch
timestamp in milliseconds and must be a non-negative integer no greater than
`2^53-1`.

## Arrow/Dora carrier

`forge_msgs.ToolMessage` is an exact-schema, single-row Arrow carrier. Its columns,
order, types, and nullability are frozen:

| Column | Arrow type | Nullable |
| --- | --- | --- |
| `protocol` | `utf8` | no |
| `message_type` | `utf8` | no |
| `request_id` | `utf8` | yes |
| `invocation_id` | `utf8` | yes |
| `attempt_id` | `utf8` | yes |
| `endpoint_id` | `utf8` | no |
| `endpoint_instance_id` | `utf8` | no |
| `operation` | `utf8` | yes |
| `sequence` | `int64` | yes |
| `payload_json` | `utf8` | no |

This is exactly 10 columns. Endpoint identities are non-null for every carrier row.
There are no top-level `tool_id` or `implementation_id` columns; those invocation
context fields remain inside the JSON object encoded by `payload_json`. There is no
observation timestamp or request-fingerprint column, and Wire v1alpha1 defines no
Wire or Arrow fingerprint.

For `tool.event` and unsolicited `endpoint.status`, the logical envelope omits
`request_id` and the carrier stores null in that column. `endpoint.register`,
`endpoint.heartbeat`, `endpoint.unregister`, and `endpoint.registry.response` require
a non-null value. The other nullable columns follow the required/forbidden identity matrix for their
message class. `payload_json` encodes exactly the logical `payload`
object, not the complete logical envelope.

Python, Rust, and C++ carrier implementations exist. Python↔C++ Arrow IPC interop is
covered in both write/read directions. Rust coverage establishes the exact schema,
model validation, and RecordBatch conversion; this contract does not claim
Python↔Rust IPC coverage. The implemented carrier schema does not imply that an
endpoint node's stateful Dora binding/handler or router exists.

## Identity and correlation

- `request_id` correlates one request/response exchange. An exchange retry preserves
  it, but management Registry effects and replay decisions never use it as a dedup key.
- `invocation_id` identifies one Runtime-owned logical Tool invocation.
- `attempt_id` identifies one Runtime-owned implementation attempt within an
  invocation.
- The flat pair `invocation_id` + `attempt_id` is the `ToolExecutionKey`; it is not a
  nested envelope object.
- `endpoint_id` is the stable logical endpoint identity advertised by the
  descriptor.
- `endpoint_instance_id` is an opaque process-start identity. Each restart creates a
  new value. It is unordered and cannot determine which racing registration is
  newer.
- `operation` names an operation advertised by the endpoint descriptor.
- An endpoint-local `execution_id`, if needed, is private state of the concrete
  endpoint node/embedded handler. It never replaces `ToolExecutionKey` and is not a
  logical correlation header.

All Tool execution messages require non-empty `invocation_id`, `attempt_id`,
`endpoint_id`, `endpoint_instance_id`, and `operation`. All require a non-empty
`request_id` except `tool.event`, which forbids it: the logical field is omitted and
the Arrow carrier value is null. Invoke and event processing preserve
`ToolExecutionKey`; control, status, and result use it to locate execution state.

Every endpoint-management message requires non-empty `endpoint_id` and
`endpoint_instance_id`. `endpoint.register`, `endpoint.heartbeat`,
`endpoint.unregister`, and `endpoint.registry.response` require a non-empty
`request_id`; unsolicited `endpoint.status` forbids it. Endpoint-management messages forbid
`invocation_id`, `attempt_id`, `operation`, and `sequence`.

`tool.event` requires a top-level `sequence` integer in `[0, 2^53-1]`. `sequence` is
forbidden on every other message. Its endpoint ordering scope is:

```text
endpoint_instance_id + invocation_id + attempt_id
```

Within each scope, the endpoint node's embedded handler assigns the first event
sequence `0` and increments strictly by `1`. A retained sequence paired with the same
structurally equal event is a duplicate; the same retained sequence paired with a
different event is a conflict. A sequence higher than the next expected value is a gap
and requires recovery from retained history or authoritative status/result; missing
events are never invented. A lower sequence no longer present in retained history is
expired/stale and is not processed as new. Sequence never wraps: after `2^53-1`,
another assignment fails with an exhaustion error. These are normative Wire semantics;
the contract does not define a public sequencing API or claim implemented production
retention/routing. The Runtime may assign a separate invocation-scoped sequence when it
exposes events to callers; that caller-facing sequence is not this endpoint sequence.

## Message types

Endpoint management:

- `endpoint.register`
- `endpoint.unregister`
- `endpoint.heartbeat`
- `endpoint.registry.response`
- `endpoint.status`

Tool execution:

- `tool.invoke.request`
- `tool.invoke.response`
- `tool.status.request`
- `tool.status.response`
- `tool.result.request`
- `tool.result.response`
- `tool.control.request`
- `tool.control.response`
- `tool.event`
- `tool.error`

There are no query-, action-, or session-specific wire routes. Query/action/session
semantics come from the selected operation in the endpoint descriptor. The concrete
endpoint node's embedded logical request handler receives `tool.invoke.request`, looks
up that operation binding, and calls the appropriate query/action/session endpoint SPI.
Callers do not redeclare semantics in a message type or route.

All message payloads below are strict: every displayed field is required unless it
is explicitly marked optional, and unknown fields are rejected. Object placeholders
such as `{}` may contain arbitrary JSON-compatible data unless a stricter shape is
documented.

## Shared payload objects

### ToolError

Every structured Tool error has exactly this shape:

```json
{
  "code": "CONTROL_REJECTED",
  "message": "execution cannot be cancelled",
  "retryable": false,
  "details": {}
}
```

`code` and `message` must be non-empty strings, `retryable` must be a boolean, and
`details` must be an object. All four fields are required.

### ToolResult

A terminal `ToolResult` has this shape:

```json
{
  "status": "succeeded",
  "outputs": {}
}
```

For an error-bearing result it has this shape:

```json
{
  "status": "failed",
  "outputs": {},
  "error": {
    "code": "EXECUTION_FAILED",
    "message": "executor failed",
    "retryable": false,
    "details": {}
  }
}
```

`status` must be one of:

- `succeeded`
- `failed`
- `cancelled`
- `stopped`
- `unknown`

`outputs` is always required and must be an object. `failed` and `unknown`
results require `error`. `succeeded`, `cancelled`, and `stopped` results must omit
`error`. A result is the authoritative terminal endpoint-execution payload; events
are not a substitute for retaining and retrieving it. `unknown` means the final
execution outcome cannot be recovered; it does not mean that a result lookup is
merely pending or unavailable.

## Endpoint-management payloads

### Registration

`endpoint.register` carries an endpoint descriptor, not a Runtime ToolSpec:

```json
{
  "descriptor": {
    "protocol_version": "forge.tool.endpoint/v1alpha1",
    "endpoint_id": "vision.yolo",
    "operations": [
      {
        "name": "detect",
        "semantics": "query",
        "cancellable": false,
        "stoppable": false,
        "status_supported": false,
        "max_concurrency": 4
      }
    ]
  }
}
```

The payload contains exactly one `descriptor`. The descriptor contains exactly
`protocol_version`, `endpoint_id`, and `operations`. Its `protocol_version` must equal
`forge.tool.endpoint/v1alpha1`, and its `endpoint_id` must equal the envelope
`endpoint_id`.

`operations` is a non-empty array with unique operation names. Each operation
contains exactly `name`, `semantics`, `cancellable`, `stoppable`,
`status_supported`, and `max_concurrency`. `name` is non-empty, the three capability
fields are booleans, and `max_concurrency` is an integer greater than zero.

Capabilities are constrained by `semantics`:

| Semantics | `cancellable` | `stoppable` | `status_supported` |
| --- | --- | --- | --- |
| `query` | `false` | `false` | `false` |
| `action` | `true` or `false` | `false` | `true` |
| `session` | `false` | `true` or `false` | `true` |

The descriptor reports what the endpoint can execute; it does not replace the
Runtime ToolSpec. The Runtime separately owns ToolSpec loading, implementation
selection, input/output schemas, retry policy, and CompletionSpec.

### Unregister and heartbeat

`endpoint.unregister` and `endpoint.heartbeat` both require an empty payload:

```json
{}
```

### Registry response

`endpoint.registry.response` is the correlated response to an
`endpoint.register`, `endpoint.heartbeat`, or `endpoint.unregister` request. An
accepted registration or heartbeat has this exact payload:

```json
{
  "operation": "register",
  "status": "accepted",
  "registry_revision": 12,
  "lease_ttl_ms": 30000
}
```

An accepted unregister omits the lease duration:

```json
{
  "operation": "unregister",
  "status": "accepted",
  "registry_revision": 13
}
```

A rejected operation omits the lease duration and requires a `ToolError`:

```json
{
  "operation": "heartbeat",
  "status": "rejected",
  "registry_revision": 13,
  "error": {
    "code": "STALE_ENDPOINT_INSTANCE",
    "message": "endpoint instance is not current",
    "retryable": false,
    "details": {}
  }
}
```

`operation` is `register`, `heartbeat`, or `unregister` and must match the
originating request type. `status` is `accepted` or `rejected`.
`registry_revision` is required and is an integer in `[0, 2^53-1]`. For an accepted
`register` or `heartbeat`, `lease_ttl_ms` is required, is an integer in
`[1, 2^53-1]`, and `error` is forbidden. For an accepted `unregister`, both
`lease_ttl_ms` and `error` are forbidden. A rejected response forbids
`lease_ttl_ms` and requires `error`. Conditional members are presence-sensitive:
when forbidden they must be absent; explicit `lease_ttl_ms: null` and `error: null`
are invalid.

`lease_ttl_ms` is a duration measured from the trusted Gateway monotonic receive
observation that anchors Registry acceptance and lease start, as defined below. It is
not an observation timestamp or absolute time. The response copies `request_id`,
`endpoint_id`, and `endpoint_instance_id` from the originating request; those identities
are not duplicated in the payload.

### Endpoint status

`endpoint.status` has exactly this payload:

```json
{
  "status": {
    "state": "ready",
    "active_invocations": 0,
    "details": {}
  }
}
```

`state` is one of `ready`, `busy`, `degraded`, or `unavailable`.
`active_invocations` is a non-negative integer and `details` is an object. Endpoint
identity comes from the envelope and is not duplicated in the payload.
`endpoint.status` is an unsolicited health snapshot and always omits `request_id`.
It is not an acknowledgement of registration, heartbeat, or unregister;
acknowledgements use `endpoint.registry.response`.

### Registry cardinality, source authority, and lookup precedence

The following is the frozen stateful Registry contract. The Registry has at most one
current `endpoint_instance_id` for each `endpoint_id`. Replacing a current registration
with a new instance must be authorized by a trusted transport generation, lease, or
equivalent source binding. The opaque instance ID alone cannot order racing
registrations. Heartbeat, status, and unregister messages only affect the accepted
current instance from its accepted source; stale or untrusted instances cannot
refresh, mutate, or remove the current registration.

For any `endpoint_id`, Registry lookup precedence is exactly:

```text
current instance > last tombstone > absent
```

An operation is evaluated against the first state that exists in this order. Accepting
a new registration clears that endpoint's tombstone before the new current state is
exposed. The cleared tombstone is no longer replayable; an old unregister cannot match
it after the new registration has been accepted.

### Tombstone contract

The Registry retains at most the last tombstone for each `endpoint_id`. A tombstone
stores exactly the identity and authority needed for replay decisions:

- `endpoint_id`;
- `endpoint_instance_id`;
- the accepted trusted source binding and source generation;
- the historical removal revision;
- reason `unregister` or `expired`.

The tombstone is retained until a new registration for that `endpoint_id` is accepted
or the Gateway process restarts. It is process-memory state and is not persisted across
Gateway restart.

When no current instance exists, an unregister matching the tombstone's endpoint
identity and accepted trusted source binding/generation returns accepted with the
historical removal or expiry revision stored in that tombstone. It does not increment
the process-global revision. This remains true if unrelated endpoint changes have
advanced the current process-global `registry_revision`. A non-matching unregister is
not a tombstone replay and follows the normal authority/rejection rules.

### Registration precedence and replay

Management `request_id` is correlation only and is never a Registry dedup key.
Registration decisions use current state first, then tombstone state, then absence:

- With a current instance, an idempotent register renewal requires the same accepted
  trusted source binding/generation, the same `endpoint_instance_id`, and exact endpoint
  descriptor equality. It renews the lease without incrementing the revision.
  A descriptor change for that current identity is rejected. Replacement by another
  instance or source generation remains subject to the existing trusted source/current
  instance authority rules.
- With an explicit-unregister tombstone and no current instance, a registration with the
  exact same trusted source binding, source generation, and `endpoint_instance_id` is
  rejected non-retryably as tombstoned. This prevents a delayed registration from
  resurrecting an explicitly removed instance.
- With that explicit-unregister tombstone, a different instance or a newer trusted
  source generation may register when authorized. Acceptance clears the tombstone,
  creates a new current lease, and increments the process-global revision once.
- With an expiry tombstone and no current instance, a matching registration is allowed.
  Acceptance clears the tombstone, creates a new current lease, and increments the
  process-global revision once, allowing recovery after missed heartbeats.
- With no current instance and no tombstone, an authorized accepted registration creates
  current state and increments the process-global revision once.

A rejected registration leaves any tombstone intact. Only acceptance clears it.

### Lease receive observation and revision responses

The Gateway transport adapter captures a trusted monotonic receive observation before
validating each management message. If the operation is accepted, Registry acceptance
and lease start are logically anchored to that captured observation, not to the later
validation-completion or response-send time. New/replacement/recovery registrations
start their lease there. Every accepted idempotent register replay and heartbeat renews
its lease from that captured receive observation. No receive observation, lease start,
lease deadline, expiry time, or other timestamp appears on the wire.

An accepted unregister against current state removes it, creates a reason `unregister`
tombstone, and increments `registry_revision` once. Expiry removes current state,
creates a reason `expired` tombstone, and increments it once. Rejections never increment
it.

`registry_revision` is a Gateway-process-global monotonically increasing state-change
revision. Each authoritative Registry state change increments it exactly once. Accepted
current-instance register renewals and heartbeats do not increment it and report the
process-global revision in effect for their decision. Rejections likewise report the
process-global revision without incrementing it. The matching unregister tombstone
replay is the explicit exception: it reports the tombstone's stored historical removal
or expiry revision, even when unrelated endpoints have advanced the process-global
revision.

The revision orders Registry state changes within one Gateway process; it is not a
wall-clock value, observation timestamp, lease deadline, or cross-process persistent
version. These revision and lease rules do not weaken the cardinality or trusted
source-authority contract.

## Tool execution payloads

### Invoke request

`tool.invoke.request` has exactly this payload:

```json
{
  "arguments": {},
  "context": {
    "tool_id": "robot.execute",
    "implementation_id": "lerobot.primary",
    "metadata": {},
    "caller_id": "runtime.client",
    "deadline_ms": 1786200000000
  }
}
```

`arguments` is an object. Within `context`, `tool_id`, `implementation_id`, and
`metadata` are required; the first two are non-empty strings and `metadata` is an
object. `caller_id` and `deadline_ms` are optional. The encoder omits them when unset;
the decoder also accepts JSON `null`. A non-null `caller_id` is a non-empty string,
and a non-null `deadline_ms` satisfies the range rule above.

`ToolExecutionKey`, `endpoint_id`, and `operation` are reconstructed from the
envelope and are not duplicated in `context`.

### Invoke response

`tool.invoke.response` is one of three exact discriminated shapes.

A synchronously completed invoke contains a terminal result:

```json
{
  "outcome": "completed",
  "result": {
    "status": "succeeded",
    "outputs": {}
  }
}
```

An asynchronously accepted invoke contains required acceptance details:

```json
{
  "outcome": "accepted",
  "accepted": {
    "details": {}
  }
}
```

A rejected invoke contains a ToolError:

```json
{
  "outcome": "rejected",
  "error": {
    "code": "INVOKE_REJECTED",
    "message": "execution was not accepted",
    "retryable": false,
    "details": {}
  }
}
```

The `outcome` discriminator and its matching `result`, `accepted`, or `error` field
are required; fields from the other variants are forbidden. `rejected` means the
endpoint declined the invoke before acceptance and before execution side effects. A
Query execution failure is instead a completed terminal `ToolResult` with status
`failed`; an endpoint implementation must not use `ToolEndpointError` after execution
has begun.

### Status request and response

`tool.status.request` uses `ToolExecutionKey` from the envelope and requires an empty
payload:

```json
{}
```

`tool.status.response` has exactly this payload:

```json
{
  "status": {
    "phase": "running",
    "details": {}
  }
}
```

`phase` is one of `accepted`, `running`, `stopping`, `completed`, `failed`,
`cancelled`, `stopped`, or `unknown`. `details` is always required and must be an
object. `failed` and `unknown` require a ToolError-valued `error`; every other phase
must omit `error`:

```json
{
  "status": {
    "phase": "failed",
    "details": {},
    "error": {
      "code": "EXECUTOR_FAILED",
      "message": "executor failed",
      "retryable": false,
      "details": {}
    }
  }
}
```

`completed` means that the endpoint executor considers its work complete. `unknown`
means the final executor outcome cannot be recovered. The Tool Runtime still owns
final CompletionSpec evaluation.

### Result request and response

`tool.result.request` uses `ToolExecutionKey` from the envelope and requires an empty
payload:

```json
{}
```

Action and Session endpoint `result()` returns a `ToolResultResponse`, not an
optional `ToolResult`. `tool.result.response` is one of these exact lookup shapes:

```json
{"status": "pending"}
```

```json
{
  "status": "available",
  "result": {
    "status": "succeeded",
    "outputs": {}
  }
}
```

```json
{"status": "not_found"}
```

Lookup `status` is `pending`, `available`, or `not_found`. `available` requires a
terminal `ToolResult`; `pending` and `not_found` forbid `result`. `pending` means the
known execution has no terminal result yet. `not_found` means the execution key has
no retained result/record. Neither is the terminal ToolResult status `unknown`, which
means the execution's final outcome itself cannot be recovered.

### Control request and response

`tool.control.request` has one of these shapes:

```json
{
  "command": "cancel"
}
```

```json
{
  "command": "stop",
  "reason": "operator requested stop"
}
```

`command` is `cancel` or `stop`. Optional `reason` is omitted by the encoder when
unset; the decoder also accepts JSON `null`. A non-null `reason` must be a non-empty
string. The request uses `ToolExecutionKey` from the envelope. Descriptor capability
fields determine whether the selected operation supports the command.

`tool.control.response` has exactly this outer shape:

```json
{
  "response": {
    "command": "cancel",
    "status": "accepted",
    "details": {}
  }
}
```

`command` is `cancel` or `stop`; `status` is `accepted`, `rejected`,
`terminal`, or `unsupported`; and `details` is a required object. A
`rejected` response requires a ToolError-valued `error`. Every other status must omit
`error`:

```json
{
  "response": {
    "command": "cancel",
    "status": "rejected",
    "details": {},
    "error": {
      "code": "CONTROL_REJECTED",
      "message": "execution cannot be cancelled",
      "retryable": false,
      "details": {}
    }
  }
}
```

`accepted` means only that the control command was admitted. It does not mean that
the execution is terminal. `terminal` means the execution was already terminal when
the control request arrived; it does not claim that this request caused termination.
Terminal state is observed through status or result.

### Event

`tool.event` carries `sequence` in the top-level envelope and has exactly this
payload shape:

```json
{
  "type": "progress",
  "data": {}
}
```

`type` is one of `progress`, `heartbeat`, `executor_completed`, `executor_failed`,
`cancelled`, or `stopped`. `data` is a required object. The allowed event types and
outer payload shape are frozen; type-specific `data` schemas remain future work.

### Tool error message

`tool.error` is used for a protocol or transport-level execution failure that cannot
be represented as the normal invoke/status/result/control response. Its exact
payload is:

```json
{
  "error": {
    "code": "TRANSPORT_FAILURE",
    "message": "request exchange failed",
    "retryable": true,
    "details": {}
  }
}
```

As an execution message, it carries `ToolExecutionKey` and requires `request_id`. When
a request's route identity is already trusted but its message-specific payload is
invalid, the embedded logical handler returns a correlated non-retryable `tool.error`;
carrier decoding or untrusted-route failures may still be raised to the concrete node.

## Endpoint model invariants

The Python endpoint models are frozen dataclasses. Mapping-valued inputs are
validated as bounded JSON and defensively deep-copied at model construction: keys
must be strings with valid Unicode, strings must be valid Unicode, integers must fit
`±(2^53-1)`, floats must be finite, nesting is limited to 64 levels, and unsupported
values are rejected. The copied mappings are ordinary mutable dictionaries for
standard dataclass serialization, so this is a construction-time invariant; complete
wire construction validates them again.

The models enforce these invariants in addition to the payload rules above:

- `ToolExecutionKey.invocation_id` and `attempt_id` are non-empty strings.
- `ToolContext` requires a `ToolExecutionKey` plus non-empty `tool_id`,
  `implementation_id`, `endpoint_id`, and `operation`; optional `caller_id` and
  `deadline_ms` follow the rules above.
- `ToolRequest.arguments`, `ToolAccepted.details`, `ToolError.details`,
  `ToolResult.outputs`, `ToolControlResponse.details`, `ToolEvent.data`,
  `EndpointStatus.details`, and `ToolExecutionStatus.details` are mappings with
  string keys.
- `ToolError.code` and `message` are non-empty and `retryable` is a boolean.
- `ToolResult` enforces terminal status and error coupling: `failed` and
  `unknown` require an error; all other result statuses forbid one.
- `ToolResultResponse` enforces lookup coupling: `available` requires a
  `ToolResult`; `pending` and `not_found` forbid one.
- `ToolControlResponse` enforces command/status membership and error coupling:
  `rejected` requires an error; `accepted`, `terminal`, and `unsupported`
  forbid one.
- `ToolExecutionStatus` requires an error for `failed` and `unknown` and forbids it
  for every other phase.
- `ToolOperationDescriptor.max_concurrency` is in `[1, 2^53-1]`.
- `EndpointStatus.active_invocations` is in `[0, 2^53-1]`.
- `EndpointRegistryResponse.registry_revision` is in `[0, 2^53-1]`; a present
  `lease_ttl_ms` duration is in `[1, 2^53-1]`, with presence controlled by operation
  and acceptance status.

## Construction and response correlation

Complete `make_*_envelope` factories are the preferred public construction path:

```text
make_invoke_request_envelope      make_invoke_response_envelope
make_status_request_envelope      make_status_response_envelope
make_result_request_envelope      make_result_response_envelope
make_control_request_envelope     make_control_response_envelope
make_event_envelope               make_error_envelope
make_error_response_envelope      make_registration_envelope
make_heartbeat_envelope           make_unregister_envelope
make_endpoint_registry_response_envelope
make_endpoint_status_envelope
```

Execution request and event factories derive `invocation_id`, `attempt_id`,
`endpoint_id`, and `operation` from `ToolContext`. Invoke, status, result, and control
response factories instead accept the originating request envelope and copy its
correlation identity directly; an embedded endpoint handler therefore does not need to
retain the complete invoke context just to answer a later request.
`make_error_response_envelope` follows the same request-based pattern, including when
the request's typed payload cannot be decoded. Registration, heartbeat, and unregister
factories require `request_id`; the unsolicited endpoint-status factory always omits it.
`make_endpoint_registry_response_envelope` accepts the originating management request,
copies its exchange and endpoint identities, and requires the response operation to
match that request. Raw payload adapters remain public for transport integration
and advanced use, but callers assembling a complete message should prefer the
factories.

`validate_management_response_correlation(request, response)` validates
`endpoint.registry.response` type, matching `request_id`, `endpoint_id`, and
`endpoint_instance_id`, and the request/response operation pair.

`validate_response_correlation(request, response)` validates the execution response message
type and equality of `request_id`, `invocation_id`, `attempt_id`, `endpoint_id`,
`endpoint_instance_id`, and `operation`. For a normal control response it also
requires the response command to match the request command. A correlated
`tool.error` is accepted as the error response for invoke, status, result, or control.

## Lifecycle, ordering, and terminal consistency

Wire v1alpha1 normatively defines the following transition relation. The currently
implemented models, codecs, factories, and carriers do not by themselves provide a
stateful embedded request handler, dispatcher, or execution store.

| Semantics/current phase | Allowed next phase |
| --- | --- |
| Query initial | terminal only |
| Action/Session initial | `accepted` or terminal |
| `accepted` | `running`, `stopping`, or terminal |
| `running` | `stopping` or terminal |
| `stopping` | terminal |
| Any phase | the same phase as an idempotent replay |
| Terminal | no different phase |

Here terminal means `completed`, `failed`, `cancelled`, `stopped`, or `unknown`.
Once a terminal phase and result are established, both are immutable. The exact
phase-to-result mapping is:

| Terminal `ExecutionPhase` | Required terminal `ToolResult.status` |
| --- | --- |
| `completed` | `succeeded` |
| `failed` | `failed` |
| `cancelled` | `cancelled` |
| `stopped` | `stopped` |
| `unknown` | `unknown` |

A nonterminal phase (`accepted`, `running`, or `stopping`) cannot be paired with a
terminal result. `validate_execution_result(status, result)` enforces that the status
is terminal and that its result has the exact mapped status.

A terminal event (`executor_completed`, `executor_failed`, `cancelled`, or `stopped`)
closes event progression for that attempt; a later `progress` or `heartbeat` event is
invalid. For asynchronous invoke, related events must not be exposed before the
`accepted` response is established. Early events therefore require a configured,
bounded buffer; overflow must fail deterministically rather than grow without bound.
The buffering mechanism remains private implementation work for the endpoint node's
embedded handler.

A terminal result barrier also applies: the authoritative, matching `ToolResult` must
be retained before a terminal phase or terminal event is exposed, so result/status
recovery does not depend on event delivery. If an Action/Session dispatch may have
started a side effect but raises before `accepted` can be established and the outcome
cannot be recovered, the allowed initial terminal outcome is `unknown`; the system
must not fabricate `accepted` or blindly retry. Retention and barrier integration
remain private implementation work for the endpoint node's embedded handler.

Executor completion and Runtime completion are separate. An endpoint event or
endpoint ToolResult records endpoint execution state. The future Tool Runtime will
apply its CompletionSpec before deciding the caller-facing Tool outcome; Gateway and
the endpoint node's embedded handler must not interpret CompletionSpec.

## Deduplication keys and structural request identity

Wire v1alpha1 defines structural request identity without defining a fingerprint
format. Identity is equality of validated, decoded structural JSON:

- object member order is ignored, while member presence and names participate;
- array order participates;
- strings compare as exact Unicode scalar sequences with no Unicode normalization;
- `null` and booleans retain their JSON types and are distinct from strings and
  numbers;
- numbers compare by finite IEEE-754 binary64 value, so `1` equals `1.0` and `-0`
  equals `0`.

Raw envelope bytes, raw `payload_json` bytes, and codec output are never canonical
request identity. No canonical serialization, digest, or cross-language fingerprint is
required, and no fingerprint field is added to the logical Wire or Arrow carrier.

Execution exchange deduplication uses:

```text
endpoint_instance_id + request_id
```

Its request identity excludes `protocol`, `request_id`, and `endpoint_instance_id`,
but includes `message_type`, every other route field, and the complete decoded
`payload`. The same key and identity replays the established response; reuse with a
different identity fails with `FORGE_PROTOCOL_DEDUP_CONFLICT`.

Execution deduplication uses:

```text
invocation_id + attempt_id
```

For `tool.invoke.request`, invoke identity is exactly `endpoint_id` + `operation` +
the complete decoded `payload`. It excludes the execution key, `request_id`, and
`endpoint_instance_id`. Every `arguments` and `context` field participates, including
optional-field presence, so omission and explicit `null` are structurally different.
The same execution key and invoke identity replays the established accepted response
or terminal result without restarting the side effect; a different invoke identity is
a conflict.

Management `request_id` is correlation only, not deduplication. Management effects
follow the trusted-source/current-identity Registry rules above, including lease renewal,
unregister tombstone replay, and state-change revision behavior. Current models and
carriers do not themselves provide the stateful Registry implementation, asynchronous
execution deduplication cache, execution store, or retention window. Eventual
execution guarantees remain scoped to one endpoint process epoch and its configured
retention window; the protocol does not promise cross-process exactly-once execution.
If a side effect may have occurred but its outcome cannot be recovered, the terminal
result is `unknown` rather than a blind success or retry.

## Implementation scope

Query/Action/Session endpoint SPI models, envelope validation, registration conversion,
typed payload codecs, and complete factories are implemented in `forge-tool`. The exact
10-column Arrow/Dora carrier is implemented in Python, Rust, and C++, with Python↔C++
Arrow IPC interop coverage; no Python↔Rust IPC coverage is claimed.

No independent endpoint execution service is part of the design, and this scope does
not claim implemented or public structural-identity, lifecycle-state, or sequence
primitives.
The previous `forge_tool.host` surface and its public primitives have been removed.
Python `ToolEndpointHandler` now implements exact operation mapping validation,
endpoint/instance route validation, and the Query invoke/result/rejection path. The
optional `forge_tool.dora` module converts `forge_msgs.ToolMessage` Arrow values to and
from that logical path without owning a Dora node or event loop. Embedding the binding
in a concrete endpoint node, the first real Query, Action/Session handling, and only
then private bounded dedup as needed remain implementation work. Registry/Gateway
services, caller-facing Web/Dora Runtime bindings, and Tool Runtime behavior also
remain future work. `PolicyCommand` remains
retained unchanged; migration or deprecation is not in the current scope.
