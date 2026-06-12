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
- `Pose` and `PoseSet`
- `PolicyCommand` and `PolicyCommandStatus`

Each message type is designed for single-row Arrow `RecordBatch` interchange so
Rust, Python, and Dora nodes can exchange the same payloads.

## Testing

Run the crate tests from the workspace root:

```bash
cargo test -p forge_msgs
```
