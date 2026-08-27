# Forge Tool documentation

Forge Tool separates a caller-facing Tool Runtime from the provider-side
ToolEndpoint contract. The files in this directory document the stable provider
boundary and its logical Wire protocol.

The protocol identifier is `forge.tool.endpoint/v1alpha1`. Tool `0.1.0` is the first
tagged/public Forge Tool release.

## Read this first

| Document | Audience | Purpose |
| --- | --- | --- |
| [Architecture](ARCHITECTURE.md) | Maintainers and integrators | Explains the Runtime, Gateway, Wire, carrier, handler, and provider boundaries; identifies state ownership and non-goals. |
| [Wire protocol](PROTOCOL.md) | Gateway, provider, and cross-language implementers | Normative logical envelope, payload, identity, correlation, lifecycle, Registry, ordering, and carrier-mapping rules. |
| [Python package guide](../../packages/tool/README.md) | Python endpoint authors | Installation, examples, public API map, Dora embedding, limits, and current package restrictions. |
| [`ToolMessage` Arrow schema](../forge_msgs/tool.v1.yaml) | Carrier implementers | Canonical field order, Arrow types, nullability, and generic carrier validation. |

## Contract versus implementation

The ToolEndpoint definition is independent of rollout status. Current Python package
capabilities and restrictions belong to the
[`forge-tool` package guide](../../packages/tool/README.md) and its tests. Gateway,
Runtime, and concrete provider progress belongs to those components' own repositories
and issue trackers; this interface directory intentionally maintains no cross-component
implementation roadmap.

## Source of truth

Each fact should have one primary owner. Other documents summarize and link instead of
copying the full contract.

| Question | Primary source |
| --- | --- |
| What are the architectural boundaries and state owners? | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| What is valid on the logical Wire? | [`PROTOCOL.md`](PROTOCOL.md) |
| What is the exact Arrow schema? | [`../forge_msgs/tool.v1.yaml`](../forge_msgs/tool.v1.yaml) |
| How do I use the Python package and see its current restrictions? | [`../../packages/tool/README.md`](../../packages/tool/README.md) and [`../../packages/tool/tests`](../../packages/tool/tests) |
| What changed in a release? | [`../../CHANGELOG.md`](../../CHANGELOG.md) |
| What are the release/tag and coordinated-deployment rules? | [`../../RELEASING.md`](../../RELEASING.md) and [protocol versioning](PROTOCOL.md#31-version) |

## Terminology

- **Operator node**: Forge-native computation such as policy, perception, control, or
  simulation. See the [Forge node model](../../README.md#forge-node-model).
- **Adapter node**: a boundary to an external device, service, runtime, or caller, such
  as robot, camera, or Gateway.
- **External caller**: an Agent framework, Web application, or other client outside the
  Forge node taxonomy. It reaches Tool semantics through a Gateway caller binding.
- **Tool Runtime**: the target caller-facing owner of ToolSpec discovery, invocation and
  attempt creation, implementation selection, caller-visible status/result/events, and
  CompletionSpec. It is a logical domain responsibility, normally hosted by Gateway, not
  a node category.
- **Gateway**: the Adapter node that owns caller transport and provider routing and
  normally hosts Tool Runtime. Within it, the Registry/router role owns endpoint
  availability and concrete endpoint-instance route lookup, but does not perform logical
  implementation selection or provider business execution.
- **ToolEndpoint Wire**: the internal provider protocol defined by
  [`PROTOCOL.md`](PROTOCOL.md).
- **Endpoint SPI**: the Python structural contracts implemented by a concrete provider:
  `QueryToolEndpoint`, `ActionToolEndpoint`, or `SessionToolEndpoint`.
- **Carrier**: the physical representation of one logical message. Dora uses the
  single-row Arrow `forge_msgs.ToolMessage` carrier.
- **Provider node**: an Operator or Adapter that owns the executor, embeds the
  handler/binding, and owns its Dora node and event loop. `ToolEndpoint` is a capability,
  not a third node category.

The architecture document defines these terms in context.

## Compatibility

Tool `0.1.0` and Msgs `1.2.0` define one coordinated contract set. Compatible
deployments must use matching `forge-tool`, Python/Rust/C++ `ToolMessage` bindings,
Gateway, and provider revisions. Earlier untagged prototypes are not a compatibility
baseline, even if they used the same v1alpha1 identifier.
