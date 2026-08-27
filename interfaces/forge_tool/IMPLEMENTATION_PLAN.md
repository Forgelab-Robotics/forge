# Forge Tool 实现计划

状态：`forge-tool` Endpoint models、logical Wire、complete factories、严格 Query-only legacy API、Action `dispatch()` lifecycle handler 和 optional `forge_tool.dora` Arrow carrier binding，以及 `forge_msgs.ToolMessage` 的 10 列 Arrow/Dora carrier schema 已实现。Action path 已实现 bounded retention、per-operation admission、完整 transition/terminal barrier、cancel-to-unknown、Accepted physical-publish barrier 和 strict event sequence；Session 尚未实现。独立 Endpoint Host 概念已经取消，`packages/tool/src/forge_tool/host` 及其 public P1 identity/state/sequence primitives 已删除。`DoraToolEndpointBinding` 不拥有 Dora `Node`、event loop 或 metadata；第一个 YOLO concrete Dora provider-node embedding 和 first real Query vertical 已完成。当前 Query-only Gateway 已采用 static configured/trusted route、单 current instance 和周期 `endpoint.register` lease，并已有 simple experimental HTTP Query discovery/invoke bridge 与 Dora logical caller vertical bridge；Gateway 当前只关联 invoke terminal response/`tool.error`，不接收或路由 `endpoint.status`/`tool.event`。完整 caller-facing Tool Runtime API、stable Dora caller contract、Gateway Action routing/events、Session、SSE 和 MCP 仍属于后续阶段。

`forge.tool.endpoint/v1alpha1` 尚无 tagged/public Tool release；本文冻结的是该 identifier 的第一次 atomic release。此前 untagged prototype 不兼容且不声明 backward compatibility。`forge-tool`、Python/Rust/C++ `ToolMessage` binding、Gateway 和 provider 必须作为同一个 coordinated version set 部署，不支持 prototype/current mixed deployment。

本文描述 Forge Tool 通用调用能力，并与现有 `PolicyCommand` 并存。初期目标是建立清晰分层、可扩展的 Runtime API 与 endpoint SPI/Wire，同时支持或冻结：

- Forge/Dora 内部调用所需的 Arrow carrier contract；
- 当前 simple experimental HTTP Query discovery/invoke bridge，以及未来完整稳定 Web binding；
- Query、Action、Session 三种 operation semantics；
- Endpoint registration 和 endpoint execution lifecycle contract；
- 现有 `PolicyCommand` 原样保留，当前不迁移、不弃用。

P0 不引入 MCP、A2A、Temporal 等外部协议或运行时依赖。它们只作为设计参考，后续可以通过 adapter 接入。

## 1. 设计原则

### 1.1 只维护一套 caller-facing Runtime 语义

目标架构只定义一套完整 caller-facing Runtime API：

```text
Caller-facing Forge Tool Runtime API
├── discover
├── invoke
├── get status
├── get result
├── control
└── events
```

Query、Action、Session 不设计三套不同的调用协议。operation 的 `semantics` 来自 ToolSpec 和 EndpointDescriptor：

- Query：`invoke` 后通常直接得到 terminal result；
- Action：`invoke` 后快速 accepted，之后通过 status/result/event 观察；
- Session：`invoke` 后快速 accepted，通过 stop/status/result/event 控制和观察。

调用者不通过不同 route 或 message type 再声明一次 semantics。

### 1.2 Caller-facing Runtime API 与 endpoint SPI/Wire 分层

目标架构有两个不同边界，不能把它们统称为同一个调用 API：

```text
Web caller  ── target stable HTTP JSON/SSE binding ──┐
                                       ├── caller-facing Tool Runtime API
Dora caller ── target stable caller binding ──┘
                                                   │
                                                   │ resolve + create invocation/attempt
                                                   ▼
                                      ToolEndpoint Wire v1alpha1
                                                   │
                                                   ▼
具体 Dora 业务 node ── embedded binding/handler ── Query/Action/Session SPI ── 业务实现
```

目标 caller-facing Runtime API 面向 Web/Dora caller，提供 discovery、invoke、status、result、control 和 events；它隐藏 `attempt_id`、endpoint identity 等内部 routing 字段。当前 Gateway 已有 simple experimental HTTP Query discovery/invoke bridge 和 Dora logical caller vertical bridge，但两者只验证 Query vertical，不是完整或稳定的 caller-facing Runtime contract。未来 stable Dora caller binding 与完整 Web binding 必须进入同一个 Runtime API。

Endpoint SPI/Wire 面向 provider：Runtime/Gateway 使用 ToolEndpoint Wire 与具体 endpoint node 内嵌的 binding/handler 交换消息，handler 再调用该 node 实现的 Query/Action/Session SPI。Endpoint SPI 不是 caller API，当前 10 列 `forge_msgs.ToolMessage` 也不是 caller-facing Runtime carrier。

Transport binding 不增加第二套领域语义，但两个边界可以使用不同 framing 和 identity/correlation matrix；即使未来复用相同物理列布局，也必须分别冻结 contract。

### 1.3 一个内部 Tool message family

目标架构中的 Runtime/Gateway 与具体 endpoint node 内嵌的 ToolEndpoint binding/handler 将使用一套通用 Tool message：

```text
Execution
├── tool.invoke.request
├── tool.invoke.response
├── tool.status.request
├── tool.status.response
├── tool.result.request
├── tool.result.response
├── tool.control.request
├── tool.control.response
├── tool.event
└── tool.error

Endpoint management
├── endpoint.register
├── endpoint.unregister
├── endpoint.registry.response
└── endpoint.status
```

Endpoint management 只是同一协议中的内部 message family，不是另一套协议。

不再分别维护：

```text
tool.query.*
tool.action.*
tool.session.*
```

具体 endpoint node 内嵌的 logical request handler 将根据 operation descriptor 的 semantics，把统一 `tool.invoke.request` 分发到 Query、Action 或 Session endpoint SPI。

### 1.4 外部 Web 不暴露内部 routing 字段

Web 和普通 Dora caller 面向：

```text
tool_id
operation
arguments
timeout
idempotency key
```

调用者不得提交：

- `attempt_id`；
- `implementation_id`；
- `endpoint_id`；
- `endpoint_instance_id`；
- Runtime 生成的 `invocation_id`；
- 受信任的 `caller_id`。

当前 experimental Query bridges 只覆盖 discovery/invoke vertical 所需的最小 routing。未来完整 Gateway/Runtime 统一 resolver、attempt ownership 和其余 caller-facing API，不把内部 identity 暴露给 caller。

### 1.5 高频数据不进入 Tool control message

Image、JointState、JointCommand、trajectory feedback 等高频或大体积数据继续走现有 Dora 数据面。Tool request 只携带小型参数或数据引用。

## 2. 外部框架参考范围

P0 不实现外部协议兼容，只参考成熟框架已经验证过的设计：

| Forge 能力 | 参考模式 | P0 采用内容 |
|---|---|---|
| Tool discovery 和参数 schema | MCP、OpenAI-style tools | name、description、JSON Schema input/output |
| 长任务 status/result/events | Agent task/resource API | invocation resource、查询、事件、terminal result |
| Action accepted/feedback/result/cancel | ROS 2 Action、Dora Action | accepted 不等于 completed；cancel accepted 不等于 cancelled |
| retry、duplicate delivery、crash recovery | Temporal-style execution | invocation/attempt identity、ambiguous outcome；P0 不采用 replay/dedup/exactly-once 保证 |
| Endpoint registration | lease/service registry | logical ID、process instance、receive-time liveness |

P0 明确不做：

- MCP server/client；
- A2A adapter；
- OpenAI SDK adapter；
- Temporal dependency；
- 多套外部协议版本协商；
- push notification；
- 双向 WebSocket Session。

后续 caller adapter 必须调用同一个 caller-facing Forge Tool Runtime API，不得绕过 Runtime 直接构造 Endpoint Wire 或调用 endpoint SPI。

## 3. 现有 `PolicyCommand` 保留

### 3.1 当前保留，不迁移、不弃用

现有 `PolicyCommand` 和 `PolicyCommandStatus` 保持不变：

- `policy_command` / `policy_command_status` Dora topic 继续工作；
- `/policy/command`、Agent session、录制和回放链路继续工作；
- 新 ToolEndpoint Wire 使用独立 message；
- 不向 `PolicyCommand` 叠加 invocation/attempt 字段；
- 当前范围不迁移、不弃用也不删除 `PolicyCommand`；任何未来变化都需要单独设计和批准。

### 3.2 未来如需复用，可抽取 controller

如果未来另行启动 Policy/Tool 整合，不做 Wire-to-Wire 字段翻译，而是让两种 adapter 复用消息无关的 Policy Controller：

```text
PolicyCommand adapter -> Policy Controller
ToolEndpoint adapter  -> Policy Controller
```

即使未来整合，也不能直接映射：

```text
PolicyCommandStatus.done -> Tool execution completed
```

现有 `start -> done` 只表示 start command 已处理，不表示整个 policy session 已结束。

## 4. Package 和职责边界

### 4.1 `forge-tool`

负责：

- Query/Action/Session endpoint provider SPI；
- Tool request/result/error/status/event models；
- Endpoint Descriptor；
- 通用 Tool logical message；
- stateless message validation 和 lifecycle contract helpers；
- bounded JSON model validation；
- 完整 `make_*_envelope` factory 和 response correlation validation；
- strict JSON codec，主要用于测试、调试和未来非 Dora transport。

基础安装和 core modules 不依赖：

- Dora；
- Arrow；
- FastAPI；
- Gateway。

显式 optional `forge-tool[dora]` extra 依赖 `forge-msgs` 及其 Arrow carrier stack；`import forge_tool` 不加载这些 optional dependencies。

### 4.2 `forge-msgs`

负责一个通用的单行 Tool Arrow/Dora carrier：

```text
forge_msgs.ToolMessage
```

其 schema 固定为 10 列：`protocol/message_type/request_id/invocation_id/attempt_id/endpoint_id/endpoint_instance_id/operation/sequence/payload_json`。`endpoint_id` 非 null；所有 `tool.*` logical message 的 `endpoint_instance_id` 可为 null，所有 `endpoint.*` message（含 `endpoint.status`）必须非 null；没有顶层 `tool_id`、`implementation_id`、观测 timestamp 或 request fingerprint 列；Wire v1alpha1 不定义 Wire/Arrow fingerprint。`tool.event` 的 logical `request_id` 被省略，在 carrier 中为 null。

Python、Rust、C++ carrier 均已实现。Python↔C++ Arrow IPC interop 已覆盖；Rust 当前覆盖 schema/model/RecordBatch 行为，不在此声称 Python↔Rust IPC coverage。

`forge-msgs` 不负责 resolver、Runtime state、CompletionSpec 或 HTTP。

### 4.3 Tool Runtime

未来的 Tool Runtime 将是 invocation 的唯一权威，负责：

- ToolSpec discovery；
- 创建 `invocation_id`；
- resolver 和 implementation selection；
- 创建 `attempt_id`；
- resource 和 Control Lease；
- 按真实需求另行设计的 retry/fallback（P0 不自动 retry Query）；
- invocation status/result；
- CompletionSpec；
- caller-facing event sequence。

### 4.4 Gateway

当前 Query-only Gateway 的 P0 endpoint route/Registry 与 caller vertical 基线负责：

- 以 static configured/trusted route 授权 `endpoint_id`；
- 每个 configured endpoint 维护至多一个 current instance；
- 通过周期 `endpoint.register` 维护 lease 和 availability；
- 路由 `tool.invoke.request`，并关联 invoke terminal response 或 `tool.error`；
- 提供 simple experimental HTTP Query discovery/invoke bridge；
- 提供 Dora logical caller vertical bridge。

`endpoint.status` 虽保留为 protocol/model message，但当前 Gateway 不接收、路由或执行 current-instance validation；该路径留到真实 availability/health 需求。`tool.event` 同样保留在 schema/message family 中，但当前 Gateway 不接收、路由或执行 event correlation。完整 caller-facing Tool Runtime API、stable Dora caller contract、Gateway-side Action/Session routing、SSE、MCP 及 production HTTP surface 仍按后续阶段推进。Gateway 不决定 implementation，不解释 CompletionSpec。

未来部署中，Tool Runtime 可以与 Gateway 位于同一进程，但应保持独立 domain module 和唯一状态所有权。

### 4.5 具体 Dora endpoint node 与 embedded binding/handler

ToolEndpoint 不定义独立执行主体。与 `forge_policy` 的集成方向相同，具体 Dora 业务 node 实现 Query/Action/Session endpoint SPI，并嵌入 ToolEndpoint binding/handler。

Embedded binding/handler 负责：

- 将 Dora Arrow carrier 转换为 logical message；
- 校验 descriptor，并把 operation 显式绑定到该 node 的 endpoint SPI；
- legacy `handle_invoke()`/Dora `handle_input()` 保持严格 Query-only，调用 `QueryToolEndpoint.query()` 并构造 correlated terminal response 或 `tool.error`；
- Action invoke/status/result/control/event 已由 `dispatch()` 和 Dora acknowledged publisher 打通，包含 per-operation admission、完整 lifecycle transition、terminal result barrier、Accepted physical-publish barrier、strict event sequence publication、cancel-to-unknown 和 bounded private duplicate suppression；
- 由具体业务 node 发布周期 `endpoint.register` lease-renewal Arrow value；
- Session 与 availability/health 路径仍留待后续；`endpoint.status` 仍未进入当前 Gateway。

业务 endpoint 实现负责 executor 的权威状态，以及必要的 `ToolExecutionKey` 到私有 executor handle 映射；通用 binding 不维护第二份业务状态所有权，也不解释 Runtime CompletionSpec。

YOLO provider 已验证具体业务 node 直接嵌入 binding/handler 的路径。未来 additional providers 可复用该模式，也可以提供可选通用 runner 作为便利封装，但 runner 不能成为实现或部署 ToolEndpoint 的唯一方式。

## 5. Caller-facing Runtime API 与 endpoint SPI

本节的 discovery/invoke/get status/get result/control/events 描述目标完整 caller-facing Runtime API，供 Web caller 和 Dora caller 使用；当前 experimental HTTP 与 Dora logical caller bridges 只实现 Query discovery/invoke vertical，不冻结完整 caller contract。Query/Action/Session 则是具体 endpoint node 实现的 provider SPI；Endpoint Wire 在 Runtime/Gateway 与 node 内嵌 handler 之间传输请求，不直接暴露给 caller。

### 5.1 Discovery

```text
list_tools()
get_tool(tool_id)
```

ToolSpec operation 至少公开：

```text
name
description
semantics
input_schema
output_schema
cancellable
stoppable
status_supported
retry_safety
```

P0 需要选择并记录支持的 JSON Schema dialect/subset，但不实现 MCP/OpenAI adapter。

EndpointDescriptor 只描述当前 Endpoint 能执行哪些 operation，不替代 Runtime ToolSpec。operation capability matrix 已冻结：

| semantics | cancellable | stoppable | status_supported |
|---|---:|---:|---:|
| query | false | false | false |
| action | true/false | false | true |
| session | false | true/false | true |

### 5.2 Invoke

统一调用：

```text
invoke(tool_id, operation, arguments, options) -> ToolInvocation
```

`options` 最小包含：

```text
deadline/timeout
idempotency_key
wait_timeout
```

返回的 `ToolInvocation` 至少包含：

```text
invocation_id
tool_id
operation
semantics
status
optional result
optional error
```

所有调用都创建 invocation：

- Query 在 `wait_timeout` 内完成时可以直接返回 terminal invocation；
- Query 未在窗口内完成时返回 active invocation；
- Action/Session 通常快速返回 accepted/running invocation。

### 5.3 Status

```text
get_invocation(invocation_id) -> ToolInvocation
```

最小 caller-facing status：

```text
pending
running
cancel_requested
stop_requested
succeeded
failed
cancelled
stopped
unknown
```

terminal status：

```text
succeeded
failed
cancelled
stopped
unknown
```

terminal status 不可逆。

### 5.4 Result

Caller-facing Runtime API：

```text
get_result(invocation_id) -> ToolResult
```

Action/Session endpoint SPI：

```text
result(ToolExecutionKey) -> ToolResultResponse
```

`ToolResultResponse.status` 为：

```text
pending
available
not_found
```

`available` 必须携带 `ToolResult`；`pending` 和 `not_found` 禁止携带 result。`ToolResult.status=unknown` 是不可恢复的 terminal execution outcome，不是 lookup pending/not-found。

`ToolResult` 是权威 terminal snapshot，包含 status、outputs 和条件性 error。Event 是增量通知，不能作为唯一 result storage。即使 terminal event 丢失，也必须能够通过 result/status 恢复。

### 5.5 Control

```text
control(invocation_id, command, reason=None) -> ToolControlResponse
```

P0 command：

```text
cancel
stop
```

语义：

- Action 通常支持 `cancel`；
- Session 通常支持 `stop`；
- operation descriptor 决定命令是否支持；
- `accepted` 只表示控制命令已接收，不表示 execution 已终止。

Control response：

```text
accepted
rejected
terminal
unsupported
```

最终结果通过 status/result 观察。

### 5.6 Events

```text
subscribe_events(invocation_id, after_sequence=None)
```

事件用于进度和状态变化通知。Runtime 为每个 invocation 分配 caller-facing sequence。P0 不承诺无限事件保留，只定义有限 buffer 和 cursor 过期行为。

## 6. Identity 和 execution key

### 6.1 ID 层级

```text
idempotency_key
    未来 caller/Runtime 概念；不是 P0 Endpoint Wire 字段或保证

invocation_id
    Runtime 创建的一次逻辑 Tool 调用

attempt_id
    Runtime 创建的一次 implementation 尝试

request_id
    一次 message exchange

execution_id
    Endpoint executor 可选的本地 handle
```

这些 ID 不合并。

### 6.2 固定 execution key

P0 直接采用：

```text
ToolExecutionKey
├── invocation_id
└── attempt_id
```

所有 Endpoint execution request、status、result、control 和 event 都关联该 key。

Endpoint SPI 的 control/status/result 应能够通过 `ToolExecutionKey` 定位 execution。`execution_id` 仅作为具体 endpoint node/embedded handler 的私有映射，不替代 Runtime identity。

### 6.3 Correlation 与 execution identity

P0 只冻结以下 identity/correlation 含义：

```text
exchange correlation
    request_id

execution identity
    invocation_id + attempt_id
```

`request_id` 标识一次 request/response exchange，response 从 paired request 原样复制；它不是 response cache key，也不触发 replay、dedup 或 retry。`invocation_id + attempt_id` 是一次 execution attempt 的 identity，供 invoke/status/result/control/event 关联同一 attempt；它同样不提供 duplicate suppression。`endpoint_instance_id` 只标识并校验 concrete provider route。

P0 不提供 stateful response replay、exchange/execution dedup、retention window 或 exactly-once guarantee，也不冻结 decoded structural JSON dedup identity、fingerprint 或 conflict 行为。重复投递可能再次执行。`ToolError.retryable` 只是错误元数据，不触发自动 retry；P0 不自动 retry Query。

Management `request_id` 也仅用于 correlation。Registry 的 renew、replace、unregister 和 expiry 是 7.5 定义的 configured-route/current-state effect，不是 request replay guarantee。Action 与任何 retry policy 留待真实需求出现后另行设计；若重复投递确实需要处理，再设计 private、bounded、stateful dedup 和明确 retention。

### 6.4 Ambiguous outcome 与未来 retry

- P0 Query 只执行收到的当前 exchange，不自动 retry；调用方不得从 `retryable` 或 execution identity 推导自动重试。
- 未来 Action/Session side effect 可能已开始、但 Accepted 建立前发生异常或断连时，不伪造 Accepted，也不盲目自动 retry；无法恢复 execution outcome 时建立 initial terminal `unknown`。
- Action 和 retry/fallback policy 不在 P0 预先冻结，后续按真实 operation 与 transport 行为单独设计；Motion 等物理动作还需要稳定 goal/execution identity。
- P0 不提供进程内或跨进程 exactly-once guarantee。

## 7. ToolEndpoint Wire message

### 7.1 Invoke

```text
tool.invoke.request
tool.invoke.response
```

具体 endpoint node 内嵌的 logical request handler 根据 descriptor semantics：

- 调用 `QueryToolEndpoint.query()`；或
- 调用 `ActionToolEndpoint.start()`；或
- 调用 `SessionToolEndpoint.start()`。

Response 表达：

```text
completed
accepted
rejected
```

completed 包含 result；accepted 表示 executor 已接收；rejected 包含 structured error。

### 7.2 Status 和 Result

```text
tool.status.request
tool.status.response
tool.result.request
tool.result.response
```

Status 是当前 snapshot。`ExecutionPhase` 为 `accepted|running|stopping|completed|failed|cancelled|stopped|unknown`；`failed` 和 `unknown` 必须携带 structured error。

Result lookup response 的 exact payload 为：

```text
{status: pending}
{status: available, result: ToolResult}
{status: not_found}
```

只有 `available` 携带 result。`unknown` 只作为 terminal `ToolResult.status`，不作为 lookup unavailable/pending 的别名。

### 7.3 Control

```text
tool.control.request
tool.control.response
```

Control request payload：

```text
command: cancel | stop
reason: optional string
```

Control response：

```text
accepted
rejected
terminal
unsupported
```

### 7.4 Events 和 Error

```text
tool.event
tool.error
```

Event 携带 execution key 和 endpoint sequence；其 logical `request_id` 必须省略，Arrow carrier 中对应值为 null。`tool.error` 用于无法作为正常 invoke/status/result/control response 表达的协议或 transport-level failure。`tool.event` 是现有 schema/message family，但当前 Query-only Gateway 不接收、路由或执行 event correlation；当前只处理 invoke terminal response/`tool.error`。

### 7.5 Endpoint management

```text
endpoint.register
endpoint.unregister
endpoint.registry.response
endpoint.status
```

P0 保留 opaque `endpoint_instance_id`。所有 `tool.*` logical envelope 都可在 provider selection 前省略它；所有 `endpoint.*` message（含 `endpoint.status`）必须携带。Gateway 成功选定 provider 后必须填入 concrete instance，provider handler 仍执行 strict route validation；若 selection 前失败，correlated invoke response/error 保持 `None`。`endpoint.register`、`endpoint.unregister` 及其 correlated `endpoint.registry.response` 必须携带 `request_id`；unsolicited `endpoint.status` 必须省略。Registry response 的 operation 为 `register|unregister`，status 为 `accepted|rejected`，携带 non-negative interoperable `registry_revision`。accepted register 必须携带 positive `lease_ttl_ms` duration；accepted unregister 不携带 lease；rejected 不携带 lease 且必须携带 `ToolError`。conditional field 的 presence 有语义，显式 `lease_ttl_ms: null` 与 `error: null` 均非法。没有 observation timestamp。`endpoint.status` 的 protocol/model message 仍保留，但当前 Query-only Gateway 不接收、路由或执行 current-instance validation；留到未来 availability/health 需求。

Management `request_id` 只用于 correlation。static configured/trusted route 授权其配置的 `endpoint_id`；Gateway 必须校验 route、envelope `endpoint_id` 和 register descriptor `endpoint_id` 一致。Registry 对每个 configured endpoint 最多维护一个 current instance，instance ID 只是 identity，不提供排序或授权。

`endpoint.register` 是 announce/upsert/lease renewal，并由 endpoint 周期发送：无 current 时 accepted register 建立 current 并增加 revision；同 route、同 current instance、descriptor exact equality 时续租且不增加 revision；同 instance descriptor change 被拒绝且不续租；同 route 新 instance accepted 时 atomic replace current，并只增加一次 revision，不暴露中间 absent 状态。

`endpoint.unregister` 从授权 route 且匹配 current instance 时移除 current 并增加 revision；无 current 时 effect-idempotent accepted，不改变 state/revision；已有不同 current instance 时，旧 instance 是 stale，必须 rejected 且不能移除 current。route/endpoint mismatch rejected。当前 Registry path 不处理 `endpoint.status`。lease expiry 移除 current 并增加 revision。

Gateway 使用 trusted monotonic receive observation 作为 accepted register 的 lease start/renewal 基准，不携带 wire timestamp。`registry_revision` 仅是 process-local availability-state revision：absent-to-current、atomic replace、matching unregister removal 和 expiry 各增加一次；descriptor-equal renewal、absent unregister 和 rejection 不增加。每个 response 返回 decision 后的 current process-local revision。Gateway restart 后 Registry/current state 和 revision 都重新开始，endpoint 依靠周期 `endpoint.register` 恢复 availability。

### 7.6 Complete envelope factory 和 correlation（已实现）

完整 `make_*_envelope` factory 是推荐的 public construction path，覆盖 invoke/status/result/control/event/error/register/unregister/registry response/endpoint status。`make_invoke_request_envelope` 接受 `endpoint_instance_id=None` 供 Gateway resolution；invoke response/error factory 原样复制 unresolved identity，保持 `None` correlation；non-P0 status/result/control request factory API 可继续要求 concrete instance。Execution request 和 event factory 从 `ToolContext` 派生 route identity；invoke/status/result/control response factory 直接从原始 request envelope 复制 correlation identity，不要求 endpoint node 为构造响应保留完整 invoke context。`make_endpoint_registry_response_envelope` 同样从原始 management request 复制 `request_id` 与 endpoint identities，并校验 operation 配对。

`validate_response_correlation(request, response)` 校验 execution response type 以及 `request_id`、`invocation_id`、`attempt_id`、`endpoint_id`、`endpoint_instance_id`、`operation`；control response 还必须匹配 request command。`validate_management_response_correlation(request, response)` 校验 Registry response type、`request_id`、两项 endpoint identity 和 operation。Raw payload adapter 继续保持 public，供 transport integration 和高级用法使用；完整 message 默认使用 factory。Model mapping 在构造时已经执行 bounded JSON validation 和 defensive copy。

## 8. 时间和顺序

### 8.1 不携带观测 timestamp

逻辑 message 和 Arrow carrier 不包含观测时间：

- Dora 使用 event context；
- Web 使用 Gateway request/event context；
- Gateway 对 accepted `endpoint.register` 使用 trusted monotonic receive observation 作为 lease start/renewal 基准；
- Registry liveness 由周期 register 和该 process-local observation 维护，不写入 Wire。

`deadline_ms` 是执行语义字段，继续保留，并限制在可互操作 JSON integer 范围。

### 8.2 两个 sequence scope

Endpoint sequence：

```text
endpoint_instance_id + invocation_id + attempt_id
```

具体 endpoint event producer 在每个 scope 从 `0` 开始分配并严格 `+1`，且 sequence 不 wrap；`2^53-1` 后不得再分配事件。sequence 只表达 producer order。P0 不提供 retained history、duplicate suppression、gap recovery 或 event replay guarantee，也不要求 public sequence primitive 或生产 retention/router。

Invocation sequence：

```text
invocation_id
```

由未来 Runtime 分配，用于 Web SSE、Dora caller events 和多 attempt 合并。

### 8.3 Terminal lifecycle invariant

Terminal phase 不可逆，且 status/result 固定映射：

```text
completed -> succeeded
failed    -> failed
cancelled -> cancelled
stopped   -> stopped
unknown   -> unknown
```

Wire v1alpha1 normative transition table 为：

| semantics/current | allowed next |
|---|---|
| Query initial | terminal only |
| Action/Session initial | `accepted` 或 terminal |
| `accepted` | `running`、`stopping` 或 terminal |
| `running` | `stopping` 或 terminal |
| `stopping` | terminal |
| 任意 state | 可重复观察同一 state |
| terminal | 不得变为不同 state |

terminal 指 `completed|failed|cancelled|stopped|unknown`；terminal phase/result 一旦建立即 immutable。`validate_execution_result(status, result)` 已实现单个 pair 的 terminal mapping 检查；Python embedded Action handler 已用 bounded private ledger 实现完整 transition validation 和 immutable terminal retention，但不导出 public/general lifecycle store。

异步 execution 的 Accepted 必须先于相关 event 暴露；早到 event 需要 configured bounded buffer，overflow 必须 deterministic failure，不能无限增长。terminal result barrier 要求 matching authoritative `ToolResult` 先 retained，再暴露 terminal phase/event，以便 event 丢失后通过 status/result 恢复。Action/Session 在 Accepted 前发生不可恢复的不确定异常时，可直接 initial terminal `unknown`，不得伪造 Accepted 或盲目 retry。Python Action path 已实现这些规则：Dora binding 通过同一个 acknowledged async publisher 先 await Accepted 的物理发布，再开放 event gate，并按 endpoint sequence 串行发布；`start()` 取消/失败收敛为 retained `unknown` 并唤醒 duplicate。Session integration 仍未实现。

## 9. P0：冻结基线与 cleanup

### P0-A：冻结最小 Endpoint/Wire 值语义（已完成）

当前已冻结并实现：

1. `ToolExecutionKey`；
2. Query/Action/Session endpoint provider SPI；
3. control/result/error 的单消息语义；
4. required/forbidden identity matrix；
5. terminal status/result mapping 和 `unknown` 语义。

Caller-facing `list_tools/get_tool/invoke/get_invocation/get_result/control/subscribe_events`、ToolSpec repository/schema、完整 invocation state、retry safety 和 stateful endpoint handling 属于后续 Tool Runtime 或 embedded handler 阶段。精确 Arrow carrier schema 已在 P0-D 冻结并实现。

### P0-B：删除 legacy `forge_tool.host` surface（已完成）

已完成：

1. 删除 `packages/tool/src/forge_tool/host`；
2. 删除其 public exports，以及把 identity/state/sequence helper 当作 public P1 foundation 的测试和文档声明；
3. 将 identity/correlation、lifecycle、terminal barrier 和 endpoint sequence 的值语义保留在 Wire v1alpha1，同时明确 P0 不提供 stateful replay/dedup/retention guarantee；
4. 将 invoke/status/result/control response factory 改为直接从原始 request envelope 派生 correlation identity；
5. 保持 Query/Action/Session endpoint SPI、logical models/codecs 和 10 列 carrier contract 不变；
6. 不创建替代执行 package，也不在 cleanup 中决定 Dora integration 的依赖位置。

该 cleanup 只收缩错误的 implementation/public surface，并使 response construction 适合 embedded handler；不改变 message family、identity fields、lifecycle/sequence 语义或 `PolicyCommand`。

### P0-C：冻结 logical protocol（已完成）

已更新：

```text
interfaces/forge_tool/PROTOCOL.md
packages/tool/src/forge_tool/endpoint/
packages/tool/src/forge_tool/wire/
packages/tool/tests/
```

主要修改：

- 协议收敛为通用 invoke/status/result/control/event；
- 删除 query/action/session-specific Wire message type；
- Endpoint control/status/result 使用 `ToolExecutionKey`；
- 删除观测时间字段；
- 增加 authoritative result 和 `ToolResultResponse` lookup 状态；
- 增加 control response 状态；
- 增加 `unknown` phase/result 和 terminal mapping；
- 增加 sequence；
- 冻结 descriptor capability matrix、payload 和 identity matrix；
- 实现 complete envelope factories、response correlation 和 bounded JSON models；
- response factory 直接从 paired request 派生 correlation identity。

验收：

- strict JSON round-trip；
- unknown field、explicit null、duplicate key、invalid number 被拒绝；
- terminal status/result pair 和 identity 正反例；
- `forge-tool` 仍无运行时依赖。

### P0-D：`forge_msgs.ToolMessage` Arrow/Dora carrier schema（已完成）

已冻结并实现 exact single-row、10-column schema，列顺序和 nullability 如下：

```text
ToolMessage
├── protocol: utf8 non-null
├── message_type: utf8 non-null
├── request_id: nullable utf8
├── invocation_id: nullable utf8
├── attempt_id: nullable utf8
├── endpoint_id: utf8 non-null
├── endpoint_instance_id: nullable utf8
├── operation: nullable utf8
├── sequence: nullable int64
└── payload_json: utf8 non-null
```

carrier 没有 `tool_id` 或 `implementation_id` 列；它们作为 invoke payload context 的字段保留在 `payload_json` 中。carrier 也没有观测 timestamp。`endpoint_instance_id` 可在任意 pre-provider `tool.*` logical message 中为 null，但所有 `endpoint.*` message 必须 non-null。`tool.event` 与 unsolicited `endpoint.status` 在 logical envelope 中省略 `request_id`，在 Arrow carrier 中该列必须为 null；register/unregister/registry response 的 carrier `request_id` 必须 non-null。

现有 carrier 校验 exact schema、单行约束、protocol/message type、message-class identity/sequence 规则和 object-valued `payload_json`。未来 Gateway 与具体 endpoint node 内嵌的 binding/handler 仍需提供 trusted binding 和 role-specific validation。继续只维护一个通用 Tool carrier。

### P0-E：Python carrier 和 Python/C++ IPC conformance（已完成）

Python `forge_msgs.ToolMessage` 已实现 exact-schema RecordBatch/Table/IPC round-trip，以及 identity、event sequence/request ID、strict `payload_json` 和单行 schema validation。

Python↔C++ Arrow IPC fixture 已覆盖双方写入和读取 `ToolMessage`。这里不声称 Python↔Rust IPC coverage。

### P0-F：Rust/C++ carrier（已完成）

Rust 和 C++ 已实现相同 10 列 schema、nullability、message-class validation 和 RecordBatch conversion。Rust coverage 验证 schema/model/RecordBatch 行为；C++ 还参与 Python↔C++ Arrow IPC interop。该完成状态不包含任何语言的 stateful endpoint binding/handler。

现有 `PolicyCommand` schema 和测试保持不变；当前不迁移、不弃用 `PolicyCommand`。

## 10. P1：endpoint node embedded vertical implementation

P1 按以下顺序实现，每一步建立在前一步的真实调用路径上，不先建设独立 execution service 或 public state-machine utility surface。

### P1-A：operation implementation mapping（已完成）

`ToolEndpointHandler` 接收 descriptor、endpoint process instance ID 和普通 `operation name -> endpoint implementation` mapping。构造时要求 descriptor operation 与 mapping key 完全一致，按 semantics 校验 Query/Action/Session 所需 callable method，并 defensive-copy mapping。没有新增独立 public operation-map 类型；mapping 不负责 caller-facing discovery/resolution。

### P1-B：logical request handler（Query first，已完成）

Transport-independent `ToolEndpointHandler.handle_invoke()` 已打通 Query：执行 endpoint/instance route、operation 和 typed payload 校验，调用 `QueryToolEndpoint.query()`，检查 authoritative `ToolResult`，并从原始 request 建立 correlated completed、pre-acceptance structured rejected 或 protocol `tool.error` response。Action/Session implementation 可以完成启动绑定校验，但其调用路径明确留到 P1-E。handler 不拥有 Dora node、execution state、dedup cache 或 endpoint-local executor handle。

### P1-C1：optional Dora Arrow carrier binding（已完成）

在现有 `forge-tool` package 中增加 optional `dora` extra 和显式 `forge_tool.dora` module，不新增 package。基础 `import forge_tool` 保持零运行时依赖且不加载 `forge_msgs`/PyArrow；只有使用该 optional module 时才加载 `forge_msgs.ToolMessage` carrier。`DoraToolEndpointBinding.handle_input()` 转换单个 Arrow value、调用 Query-first logical handler 并返回 response `RecordBatch`，但不导入或创建 Dora `Node`，也不接管 event loop、input/output ID 或 Dora metadata。

### P1-C2：具体 Dora node embedding（已完成：YOLO）

YOLO 具体 Dora provider node 已嵌入 optional carrier binding，完成 Dora input/output wiring、role-specific validation、configured/trusted route 和周期 registration lease 的 vertical 验证。业务 node 自己拥有 event loop，负责 await binding 和发送返回的 Arrow value；binding 不在内部调用 `asyncio.run()`。即使 additional providers 采用不同 topic 拆分，message type 仍需自描述。

未来可以提供可选 runner 作为便利入口，但具体业务 node 必须始终能够直接嵌入 binding/handler，runner 不能成为唯一实现方式。

### P1-D：first real Query（已完成：YOLO）

YOLO 已完成第一个真实 Query vertical：Wire request 经 Dora carrier、embedded handler 到业务 SPI，并返回 terminal result。高频 image 数据继续走 Dora 数据面，Tool request 只携带小型参数或引用。完整 caller-facing Runtime API 仍按 P2 推进。

### P1-E：Action（已完成）/Session（待实现）

Action 的 start/status/result/control/event handling 已完成，并在 embedded handler/Dora binding 内满足 Accepted physical-publish-before-Event、strict endpoint sequence、完整 phase transition、terminal result barrier、immutable terminal outcome、cancel-to-`unknown`、per-operation `max_concurrency` admission 和 terminal permit single-release。legacy `handle_invoke()`/`handle_input()` 仍严格 Query-only，Action 必须进入 `dispatch()`。Session handling 仍待实现。

### P1-F：private bounded Action dedup（已完成）

Action handler 已增加 configurable count-bounded execution retention（默认 1024）：同 key 在 retained 期间不会再次 physical start，completed/pre-acceptance records 在容量压力下按最旧记录淘汰，active records 不淘汰；ledger 满且全为 active 时拒绝新 admission。该行为保持 module-private，不导出通用 public state/dedup/sequence primitive，不新增 Wire/Arrow fingerprint，不提供 eviction/restart 后保证，也不改变 10 列 carrier。

## 11. P2：完整 Tool Runtime 与稳定 caller bindings

### P2.1 Tool Runtime

实现：

- ToolSpec repository；
- invocation repository；
- resolver；
- attempt state machine；
- resources/Control Lease；
- CompletionSpec；
- 按真实需求另行设计的 retry/fallback（P0 不自动 retry Query）；
- result/event retention；
- restart 后 lost/unknown 处理。

### P2.2 完整 Web binding

当前 Gateway 已有 simple experimental HTTP Query discovery/invoke bridge。它只用于 Query vertical，不是完整或稳定的 caller-facing Runtime API，也不提供 invocation status/result/control/events 或 SSE。目标统一调用 route 为：

```text
GET  /v1alpha1/tools
GET  /v1alpha1/tools/{tool_id}
POST /v1alpha1/tools/{tool_id}/operations/{operation}:invoke
GET  /v1alpha1/invocations/{invocation_id}
GET  /v1alpha1/invocations/{invocation_id}/result
POST /v1alpha1/invocations/{invocation_id}:control
GET  /v1alpha1/invocations/{invocation_id}/events
```

行为：

- Query 可在受限 wait window 内返回 terminal result；
- 未完成的 Query、Action、Session 返回 invocation resource；
- Action/Session 不等待 executor 完成；
- events 使用 SSE；
- caller identity 来自认证 principal 或受信任部署配置；
- body 中的内部 identity 被拒绝。

### P2.3 稳定 Dora caller binding

当前已有 Dora logical caller vertical bridge，用于验证 Query 调用链路；它是 experimental integration，不是稳定 caller contract。未来内部 Dora caller 和 Web caller 进入同一个完整 caller-facing Tool Runtime API，不直接构造 ToolEndpoint Wire 或调用 endpoint SPI。Gateway 从静态 graph/input binding 获得 Dora caller identity。

当前 `forge_msgs.ToolMessage` 只承载 Gateway/Runtime endpoint route 与具体 endpoint node 内嵌 binding/handler 之间的 ToolEndpoint Wire，不是已冻结的 caller-facing Runtime carrier。P2 再冻结稳定 Dora caller transport、framing 和 identity/correlation matrix；即使复用相同物理列布局，也不能改变当前 Endpoint contract。

### P2.4 Retry 与 duplicate-delivery 范围

P0 不提供 Gateway epoch 内或跨 restart 的 replay、dedup、idempotency、exactly-once guarantee，也不自动 retry Query。Action/retry 若出现真实需求，再定义 bounded stateful dedup、retention、冲突处理和是否需要持久 ledger。

## 12. P3：`PolicyCommand` 保留与可选后续评估

当前继续保留 `PolicyCommand`，不迁移、不弃用。只有未来另行批准 legacy 和 Tool 双输入整合时，才需要先完成：

- Policy session owner；
- single-active 或明确并发规则；
- Control Lease；
- legacy/Tool 优先级；
- active ToolInvocation 状态同步。

若未来启动迁移，可评估模式：

```text
legacy_only
tool_only
dual_input_single_owner
```

届时可再抽取消息无关 Policy Controller，并决定是否逐步迁移 Agent session/action manifest。Gateway 本地管理能力不必强制改成 Tool invocation。

## 13. P4：更多具体 Tool Adapter

P1 已用 YOLO Query 完成第一条真实 endpoint-node vertical path；additional provider 扩展顺序为：

1. LeRobot Session；
2. Motion Action。

要求：

- YOLO 使用 image reference；
- LeRobot 复用 Policy Controller 和 Control Lease；
- Motion 将 `ToolExecutionKey` 稳定映射到底层 goal identity；
- 高频数据继续走 Dora 数据面。

## 14. 后续可选扩展

P0～P2 稳定后，再按真实需求评估：

- MCP adapter；
- A2A adapter；
- OpenAI tool adapter；
- 双向 WebSocket Session；
- persistent invocation ledger；
- 按需提供其他语言的 embedded endpoint binding/handler；
- push notification；
- 多协议版本协商。

Caller adapter 扩展必须复用 caller-facing Tool Runtime API，endpoint adapter 扩展必须复用现有 SPI/Wire；不得新增第二套 Runtime state machine。

## 15. 当前实施切片

当前严格按以下顺序推进：

1. P0 cleanup：删除独立 `forge_tool.host` 及其 public P1 primitive surface（已完成）；
2. 建立 operation implementation mapping（已完成）；
3. 实现 Query-first logical request handler（已完成）；
4. 实现 optional Dora Arrow carrier binding（已完成）；
5. 建立 simple experimental HTTP Query discovery/invoke bridge 和 Dora logical caller vertical bridge（已完成 experimental vertical）；
6. 将 binding 嵌入 YOLO concrete Dora provider node（已完成）；
7. 接入第一个真实 YOLO Query vertical（已完成）；
8. 扩展 additional providers 或按需提供通用 runner；
9. 实现 Action lifecycle 与 private bounded dedup（已完成）；
10. 再实现 Session lifecycle。

已冻结的 Wire v1alpha1、10 列 carrier、message family、identity/correlation fields 和 lifecycle/sequence 值语义在此顺序中保持不变；不由此推导 stateful replay/dedup guarantee。

当前切片明确不做：

- MCP/A2A/OpenAI adapter；
- 修改或删除 `PolicyCommand`；
- 将现有 experimental Gateway HTTP Query bridge 扩展成完整 production API；
- 完整生产 Registry/Resolver/Completion；
- stateful replay/dedup/idempotency/exactly-once guarantee；
- Policy legacy/Tool 双控制；
- P1 首个 YOLO Query 之外的完整 LeRobot 或 Motion adapter rollout；
- 高频数据进入 Tool message。
