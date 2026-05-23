# forge_msgs Interface Schema v1

This directory is the language-neutral contract for `forge_msgs`.

Python (`packages/msgs`), Rust (`crates/forge_msgs`), and future C++ implementations should treat `forge_msgs.v1.yaml` as the source of truth. The implementations may be handwritten at first, but their Arrow schemas and validation rules should conform to this interface.

## Transport Contract

- Payloads are single-row Apache Arrow `RecordBatch` values.
- The schema does not require Arrow metadata. Dora/IPC paths may drop metadata, so required semantics must be represented as real columns.
- Core messages do not contain ROS-style `Header`, timestamp, or `frame_id`.
- Timing and frame information should live in Dora event context, topic naming, node configuration, or adapter layers.

## Messages

### JointState

Robot or simulator joint observation payload.

Fields:

- `name: list<utf8>`
- `position: list<float64>`
- `velocity: list<float64>`
- `effort: list<float64>`

Rules:

- `name` must be non-empty.
- `name` items must be unique.
- `position`, `velocity`, and `effort` must either be empty or have the same length as `name`.
- Units follow common robotics convention: revolute position in radians, velocity in radians/s, effort in Nm; prismatic position in meters, velocity in meters/s, effort in N.

### JointCommand

Joint command payload for robot drivers and controllers.

Fields:

- `name: list<utf8>`
- `position: list<float64>`
- `velocity: list<float64>`
- `effort: list<float64>`
- `kp: list<float64>`
- `kd: list<float64>`

Rules:

- `name` must be non-empty.
- `name` items must be unique.
- Each numeric list must either be empty or have the same length as `name`.
- `kp` and `kd` are optional low-level gains. For Unitree-style low-level control, map `position -> q`, `velocity -> dq`, `effort -> tau`, `kp -> kp`, and `kd -> kd`.

### Image

Uncompressed image payload.

Fields:

- `height: uint32`
- `width: uint32`
- `encoding: utf8`
- `step: uint32`
- `data: large_binary`

Rules:

- `step` is the full row length in bytes and may include row padding.
- `data` length must equal `step * height`.
- For known encodings, `step` must be at least `width * bytes_per_pixel`.
- Multi-byte pixel encodings are little-endian.
- Compressed `jpeg`, `png`, or `webp` payloads use `CompressedImage`.

Recommended encodings:

- `rgb8`
- `bgr8`
- `mono8`
- `16UC1`
- `32FC1`

### CompressedImage

Compressed image bitstream payload.

Fields:

- `format: utf8`
- `data: large_binary`

Recommended formats:

- `jpeg`
- `png`
- `webp`

## Cross-Language Implementation Notes

- Python, Rust, and C++ structs should use the same field names as the schema.
- Arrow field order should match `forge_msgs.v1.yaml`.
- Implementations should reject duplicate joint names and invalid list lengths.
- Implementations should not infer missing columns. A payload either conforms to the schema or fails validation.
- Helper methods may convert to fixed-order arrays, but fixed order is not part of the wire schema.
