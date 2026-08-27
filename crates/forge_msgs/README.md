# forge_msgs

Rust message types and Arrow serialization for Forge robotics dataflows.

The canonical cross-language message contract starts at
`../../interfaces/forge_msgs/forge_msgs.v1.yaml`. The manifest references the
versioned domain schemas. This crate should stay aligned with those schemas and
with the Python `forge-msgs` package.

## Messages

The crate currently exports:

- `JointState` and `JointCommand`
- `LocomotionCommand`
- `Image` and `CompressedImage`
- `PointCloud`
- `Detection2DSet` and `Detection3DSet`
- `SegmentationMaskSet`
- `Pose` and `PoseSet`
- `PolicyCommand` and `PolicyCommandStatus`
- `ToolMessage`
- `Text`

Each message type is designed for single-row Arrow `RecordBatch` interchange.

`ToolMessage`, defined by `tool.v1.yaml`, is the first tagged/public Tool protocol
contract; earlier untagged prototypes are incompatible, and Python/Rust/C++ bindings
plus Gateway and provider must deploy atomically. It is implemented in Python, Rust,
and C++ as an exact ten-column carrier ordered as `protocol`, `message_type`,
`request_id`, `invocation_id`, `attempt_id`, `endpoint_id`,
`endpoint_instance_id`, `operation`, `sequence`, and `payload_json`. All columns
are `utf8` except nullable `sequence: int64`; optional values use Arrow null.
`endpoint_instance_id` may be null on any `tool.*` message; every `endpoint.*` message,
including `endpoint.status`, requires it.
`payload_json` is a bounded strict JSON object with unique keys, valid Unicode,
finite numbers, interoperable integers, and at most 64 levels. Message-specific
validation remains in `forge-tool`. The known management types include
`endpoint.registry.response`; register, unregister, and Registry response require
`request_id`, while unsolicited endpoint status requires null. Transport
observation time is not a carrier column. The repository's bidirectional IPC
compatibility coverage for this carrier
is between Python and C++.

## Testing

Run the crate tests from the workspace root:

```bash
cargo test -p forge_msgs
```
