# forge-msgs

Forge message definitions for Dora dataflow.

The canonical cross-language contract lives in `interfaces/forge_msgs/forge_msgs.v1.yaml`. Python, Rust, and future C++ implementations should conform to that schema.

## Core Messages

### `JointState`

Robot or simulator joint observation payload.

- `name: list[str]`
- `position: list[float]`
- `velocity: list[float]`
- `effort: list[float]`

`name` must be non-empty and unique. Numeric lists must either be empty or have the same length as `name`.

### `JointCommand`

Command payload for robot drivers and controllers.

- `name: list[str]`
- `position: list[float]`
- `velocity: list[float]`
- `effort: list[float]`
- `kp: list[float]`
- `kd: list[float]`

For Unitree-style low-level control, map `position -> q`, `velocity -> dq`, `effort -> tau`, `kp -> kp`, and `kd -> kd`.

### `Image`

Uncompressed image payload.

- `height: int`
- `width: int`
- `encoding: str`
- `step: int`
- `data: bytes`

Supported encodings are `rgb8`, `bgr8`, `mono8`, `16UC1`, and `32FC1`. Multi-byte pixels are little-endian. Compressed images use `CompressedImage`.

### `CompressedImage`

Compressed image bitstream payload.

- `format: str`
- `data: bytes`

Recommended formats are `jpeg`, `png`, and `webp`.

## Arrow Format

All core messages encode to a single-row `pyarrow.RecordBatch`.

```python
from forge_msgs import JointCommand, JointState

state = JointState(
    name=["joint1", "joint2"],
    position=[0.1, 0.2],
    velocity=[0.0, 0.0],
    effort=[],
)
batch = state.to_arrow()
back = JointState.from_arrow(batch)

command = JointCommand.from_np(
    values=[0.3, 0.4],
    order=["joint1", "joint2"],
    field="position",
)
```

Timing and frame data are intentionally not part of the core schema. Carry them in Dora event context, topic naming, node configuration, or adapter layers.
