# Forge ToolEndpoint Wire Protocol v1alpha1

- Status: **released** with Forge Tool `0.1.0`
- Protocol identifier: `forge.tool.endpoint/v1alpha1`

This document is the normative language-neutral contract for low-rate endpoint
registration and provider execution messages. Related documentation:

- [Architecture](ARCHITECTURE.md)
- [Python package guide](../../packages/tool/README.md)
- [Canonical Arrow carrier schema](../forge_msgs/tool.v1.yaml)

The words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** describe protocol requirements.
Examples are non-normative unless the surrounding text explicitly freezes their shape.

## Reading guide

| Reader | Recommended sections |
| --- | --- |
| Gateway / Registry implementer | 1–6, 8, and 10–13 |
| Provider handler/binding implementer | 1–7 and 9–13 |
| Arrow carrier implementer | 3–5, 11, and 12–13 |
| Python endpoint author | Start with the [package guide](../../packages/tool/README.md), then use sections 6–10 as the normative reference. |

## 1. Scope

The protocol defines:

- endpoint registration, unregister, Registry responses, and health snapshots;
- generic invoke, status, result, control, event, and error messages;
- endpoint descriptors and Query/Action/Session operation semantics;
- exchange, execution, and route identity;
- lifecycle, terminal-result, correlation, and event-ordering rules; and
- the mapping to the single-row Arrow `forge_msgs.ToolMessage` carrier.

The protocol does not define:

- the caller-facing Tool Runtime API;
- ToolSpec storage, resolver policy, CompletionSpec, or caller-visible invocation state;
- a stable Web, SSE, Dora caller, MCP, A2A, or OpenAI binding;
- high-rate images, joint state, joint commands, or trajectory feedback;
- replay, persistent idempotency, exactly-once execution, or automatic retry; or
- a mandatory endpoint process/runner implementation.

High-rate or large values remain on the Dora data plane. Tool requests carry small
JSON-compatible arguments or references.

## 2. Architecture boundary

```text
external caller or internal initiator
  -> caller binding / Tool Runtime                 outside this protocol
  -> Gateway router or another conforming sender
  -> ToolEndpoint Wire v1alpha1                    this protocol
  -> provider node [Operator or Adapter]
       ├─ carrier binding
       ├─ logical handler
       └─ Query/Action/Session SPI
```

The normative boundary begins when a ToolEndpoint envelope is constructed for provider
routing or endpoint management. It covers the sender/Registry-to-provider exchange, not
the API through which an external caller discovers or invokes a logical Tool. The Wire
therefore defines the shape and correlation of `invocation_id`, `attempt_id`, and endpoint
routing fields without defining which caller binding created them before routing.

The target architecture assigns logical invocation and implementation-attempt creation to
a Tool Runtime and hides endpoint routing identities from ordinary callers. Experimental
or internal bridges may carry the same pre-routing envelope shape directly, but that does
not make the Endpoint Wire a stable caller API.

Gateway is an Adapter node because it owns external caller and routing boundaries. Tool
Runtime is a logical domain responsibility, normally hosted by Gateway, while Gateway
Registry/router resolves the current concrete endpoint instance and carrier route. A
concrete provider may be either an Operator or Adapter; it implements an endpoint SPI and
embeds a binding/handler. The protocol does not require a Runtime, Gateway, or independent
endpoint-host service to be a standalone process.

## 3. Version and logical encoding

### 3.1 Version

Every message MUST set:

```text
protocol = forge.tool.endpoint/v1alpha1
```

A receiver MUST reject any other value as an unsupported protocol version.

This is the first tagged/public contract for this identifier, released with Tool `0.1.0`
and Msgs `1.2.0`. Earlier untagged prototypes are not a compatibility baseline. A
compatible deployment MUST use one coordinated version set across the logical protocol
package, Python/Rust/C++ carrier bindings, Gateway, and providers. Mixed
prototype/current deployments are unsupported.

### 3.2 JSON rules

A logical message is one UTF-8 JSON object.

- Object keys MUST be strings.
- Keys and strings MUST contain valid Unicode scalar values.
- Numbers MUST be finite; `NaN` and infinities are invalid.
- Integers MUST be in the interoperable range `±(2^53-1)`.
- JSON nesting MUST NOT exceed 64 levels.
- Duplicate object keys are invalid.
- Unknown top-level envelope fields are invalid.
- Message-specific payload objects are closed schemas unless a field is explicitly
  documented as an open JSON object.

Deployments MUST enforce a finite encoded-message limit. The reference Python codec
defaults to 1 MiB and allows the configured transport limit to override it.

The reference Python codec emits compact JSON with sorted keys. That deterministic byte
encoding is a convenience, not a canonical identity or fingerprint. Implementations
MUST NOT use raw envelope bytes or raw `payload_json` bytes as a protocol-defined
idempotency identity.

## 4. Logical envelope

A routed execution request has this shape:

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

### 4.1 Fields

| Field | Meaning |
| --- | --- |
| `protocol` | Protocol identifier; always required. |
| `message_type` | One of the 14 v1alpha1 message types; always required. |
| `request_id` | Correlation identity for one request/response exchange. |
| `invocation_id` | Logical invocation correlation identity assigned before provider routing. |
| `attempt_id` | Correlation identity for one provider implementation attempt. |
| `endpoint_id` | Stable logical endpoint identity; always required. |
| `endpoint_instance_id` | Opaque concrete provider process identity. |
| `operation` | Descriptor operation selected for an execution message. |
| `sequence` | Endpoint event sequence; only valid on `tool.event`. |
| `payload` | Message-specific JSON object; always required. |

All present identifier fields MUST be non-empty strings containing valid Unicode scalar
values. Whitespace-only identifiers are invalid.

### 4.2 Header matrix

`required` means a non-empty value MUST be present. `forbidden` means the logical field
MUST be absent. `optional` means it MAY be absent before provider routing.

| Message class | `request_id` | `invocation_id` / `attempt_id` | `endpoint_instance_id` | `operation` | `sequence` |
| --- | --- | --- | --- | --- | --- |
| `endpoint.register` | required | forbidden | required | forbidden | forbidden |
| `endpoint.unregister` | required | forbidden | required | forbidden | forbidden |
| `endpoint.registry.response` | required | forbidden | required | forbidden | forbidden |
| `endpoint.status` | forbidden | forbidden | required | forbidden | forbidden |
| `tool.event` | forbidden | required | structurally optional; concrete when emitted | required | required |
| every other `tool.*` message | required | required | optional | required | forbidden |

`endpoint_id` and object-valued `payload` are required for every row in the table.

Optional logical-envelope fields MUST be omitted rather than encoded as JSON `null`.
The Arrow carrier represents an omitted optional logical field as Arrow null; an empty
string is never a null sentinel.

All `tool.*` messages may omit `endpoint_instance_id` before provider selection. If the
Gateway selects a provider, it MUST set a concrete instance before forwarding the
request. A provider MUST require an exact match with its own instance. If selection
fails before a provider is chosen, the correlated response/error MAY preserve the
unresolved value by omitting the field.

`tool.event` is provider-originated. A conforming event producer MUST set its concrete
`endpoint_instance_id`, even though the generic envelope/carrier shape remains nullable
for pre-routing Tool messages.

### 4.3 Time

The envelope and Arrow carrier have no observation timestamp. In particular, they have
no `timestamp_ms`, receive-time, or observed-at field.

Observation time belongs to transport context:

- Dora uses Dora event context;
- Web uses Gateway request/event context; and
- Registry lease timing uses trusted Gateway monotonic receive time.

`deadline_ms` is different: it is optional execution context, represented as a
non-negative absolute Unix epoch timestamp in milliseconds no greater than `2^53-1`.

## 5. Identity and delivery scope

### 5.1 Identity layers

```text
request_id
    one request/response exchange

invocation_id
    one logical Tool invocation

attempt_id
    one provider implementation attempt

ToolExecutionKey
    invocation_id + attempt_id

endpoint_id
    one stable logical endpoint

endpoint_instance_id
    one opaque process-start identity
```

`ToolExecutionKey` is the flat pair `invocation_id + attempt_id`; it is not a nested
Wire object. Invoke, status, result, control, event, and error messages for one attempt
carry the same pair.

An endpoint-local `execution_id` or executor handle MAY exist as private provider state.
It MUST NOT replace `ToolExecutionKey` or become a logical correlation header.

`endpoint_instance_id` is identity, not ordering. Every provider process start, including
restart, MUST generate a new value. A receiver MUST NOT compare instance IDs to decide
which process is newer.

### 5.2 No implied delivery guarantee

These identities define correlation only. Wire v1alpha1 provides no public guarantee of:

- request or response replay;
- exchange or execution deduplication;
- a retention window;
- idempotency;
- exactly-once execution;
- automatic retry; or
- canonical request fingerprinting.

Duplicate delivery may execute again unless a specific implementation documents a
private, bounded protection window. Such protection does not become a Wire guarantee.

`ToolError.retryable` is descriptive metadata. It MUST NOT by itself trigger an
automatic retry. An explicit caller/Runtime policy MAY consider it together with operation
semantics, side-effect safety, attempt history, and outcome certainty. If a side effect
may have occurred and the outcome cannot be recovered, the terminal result is `unknown`,
not a blind retry or success.

## 6. Message family and operation semantics

### 6.1 Message types

Endpoint management:

- `endpoint.register`
- `endpoint.unregister`
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

There are no Query-, Action-, or Session-specific message types. The selected operation
in the endpoint descriptor supplies semantics. A caller or transport MUST NOT redeclare
semantics in a route or message type.

All payloads below are strict. Every displayed field is required unless marked optional,
and unknown fields are rejected. A displayed `{}` denotes an open JSON object unless a
stricter shape is stated.

### 6.2 Endpoint descriptor

An endpoint descriptor reports provider capabilities; it is not a Runtime ToolSpec. It
contains exactly:

```json
{
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
```

Requirements:

- `protocol_version` MUST equal `forge.tool.endpoint/v1alpha1`.
- `endpoint_id` MUST be non-empty and MUST equal the envelope `endpoint_id` when
  registered.
- `operations` MUST be a non-empty array with unique, non-empty operation names.
- Every operation contains exactly `name`, `semantics`, `cancellable`, `stoppable`,
  `status_supported`, and `max_concurrency`.
- The three capability fields are booleans.
- `max_concurrency` is an integer in `[1, 2^53-1]`.

Capabilities obey this matrix:

| Semantics | `cancellable` | `stoppable` | `status_supported` |
| --- | --- | --- | --- |
| `query` | `false` | `false` | `false` |
| `action` | `true` or `false` | `false` | `true` |
| `session` | `false` | `true` or `false` | `true` |

Input/output schemas, implementation selection, CompletionSpec, and retry policy belong
to the Runtime ToolSpec, not the endpoint descriptor.

## 7. Shared payload values

### 7.1 `ToolError`

Every structured Tool error has exactly this shape:

```json
{
  "code": "CONTROL_REJECTED",
  "message": "execution cannot be cancelled",
  "retryable": false,
  "details": {}
}
```

`code` and `message` are non-empty strings, `retryable` is a boolean, and `details` is an
object. All four fields are required.

### 7.2 `ToolResult`

A terminal successful result has this shape:

```json
{
  "status": "succeeded",
  "outputs": {}
}
```

An error-bearing result has this shape:

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

`status` is one of:

- `succeeded`
- `failed`
- `cancelled`
- `stopped`
- `unknown`

`outputs` is always required and is an object. `failed` and `unknown` require a
`ToolError`; `succeeded`, `cancelled`, and `stopped` forbid one.

A `ToolResult` is the authoritative terminal provider result. Events are not a
substitute for retaining and retrieving it. `unknown` means the final execution outcome
cannot be recovered; it is not a pending or missing result lookup.

### 7.3 Acceptance, status, result lookup, and control

- `ToolAccepted` contains required object-valued `details` and means only that an
  asynchronous execution was admitted.
- Execution phase is `accepted`, `running`, `stopping`, `completed`, `failed`,
  `cancelled`, `stopped`, or `unknown`.
- `failed` and `unknown` execution status require a `ToolError`; all other phases forbid
  one. Status always contains object-valued `details`.
- Result lookup status is `pending`, `available`, or `not_found`. Only `available`
  contains a `ToolResult`.
- Control command is `cancel` or `stop`.
- Control response status is `accepted`, `rejected`, `terminal`, or `unsupported`.
  Only `rejected` requires and permits a `ToolError`; every response contains
  object-valued `details`.

The exact message payloads are defined below.

## 8. Endpoint management

### 8.1 Registration

`endpoint.register` carries exactly one descriptor:

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

The descriptor obeys section 6.2 and its `endpoint_id` MUST equal the envelope
`endpoint_id`.

`endpoint.register` is announce/upsert/lease renewal. An endpoint sends it periodically;
a descriptor-equal registration from the current instance renews its lease without
changing Registry revision.

### 8.2 Unregister

`endpoint.unregister` has an exactly empty payload:

```json
{}
```

### 8.3 Registry response

`endpoint.registry.response` is the correlated response to registration or unregister.

Accepted registration:

```json
{
  "operation": "register",
  "status": "accepted",
  "registry_revision": 12,
  "lease_ttl_ms": 30000
}
```

Accepted unregister:

```json
{
  "operation": "unregister",
  "status": "accepted",
  "registry_revision": 13
}
```

Rejected operation:

```json
{
  "operation": "unregister",
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

Rules:

- `operation` is `register` or `unregister` and MUST match the originating request.
- `status` is `accepted` or `rejected`.
- `registry_revision` is required and is an integer in `[0, 2^53-1]`.
- Accepted `register` requires `lease_ttl_ms` in `[1, 2^53-1]` and forbids `error`.
- Accepted `unregister` forbids both `lease_ttl_ms` and `error`.
- Rejected responses forbid `lease_ttl_ms` and require `error`.
- Forbidden conditional fields MUST be absent. Explicit `lease_ttl_ms: null` and
  `error: null` are invalid.

`lease_ttl_ms` is a duration measured from the trusted monotonic receive observation
that anchors the accepted registration. It is not an absolute time or observation
timestamp.

### 8.4 Endpoint status

`endpoint.status` is an unsolicited health snapshot:

```json
{
  "status": {
    "state": "ready",
    "active_invocations": 0,
    "details": {}
  }
}
```

`state` is `ready`, `busy`, `degraded`, or `unavailable`.
`active_invocations` is an integer in `[0, 2^53-1]`, and `details` is an object.
Endpoint identity comes from the envelope. The message always omits `request_id` and is
not an acknowledgement; acknowledgements use `endpoint.registry.response`.

### 8.5 Registry authority and current state

Each statically configured, trusted management route authorizes one configured
`endpoint_id`. The Gateway MUST validate the envelope endpoint and, for registration,
the descriptor endpoint against that route. Message contents alone grant no
registration authority.

The Registry holds at most one current availability record per configured endpoint. The
record contains the current `endpoint_instance_id`, exact descriptor, and lease deadline.
The trusted route can replace the record; the opaque instance ID does not establish
newness or authority.

Management `request_id` is correlation only and is never a Registry deduplication key.
Operations have these effects:

- Register with no current instance: accept, establish current state, and increment
  revision once.
- Same route, same current instance, exactly equal descriptor: accept and renew without
  incrementing revision.
- Same current instance, changed descriptor: reject without replacing the descriptor,
  renewing the lease, or incrementing revision.
- Same trusted route, different instance: atomically replace current state and increment
  revision once; no transient absent state is exposed.
- Unregister matching the current instance: remove current state and increment revision
  once.
- Authorized unregister with no current instance: accept effect-idempotently without a
  state or revision change.
- Unregister from a stale instance while another instance is current: reject without
  mutating current state.
- Lease expiry: remove current state and increment revision once.

A route/endpoint mismatch is rejected without state change. An `endpoint.status` message
is not a Registry mutation.

The Gateway uses trusted monotonic receive time to start or renew a lease only after
accepting registration. No receive observation, deadline, or expiry timestamp appears on
the Wire.

### 8.6 Registry revision and restart

`registry_revision` is process-local availability-state revision. It increments once for
absent-to-current registration, atomic instance replacement, matching unregister
removal, or lease expiry. Equal renewal, absent unregister, and rejection do not
increment it. Every response reports the revision after its decision.

The revision is not a wall-clock value, persistent version, lease deadline, or
cross-process ordering token. Gateway restart begins with empty current state and a fresh
process-local revision. Periodic registration restores availability.

## 9. Tool execution messages

### 9.1 Invoke request

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

`arguments` is an object. `context` contains:

| Field | Requirement |
| --- | --- |
| `tool_id` | Required non-empty string. |
| `implementation_id` | Required non-empty string. |
| `metadata` | Required object. |
| `caller_id` | Optional non-empty string; decoder also accepts JSON `null`. |
| `deadline_ms` | Optional safe non-negative epoch millisecond; decoder also accepts JSON `null`. |

Encoders omit unset optional context fields. `ToolExecutionKey`, `endpoint_id`, and
`operation` are reconstructed from the envelope and MUST NOT be duplicated in context.
The Wire treats `tool_id`, `implementation_id`, and `caller_id` as bounded attribution
values. It does not establish their catalog authority or authenticate `caller_id`; a
receiver MUST NOT treat mere presence of that field as proof of caller identity.

A pre-routing sender or Gateway MAY leave `endpoint_instance_id` unresolved before
selection. A provider-routed request MUST contain the selected concrete instance.

### 9.2 Invoke response

`tool.invoke.response` is one of three exact discriminated variants.

Completed:

```json
{
  "outcome": "completed",
  "result": {
    "status": "succeeded",
    "outputs": {}
  }
}
```

Accepted:

```json
{
  "outcome": "accepted",
  "accepted": {
    "details": {}
  }
}
```

Rejected:

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

The discriminator and its matching `result`, `accepted`, or `error` are required; fields
from other variants are forbidden.

- `completed` contains an authoritative terminal `ToolResult`.
- `accepted` means an asynchronous Action/Session was admitted. It does not mean the
  execution completed.
- `rejected` means the endpoint declined the invoke before acceptance and before
  execution side effects.

A Query execution failure is a completed `ToolResult(status="failed")`, not a
pre-acceptance rejection. An endpoint MUST NOT report `rejected` after execution side
effects have begun.

### 9.3 Status request and response

`tool.status.request` identifies the attempt in the envelope and has an empty payload:

```json
{}
```

`tool.status.response` has exactly:

```json
{
  "status": {
    "phase": "running",
    "details": {}
  }
}
```

For `failed` or `unknown`, `status` also contains required `error`:

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

`phase` is `accepted`, `running`, `stopping`, `completed`, `failed`, `cancelled`,
`stopped`, or `unknown`. `details` is always required. `failed` and `unknown` require
`error`; every other phase forbids it.

`completed` means provider execution is complete. The caller-facing Runtime still owns
CompletionSpec evaluation. `unknown` means the provider outcome cannot be recovered.

### 9.4 Result request and response

`tool.result.request` identifies the attempt in the envelope and has an empty payload:

```json
{}
```

`tool.result.response` has one of these exact shapes:

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

- `available` requires a terminal `ToolResult`.
- `pending` and `not_found` forbid `result`.
- `pending` means a known execution has no terminal result yet.
- `not_found` means no retained execution/result exists for the key.

Neither lookup state is equivalent to terminal result status `unknown`.

### 9.5 Control request and response

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

`command` is `cancel` or `stop`. Optional `reason` is omitted when unset; a decoder also
accepts JSON `null`. A non-null reason is a non-empty string.

Descriptor capabilities determine whether the selected operation supports the command:
Action uses `cancel`; Session uses `stop`; Query supports neither.

`tool.control.response` has this outer shape:

```json
{
  "response": {
    "command": "cancel",
    "status": "accepted",
    "details": {}
  }
}
```

`command` echoes the request. `status` is `accepted`, `rejected`, `terminal`, or
`unsupported`; `details` is a required object. A rejected response requires `error`:

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

Only `rejected` permits `error`. `accepted` means only that the control command was
admitted; the execution may still be active. `terminal` means it was already terminal
when the command arrived, not that this command caused termination. Final state is
observed through status or result.

### 9.6 Event

`tool.event` carries `sequence` in the envelope and has exactly:

```json
{
  "type": "progress",
  "data": {}
}
```

`type` is one of:

- `progress`
- `heartbeat`
- `executor_completed`
- `executor_failed`
- `cancelled`
- `stopped`

`data` is a required object. The event names and outer schema are frozen; type-specific
`data` schemas are not defined by v1alpha1.

An event omits `request_id`; it is associated with an attempt by `ToolExecutionKey`, the
provider route, operation, and endpoint sequence.

### 9.7 Tool error

`tool.error` represents an exchange, protocol, or transport failure that cannot be
expressed as the normal invoke/status/result/control response:

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

It carries the execution and exchange identities of the request it answers. Once a
request route is trusted, a receiver SHOULD return a bounded correlated `tool.error` for
an invalid message-specific payload or a failure to produce a valid response.

Failures before route trust—such as invalid carrier framing, generic envelope failure,
or a request for another endpoint—MAY be raised to the transport without a correlated
response. A receiver MUST NOT answer an untrusted request as though it belonged to a
provider route.

## 10. Lifecycle and event ordering

### 10.1 Phase transitions

Wire v1alpha1 defines this transition relation:

| Semantics/current state | Allowed next state |
| --- | --- |
| Query initial | terminal only |
| Action/Session initial | `accepted` or terminal |
| `accepted` | `running`, `stopping`, or terminal |
| `running` | `stopping` or terminal |
| `stopping` | terminal |
| Any state | repeated observation of the same state |
| Terminal | no different state |

Terminal phases are `completed`, `failed`, `cancelled`, `stopped`, and `unknown`.
Once a terminal phase and result are established, both are immutable.

The exact phase-to-result mapping is:

| Terminal phase | Required `ToolResult.status` |
| --- | --- |
| `completed` | `succeeded` |
| `failed` | `failed` |
| `cancelled` | `cancelled` |
| `stopped` | `stopped` |
| `unknown` | `unknown` |

A nonterminal phase cannot be paired with a terminal result.

### 10.2 Acceptance before events

For asynchronous execution, the invoke response MUST be exposed before related events.
Events emitted during `start()` therefore require a configured finite buffer. Buffer
overflow MUST fail deterministically rather than grow without bound.

An implementation that physically publishes response and events on one transport MUST
not release buffered or concurrent events until response publication succeeds.

### 10.3 Terminal result barrier

The matching authoritative `ToolResult` MUST be retained before exposing a terminal
phase or terminal event. Event loss must not make terminal result recovery impossible.

Terminal events map to phases as follows:

| Event | Terminal phase |
| --- | --- |
| `executor_completed` | `completed` |
| `executor_failed` | `failed` |
| `cancelled` | `cancelled` |
| `stopped` | `stopped` |

A terminal event closes event progression for the attempt. A later `progress`,
`heartbeat`, or different terminal event is invalid.

If an Action/Session side effect may have started but acceptance cannot be established
and the outcome cannot be recovered, the execution MAY move directly to initial terminal
`unknown`. The implementation MUST NOT fabricate acceptance or blindly retry.

### 10.4 Endpoint event sequence

The sequence scope is:

```text
endpoint_instance_id + invocation_id + attempt_id
```

A provider event MUST carry the concrete `endpoint_instance_id` that owns this scope.
Within each scope, the producer assigns `0` to the first event and increments strictly by
`1`. Sequence MUST NOT wrap; no event may be assigned after `2^53-1`.

Sequence communicates producer order only. It does not imply retained event history,
duplicate suppression, gap recovery, or replay. A caller-facing Runtime MAY assign a
separate invocation-scoped sequence; that sequence is outside this protocol.

### 10.5 Executor completion versus Runtime completion

Endpoint status, event, and result describe provider execution. The caller-facing Runtime
owns CompletionSpec evaluation and the final caller-visible outcome. Gateway and provider
bindings MUST NOT reinterpret CompletionSpec.

## 11. Response correlation

### 11.1 Execution exchanges

Normal pairs are:

| Request | Normal response |
| --- | --- |
| `tool.invoke.request` | `tool.invoke.response` |
| `tool.status.request` | `tool.status.response` |
| `tool.result.request` | `tool.result.response` |
| `tool.control.request` | `tool.control.response` |

A correlated `tool.error` MAY answer any request in the table.

A response MUST exactly copy these fields from its request:

- `request_id`
- `invocation_id`
- `attempt_id`
- `endpoint_id`
- `endpoint_instance_id`
- `operation`

An unresolved `endpoint_instance_id` is a real correlation value: an omitted request
field must remain omitted in a pre-provider response. A normal control response MUST also
echo the request command.

`request_id` identifies only this exchange. Reusing it does not request cached replay or
suppress execution.

### 11.2 Management exchanges

`endpoint.registry.response` MUST copy `request_id`, `endpoint_id`, and
`endpoint_instance_id` from the originating `endpoint.register` or
`endpoint.unregister`. Its payload `operation` MUST match that request type.

Effect-idempotent registration renewal and absent unregister behavior are Registry state
rules; they do not imply management request/response replay.

### 11.3 Events

`tool.event` has no request/response pair and MUST omit `request_id`. Consumers correlate
it by concrete provider route, `ToolExecutionKey`, operation, and sequence.

## 12. Arrow/Dora carrier

The canonical physical schema is
[`interfaces/forge_msgs/tool.v1.yaml`](../forge_msgs/tool.v1.yaml). If a prose summary
and that schema disagree about Arrow field mechanics, the canonical schema wins.

`forge_msgs.ToolMessage` is an exact-schema, single-row Arrow value with exactly these
columns in order:

| Column | Arrow type | Nullable |
| --- | --- | --- |
| `protocol` | `utf8` | no |
| `message_type` | `utf8` | no |
| `request_id` | `utf8` | yes |
| `invocation_id` | `utf8` | yes |
| `attempt_id` | `utf8` | yes |
| `endpoint_id` | `utf8` | no |
| `endpoint_instance_id` | `utf8` | yes |
| `operation` | `utf8` | yes |
| `sequence` | `int64` | yes |
| `payload_json` | `utf8` | no |

Carrier requirements:

- The value contains exactly one row and the exact column set/order above.
- Nullable columns use Arrow null for an omitted logical-envelope field.
- `endpoint_instance_id` may be null on any `tool.*` row before provider routing; every
  `endpoint.*` row requires it, and a provider-originated `tool.event` uses a concrete
  value.
- `tool.event` and `endpoint.status` use null `request_id`; register, unregister, and
  Registry response require a non-null value.
- Execution identity columns follow the logical header matrix.
- `sequence` is non-null only for `tool.event`.
- `payload_json` encodes exactly the logical `payload` object, not the complete envelope.
- `payload_json` is a strict JSON object with the limits in section 3.2.

The carrier has no top-level `tool_id` or `implementation_id`; those fields stay inside
invoke context in `payload_json`. It also has no observation timestamp, request
fingerprint, or canonical-identity column.

Carrier validation covers the schema and generic identity matrix. Message-specific
payload validation belongs to a ToolEndpoint logical protocol implementation. A valid
carrier therefore does not by itself prove a valid invoke/status/result/control payload
or a valid lifecycle transition.

Transport framing and decompression MUST be bounded before producing an in-memory Arrow
value. A binding MAY reject raw IPC bytes and require the upstream transport to perform
bounded decoding.

## 13. Conformance

### 13.1 Sender requirements

A conforming sender:

1. emits only the 14 registered message types;
2. applies the logical header matrix and omits forbidden/absent fields;
3. validates strict JSON and the message-specific closed payload schema;
4. derives execution identities consistently from one attempt;
5. copies request identities into responses exactly;
6. obeys lifecycle, terminal-result, and event sequence rules; and
7. enforces finite message and transport resource limits.

### 13.2 Receiver requirements

A conforming receiver:

1. rejects unsupported protocol identifiers and unknown message types;
2. rejects unknown, missing, duplicate, explicit-null top-level fields where forbidden;
3. validates generic identity/nullability before message-specific payloads;
4. applies trusted route authorization before answering on behalf of a provider;
5. validates message-specific payloads and response correlation;
6. treats `retryable` as metadata rather than policy; and
7. does not infer replay, deduplication, event recovery, or exactly-once behavior from
   identity or sequence fields.

### 13.3 Role-specific validation

- A pre-routing execution request MAY omit `endpoint_instance_id` before resolution.
- A Gateway that resolves a provider MUST pin the concrete instance before forwarding.
- A provider MUST reject an endpoint ID, instance ID, or operation that does not match
  its bound descriptor/route.
- A provider event producer MUST include its concrete `endpoint_instance_id`.
- A Registry MUST authorize management operations through a trusted configured route;
  envelope identity alone is insufficient.
- A stateful Action/Session implementation MUST enforce the lifecycle and terminal
  consistency rules while it retains execution state.

### 13.4 Contract versus implementation

The presence of a valid message schema does not claim that every implementation handles
every semantics end to end. Current support belongs to each implementation's package
documentation and tests; cross-component rollout is not part of this protocol.

The provider protocol is also not a caller API. Runtime invocation policy, caller
authentication, Agent framework state, and public idempotency contracts remain outside
this endpoint contract. `ToolContext.caller_id` is only propagated attribution metadata.
