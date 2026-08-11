# Forge Tool 实现计划

状态：`forge-tool` Endpoint models、logical Wire、complete factories、Query-first `ToolEndpointHandler` 和 optional `forge_tool.dora` Arrow carrier binding，以及 `forge_msgs.ToolMessage` 的 10 列 Arrow/Dora carrier schema 已实现。独立 Endpoint Host 概念已经取消，`packages/tool/src/forge_tool/host` 及其 public P1 identity/state/sequence primitives 已删除。`DoraToolEndpointBinding` 已完成单个 Arrow input 到 logical Query handler 再到 Arrow response 的转换，但不拥有 Dora `Node`、event loop 或 metadata；下一步把它嵌入第一个具体 Dora 业务 node。Action/Session、stateful buffering、Registry/Gateway、Web binding 和 Tool Runtime 仍属于后续阶段。

`forge.tool.endpoint/v1alpha1` 尚无 tagged/public Tool release；本文冻结的是该 identifier 的第一次 atomic release。此前 untagged prototype 不兼容且不声明 backward compatibility。`forge-tool`、Python/Rust/C++ `ToolMessage` binding、Gateway 和 provider 必须作为同一个 coordinated version set 部署，不支持 prototype/current mixed deployment。

本文描述 Forge Tool 通用调用能力，并与现有 `PolicyCommand` 并存。初期目标是建立清晰分层、可扩展的 Runtime API 与 endpoint SPI/Wire，同时支持或冻结：

- Forge/Dora 内部调用所需的 Arrow carrier contract；
- Gateway 对外 Web 调用的未来 binding；
- Query、Action、Session 三种 operation semantics；
- Endpoint registration 和 endpoint execution lifecycle contract；
- 现有 `PolicyCommand` 原样保留，当前不迁移、不弃用。

P0 不引入 MCP、A2A、Temporal 等外部协议或运行时依赖。它们只作为设计参考，后续可以通过 adapter 接入。

## 1. 设计原则

### 1.1 只维护一套 caller-facing Runtime 语义

初期只定义一套 caller-facing Runtime API：

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
Web caller  ── HTTP JSON/SSE binding ──┐
                                       ├── caller-facing Tool Runtime API
Dora caller ── future caller binding ──┘
                                                   │
                                                   │ resolve + create invocation/attempt
                                                   ▼
                                      ToolEndpoint Wire v1alpha1
                                                   │
                                                   ▼
具体 Dora 业务 node ── embedded binding/handler ── Query/Action/Session SPI ── 业务实现
```

Caller-facing Runtime API 面向 Web/Dora caller，提供 discovery、invoke、status、result、control 和 events；它隐藏 `attempt_id`、endpoint identity 等内部 routing 字段。Dora caller binding 与 Web binding 都必须进入同一个 Runtime API。

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

未来的 Gateway/Runtime 完成 resolver 和 attempt 创建后，再补充内部 routing identity。

### 1.5 高频数据不进入 Tool control message

Image、JointState、JointCommand、trajectory feedback 等高频或大体积数据继续走现有 Dora 数据面。Tool request 只携带小型参数或数据引用。

## 2. 外部框架参考范围

P0 不实现外部协议兼容，只参考成熟框架已经验证过的设计：

| Forge 能力 | 参考模式 | P0 采用内容 |
|---|---|---|
| Tool discovery 和参数 schema | MCP、OpenAI-style tools | name、description、JSON Schema input/output |
| 长任务 status/result/events | Agent task/resource API | invocation resource、查询、事件、terminal result |
| Action accepted/feedback/result/cancel | ROS 2 Action、Dora Action | accepted 不等于 completed；cancel accepted 不等于 cancelled |
| retry、dedup、crash recovery | Temporal-style execution | attempt、retry safety、ambiguous outcome |
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
- retry/fallback；
- invocation status/result；
- CompletionSpec；
- caller-facing event sequence。

### 4.4 Gateway

未来的 Gateway 负责：

- Web caller adapter 和未来 Dora caller adapter；
- Endpoint Registry；
- endpoint liveness；
- routing；
- request/response/event correlation；
- HTTP/SSE 和 endpoint Wire routing。

Gateway 不决定 implementation，不解释 CompletionSpec。

未来部署中，Tool Runtime 可以与 Gateway 位于同一进程，但应保持独立 domain module 和唯一状态所有权。

### 4.5 具体 Dora endpoint node 与 embedded binding/handler

ToolEndpoint 不定义独立执行主体。与 `forge_policy` 的集成方向相同，具体 Dora 业务 node 实现 Query/Action/Session endpoint SPI，并嵌入 ToolEndpoint binding/handler。

Embedded binding/handler 负责：

- 将 Dora Arrow carrier 转换为 logical message；
- 校验 descriptor，并把 operation 显式绑定到该 node 的 endpoint SPI；
- 处理 logical request，调用 Query/Action/Session SPI；
- 构造 correlated response、`tool.event`（其 event type 可为 `heartbeat`）、`endpoint.status` 与 `endpoint.register` lease-renewal Arrow value，并交给具体业务 node 发布；
- 后续按真实需求执行 admission、Accepted/Event ordering 和 private bounded duplicate suppression。

业务 endpoint 实现负责 executor 的权威状态，以及必要的 `ToolExecutionKey` 到私有 executor handle 映射；通用 binding 不维护第二份业务状态所有权，也不解释 Runtime CompletionSpec。

未来可以提供可选 runner 作为便利封装，但 runner 不能成为实现或部署 ToolEndpoint 的唯一方式。Dora integration 依赖应放在现有 package、业务 node 还是其他既有集成边界，由 vertical spike 决定；本计划不提前引入新 package 决策。

## 5. Caller-facing Runtime API 与 endpoint SPI

本节的 discovery/invoke/get status/get result/control/events 是 caller-facing Runtime API，供 Web caller 和 Dora caller 使用。Query/Action/Session 则是具体 endpoint node 实现的 provider SPI；Endpoint Wire 在 Runtime/Gateway 与 node 内嵌 handler 之间传输请求，不直接暴露给 caller。

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
    caller 重试同一逻辑调用

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

### 6.3 两种 dedup

Wire v1alpha1 规范冻结 key 和 decoded structural JSON identity，不定义 fingerprint：object key order 忽略但 member presence/name 参与，array 保持顺序，string 按精确 Unicode scalar sequence 比较且不做 Unicode normalization，`null`/boolean 保留类型并与 string/number 区分，number 按 finite IEEE-754 binary64 value 比较，因此 `1 == 1.0`、`-0 == 0`。raw envelope bytes、raw `payload_json` bytes 和 codec 输出从不作为 canonical identity，也不新增 Wire/Arrow fingerprint。

```text
execution exchange dedup key
    endpoint_instance_id + request_id

execution dedup key
    invocation_id + attempt_id
```

execution exchange dedup 只适用于 provider routing 已填入 concrete instance 的 exchange；pre-provider unresolved failure 不进入 endpoint-local dedup，仅按完整 correlation fields（含 `None` instance）关联 response。routed execution exchange 的 request identity 排除 `protocol`、`request_id`、`endpoint_instance_id`，包含 `message_type`、其余 route fields 和完整 decoded payload。相同 key/identity replay 已建立 response；不同 identity 返回 `FORGE_PROTOCOL_DEDUP_CONFLICT`。

`tool.invoke.request` 的 invoke identity 精确为 `endpoint_id + operation + payload`，排除 execution key、`request_id` 和 `endpoint_instance_id`。`arguments`、`context` 的全部字段及 optional member presence 都参与，因此 omitted 与 explicit `null` 不相同。相同 execution key/identity replay accepted response 或 terminal result，不重启 side effect；不同 identity 为 conflict。

Management `request_id` 仅用于 request/response correlation，不是 dedup key。Registry operation 按 trusted source 与 `current > tombstone > absent` precedence 实现 effect-idempotency，不套用 execution dedup。matching unregister tombstone replay 返回 tombstone 保存的 historical removal/expiry revision，即使 unrelated endpoint 已推进 process-global revision。tombstone、register resurrection/descriptor equality 和 receive-observation lease epoch 的完整规则见 7.5。当前 logical models、factories 和 carriers 不维护 async cache、execution store 或 retention window；execution guarantee 仍只覆盖一个 endpoint process epoch 和配置的 retention window，不承诺跨 restart exactly-once。

### 6.4 Ambiguous outcome

对于 Action/Session：

- Action/Session side effect 可能已开始、但 Accepted 建立前发生异常或断连时，不伪造 Accepted，也不盲目自动 retry；
- 无法恢复 execution outcome 时直接建立 initial terminal `unknown`；
- 未来 Runtime 根据 operation `retry_safety` 决定是否创建新 attempt；
- Motion 等物理动作最终需要稳定 goal/execution identity。

P0 不承诺跨进程重启的 exactly-once。

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

Event 携带 execution key 和 endpoint sequence；其 logical `request_id` 必须省略，Arrow carrier 中对应值为 null。`tool.error` 用于无法作为正常 invoke/status/result/control response 表达的协议或 transport-level failure。

### 7.5 Endpoint management

```text
endpoint.register
endpoint.unregister
endpoint.registry.response
endpoint.status
```

P0 保留 opaque `endpoint_instance_id`。所有 `tool.*` logical envelope 都可在 provider selection 前省略它；所有 `endpoint.*` message（含 `endpoint.status`）必须携带。Gateway 成功选定 provider 后必须填入 concrete instance，provider handler 仍执行 strict route validation；若 selection 前失败，correlated invoke response/error 保持 `None`。`endpoint.register`、`endpoint.unregister` 及其 correlated `endpoint.registry.response` 必须携带 `request_id`；unsolicited `endpoint.status` 必须省略。Registry response 的 operation 为 `register|unregister`，status 为 `accepted|rejected`，携带 non-negative interoperable `registry_revision`。accepted register 必须携带 positive `lease_ttl_ms` duration；accepted unregister 不携带 lease；rejected 不携带 lease 且必须携带 `ToolError`。conditional field 的 presence 有语义，显式 `lease_ttl_ms: null` 与 `error: null` 均非法。没有 observation timestamp，`endpoint.status` 仍是 unsolicited health snapshot 而不是 ACK。

Management `request_id` 只用于 correlation。Registry 对每个 `endpoint_id` 最多只接受一个 current instance，新 registration 替换 current instance 必须由 trusted transport generation/lease 或等价 source binding 授权；instance ID 本身不能排序 racing registration。lookup precedence 固定为 `current > tombstone > absent`，accepted new registration 清除 old tombstone，因此新 registration 之后旧 tombstone 不可 replay。

每个 `endpoint_id` 最多保留最后一个 tombstone，内容为 `endpoint_id`、`endpoint_instance_id`、accepted trusted source binding/generation、historical removal revision 和 reason `unregister|expired`。它保留到该 endpoint 的新 registration 被 accepted 或 Gateway restart；不跨 restart persistence。无 current 时，matching unregister replay 返回 tombstone 保存的 historical removal/expiry revision，即使 unrelated endpoint 已推进当前 process-global revision，也不返回新的 global revision。

`endpoint.register` 是显式 idempotent announce/upsert/lease renewal。register 按 precedence 处理：有 current 时，只有 same accepted source/generation/instance 且 descriptor exact equality 才是 idempotent renewal；descriptor change 被拒绝，其他 replacement 继续遵循 source/generation authority。无 current 且命中 explicit-unregister tombstone 时，exact same source+generation+instance registration non-retryable rejected as tombstoned；different instance 或 newer trusted source generation 可在 authority 允许时 registration，accept 后清 tombstone、创建新 lease 并增加 revision。命中 expiry tombstone 的 matching registration 可 recovery，accept 后同样清 tombstone、创建新 lease/revision。rejected registration 不清 tombstone。

Gateway adapter 在 validation 前捕获 trusted monotonic receive observation；operation accepted 时，Registry acceptance 和 lease start 逻辑上锚定该 observation。new register 与 register replay 从该 observation 开始/续租，不携带 wire timestamp。accepted unregister 首次移除和 expiry 各增加 revision 一次并写 tombstone；rejection 不增加 revision。`registry_revision` 是 Gateway-process-global monotonic state-change revision，不是 timestamp 或跨进程持久 version。current register renewal 返回 decision 时的 global revision；matching unregister tombstone replay 是例外，返回 tombstone historical revision。status/unregister 只能影响 accepted current instance 及其 accepted source；这些规则不放宽 cardinality/source-authority contract。生产 Registry/Gateway 实现仍属于后续 slice。

### 7.6 Complete envelope factory 和 correlation（已实现）

完整 `make_*_envelope` factory 是推荐的 public construction path，覆盖 invoke/status/result/control/event/error/register/unregister/registry response/endpoint status。`make_invoke_request_envelope` 接受 `endpoint_instance_id=None` 供 Gateway resolution；invoke response/error factory 原样复制 unresolved identity，保持 `None` correlation；non-P0 status/result/control request factory API 可继续要求 concrete instance。Execution request 和 event factory 从 `ToolContext` 派生 route identity；invoke/status/result/control response factory 直接从原始 request envelope 复制 correlation identity，不要求 endpoint node 为构造响应保留完整 invoke context。`make_endpoint_registry_response_envelope` 同样从原始 management request 复制 `request_id` 与 endpoint identities，并校验 operation 配对。

`validate_response_correlation(request, response)` 校验 execution response type 以及 `request_id`、`invocation_id`、`attempt_id`、`endpoint_id`、`endpoint_instance_id`、`operation`；control response 还必须匹配 request command。`validate_management_response_correlation(request, response)` 校验 Registry response type、`request_id`、两项 endpoint identity 和 operation。Raw payload adapter 继续保持 public，供 transport integration 和高级用法使用；完整 message 默认使用 factory。Model mapping 在构造时已经执行 bounded JSON validation 和 defensive copy。

## 8. 时间和顺序

### 8.1 不携带观测 timestamp

逻辑 message 和 Arrow carrier 不包含观测时间：

- Dora 使用 event context；
- Web 使用 Gateway request/event context；
- Gateway adapter 在 management validation 前捕获 trusted monotonic receive observation；accepted Registry operation 的 acceptance/lease epoch 锚定该 observation；
- Registry liveness 使用该 Gateway monotonic receive observation，不写入 Wire。

`deadline_ms` 是执行语义字段，继续保留，并限制在可互操作 JSON integer 范围。

### 8.2 两个 sequence scope

Endpoint sequence：

```text
endpoint_instance_id + invocation_id + attempt_id
```

具体 endpoint node 内嵌的 handler 在每个 scope 从 `0` 开始分配，并严格 `+1`。同一 retained sequence 加 structurally equal event 是 duplicate；同 sequence 加不同 event 是 conflict。高于 next expected 的值是 gap，必须从 retained history 或 authoritative status/result 恢复，不得虚构缺失事件；低于 next expected 且已不在 retained history 的值是 expired/stale，不作为新事件处理。sequence 不 wrap；分配 `2^53-1` 后再次分配返回 exhaustion error。这些是 Wire v1alpha1 的 normative semantics；contract 不要求 public sequence primitive，也不宣称已实现生产 retention/router。

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
| 任意 state | same-state replay |
| terminal | 不得变为不同 state |

terminal 指 `completed|failed|cancelled|stopped|unknown`；terminal phase/result 一旦建立即 immutable。`validate_execution_result(status, result)` 已实现单个 pair 的 terminal mapping 检查；当前不宣称已有 stateful lifecycle handler/store。

异步 execution 的 Accepted 必须先于相关 event 暴露；早到 event 需要 configured bounded buffer，overflow 必须 deterministic failure，不能无限增长。terminal result barrier 要求 matching authoritative `ToolResult` 先 retained，再暴露 terminal phase/event，以便 event 丢失后通过 status/result 恢复。Action/Session 在 Accepted 前发生不可恢复的不确定异常时，可直接 initial terminal `unknown`，不得伪造 Accepted 或盲目 retry。buffer、retention 和 barrier integration 仍是 endpoint node 内 embedded handler 的后续私有实现工作。

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
3. 将 identity、lifecycle、terminal barrier、dedup key 和 endpoint sequence 保留为 Wire v1alpha1 normative semantics，而不是 public state/sequence primitive；
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

### P1-C2：具体 Dora node embedding（下一步）

把 optional carrier binding 嵌入第一个具体 Dora 业务 node，完成 Dora input/output wiring 和 role-specific validation。通过最小 Dora graph 决定 topic 拆分、registration generation/lease；即使拆 topic，message type 仍需自描述。业务 node 自己拥有同步或异步 event loop，并负责 await binding 和发送返回的 Arrow value；binding 不在内部调用 `asyncio.run()`。

未来可以提供可选 runner 作为便利入口，但具体业务 node 必须始终能够直接嵌入 binding/handler，runner 不能成为唯一实现方式。

### P1-D：first real Query

接入第一个真实 Query operation（按 adapter 顺序优先 YOLO），先在 endpoint 边界验证 Wire request 经 Dora carrier、embedded handler 到业务 SPI 并返回 terminal result 的完整路径；caller-facing Runtime API 的贯通仍按 P2 推进。高频 image 数据继续走 Dora 数据面，Tool request 只携带小型参数或引用。

### P1-E：Action/Session

Query vertical path 稳定后，再扩展 Action/Session 的 start/status/result/control/event handling，并在 embedded handler 内满足 Accepted-before-Event、terminal result barrier、immutable terminal outcome、`unknown` 和 endpoint sequence 的 normative semantics。

### P1-F：按需 private bounded dedup

仅在真实重试、重复投递和并发行为表明需要时，为 embedded handler 增加 private、bounded exchange/execution dedup 和必要 retention。实现遵守已冻结 key 与 structural identity/conflict 规则，但不导出通用 public state/dedup/sequence primitive，不新增 Wire/Arrow fingerprint，也不改变 10 列 carrier。

## 11. P2：Tool Runtime、Gateway 和 Web/Dora binding

### P2.1 Tool Runtime

实现：

- ToolSpec repository；
- invocation repository；
- resolver；
- attempt state machine；
- resources/Control Lease；
- CompletionSpec；
- retry/fallback；
- result/event retention；
- restart 后 lost/unknown 处理。

### P2.2 Web binding

统一调用 route：

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

### P2.3 Dora caller binding

内部 Dora caller 和 Web caller 进入同一个 caller-facing Tool Runtime API，不直接构造 ToolEndpoint Wire 或调用 endpoint SPI。Gateway 从静态 graph/input binding 获得 Dora caller identity。

当前 `forge_msgs.ToolMessage` 只承载 Gateway/Runtime endpoint route 与具体 endpoint node 内嵌 binding/handler 之间的 ToolEndpoint Wire，不是已冻结的 caller-facing Runtime carrier。P2 vertical spike 再决定 Dora caller transport binding；即使复用相同物理列布局，也必须单独冻结 caller-side identity/correlation matrix，不能改变当前 Endpoint contract。

### P2.4 Idempotency 范围

内存实现只保证 Gateway epoch 和 retention window 内 idempotency。跨 restart 的强保证需要后续持久 invocation/idempotency ledger，不属于 P0。

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

P1 先用 YOLO Query 建立第一条真实 endpoint-node vertical path；后续扩展顺序为：

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
5. 将 binding 嵌入第一个具体 Dora 业务 node；
6. 接入第一个真实 Query；
7. 再实现 Action/Session lifecycle；
8. 最后仅在真实需求下增加 private bounded dedup。

已冻结的 Wire v1alpha1、10 列 carrier、message family、identity fields 和 lifecycle/sequence normative semantics 在此顺序中保持不变。

当前切片明确不做：

- MCP/A2A/OpenAI adapter；
- 修改或删除 `PolicyCommand`；
- 修改现有 Gateway HTTP 行为；
- 完整生产 Registry/Resolver/Completion；
- persistent exactly-once；
- Policy legacy/Tool 双控制；
- P1 首个 YOLO Query 之外的完整 LeRobot 或 Motion adapter rollout；
- 高频数据进入 Tool message。
