# forge-msgs

Forge message definitions for Dora dataflow.

The canonical cross-language contract starts at
`interfaces/forge_msgs/forge_msgs.v1.yaml`. That manifest references the
versioned domain schemas followed by the Python, Rust, and C++ implementations.

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
- `mode: "position" | "velocity" | "effort" | "hybrid"`
- `position: list[float]`
- `velocity: list[float]`
- `effort: list[float]`
- `kp: list[float]`
- `kd: list[float]`

`mode` describes the command semantics. `position`, `velocity`, and `effort` match the common ROS2 command interfaces; `hybrid` is for low-level position/velocity/effort commands with optional `kp`/`kd` gains. Payloads written before `mode` existed are read as `mode="position"`.

`name` is a sparse update set: consumers update only the listed joints. Omitted joints retain their previous command target and must never be reset or filled with zero implicitly. Disjoint arm and gripper controllers can therefore share an ordered command stream without constructing a complete joint vector.

For Unitree-style low-level control, map `position -> q`, `velocity -> dq`, `effort -> tau`, `kp -> kp`, and `kd -> kd`.

### `LocomotionCommand`

Planar body-frame locomotion velocity command for ground robots.

- `vx: float`
- `vy: float`
- `wz: float`

`vx` and `vy` are body-frame linear velocities in m/s, with positive X forward and positive Y left. `wz` is angular velocity about the body-frame Z axis in rad/s, positive counter-clockwise, corresponding to ROS2 `Twist.angular.z` / yaw rate. Stop is represented by all zeros. This message intentionally omits `mode`, `duration`, `gait`, `body_height`, timestamp/frame fields, and full 6D Twist fields.

### `Image`

Uncompressed image payload.

- `height: int`
- `width: int`
- `encoding: str`
- `step: int`
- `data: bytes`

Supported encodings are `rgb8`, `bgr8`, `mono8`, `8UC1`, `16UC1`, `32SC1`,
and `32FC1`. Multi-byte pixels are little-endian. `8UC1` is available for
generic one-channel byte data such as label maps, while `32SC1` supports signed
32-bit label images. Compressed images use `CompressedImage`.

### `CompressedImage`

Compressed image bitstream payload.

- `format: str`
- `data: bytes`

Recommended formats are `jpeg`, `png`, and `webp`.

### `TeleopObservation`

XR device raw teleop observation for embodiment-specific teleop policies.

- `device: list[str]`: XR source ids; recommended ids are `left`, `right`, and
  `headset`. Match entries by id rather than list order.
- `x/y/z: list[float]`: positions in meters in the producer-configured XR
  tracking frame.
- `qx/qy/qz/qw: list[float]`: quaternion components in `xyzw` order.
- `confidence: list[float]`: finite producer-defined confidence values in
  `[0, 1]`; zero means that the aligned pose must not be used for control.
- `buttons_json: str`: JSON object of digital boolean and analog finite-number
  values keyed by button id.
- `axes_json: str`: JSON object of finite numbers or numeric arrays keyed by
  axis or documented derived-control id.

Recommended button ids include `A`, `B`, `X`, `Y`, the `left_`/`right_`
trigger and grip ids, and the joystick-click ids. `left_axis` and `right_axis`
are `[x, y]` joystick pairs. An unavailable pose may use zero position and an
identity quaternion with confidence `0`.

The payload does not carry the tracking-frame origin, handedness, axis
directions, or timestamp. Document the frame convention in producer
configuration and carry timing in Dora event context or an adapter layer.

### `Text`

Single UTF-8 text payload for ASR transcripts, LLM responses, TTS input, and other text streams.

- `text: str`

Producers should omit empty outputs when there is no meaningful text.

### `ToolMessage`

Cross-language single-row Arrow carrier for one Forge ToolEndpoint v1alpha1
logical message. This is the release candidate for the first tagged/public Tool
protocol contract; earlier untagged prototypes are incompatible, and Python/Rust/C++
bindings plus Gateway and provider must deploy atomically. Its exact ten-column order is `protocol`, `message_type`,
`request_id`, `invocation_id`, `attempt_id`, `endpoint_id`,
`endpoint_instance_id`, `operation`, `sequence`, and `payload_json`; all are
`utf8` except nullable `sequence: int64`. `request_id`, `invocation_id`,
`attempt_id`, `endpoint_instance_id`, `operation`, and `sequence` use Arrow null when
omitted. `endpoint_instance_id` is structurally nullable on pre-routing `tool.*` messages,
but a provider-originated `tool.event` must supply its concrete instance; every
`endpoint.*` message, including `endpoint.status`, requires it.

`payload_json` encodes the logical payload object rather than the full carrier
envelope. It must be a bounded strict JSON object with unique keys, valid Unicode,
finite numbers, interoperable integers, and at most 64 levels. The carrier has no
observation timestamp; use Dora event context for transport observation time.
`forge_msgs` validates the carrier and generic header/identity matrix, including the
`endpoint.registry.response` message class. Registration, unregister, and Registry response carriers
require `request_id`; unsolicited endpoint status requires null and
remains a health message rather than an ACK. Message-specific payload validation remains in
`forge-tool`. Python, Rust, and C++
implement the carrier, with bidirectional Python/C++ Arrow IPC compatibility
coverage.

### Perception result sets

The perception messages use parallel Arrow list columns in a single-row
`RecordBatch`:

- `Detection2DSet` stores oriented pixel-space boxes and flattened class
  hypotheses. Axis-aligned boxes use `rotation=0`, and high-level constructors
  may fill that default automatically.
- `Detection3DSet` stores oriented metric boxes and flattened class hypotheses.
  Axis-aligned boxes use identity orientation (`qx=0`, `qy=0`, `qz=0`, `qw=1`),
  and high-level constructors may fill that default automatically.
- `SegmentationMaskSet` stores cropped `mono8` instance masks and their source
  image offsets. Standalone masks can omit detection and track associations,
  and high-level constructors may fill empty associations and zero offsets.

Detection class names and model label maps belong in node configuration.
`class_id` is the stable identifier carried on the wire.
Local features such as ORB, SIFT, or SuperPoint descriptors are intentionally
kept out of the core streaming schema; publish higher-level outputs unless a
future pipeline needs cross-node feature reuse.

### `PointCloud`

`PointCloud` stores common XYZ point clouds as Arrow lists with optional
intensity and RGB columns. Organized clouds preserve `width` and `height`;
unorganized clouds use `height=1`. Coordinates use meters, while the coordinate
frame is supplied by Dora metadata or node configuration. High-level
constructors may infer unorganized clouds from `x/y/z` by setting `height=1`,
`width=len(x)`, and `is_dense` from finite XYZ values.

The owned `PointCloud` model uses Python lists and is intended for convenience,
tests, and small clouds. Treat an instance as an immutable message value after
construction. High-throughput producers can construct the same wire schema from
typed NumPy buffers:

```python
import numpy as np
from forge_msgs import PointCloudBatch, PointCloudView

x = np.arange(640 * 480, dtype=np.float32).reshape(480, 640)
y = np.zeros_like(x)
z = np.ones_like(x)

# Safe default: create an immutable payload snapshot.
batch = PointCloudBatch.from_numpy(x=x, y=y, z=z).to_arrow()

# Consumer-side field views share the Arrow value buffers and are read-only.
view = PointCloudView.from_arrow(batch)
assert view.x.shape == (640 * 480,)
```

A `PointCloudView` is not an immutable snapshot: mutations through any
independent writable alias to the input Arrow storage remain observable.

XYZ inputs are same-shape one- or two-dimensional `float32` arrays. A 2D shape
infers organized `height/width`; view properties are always flat row-major
arrays. Optional intensity is `float32` with the XYZ shape or a flat point-count
shape. RGB is `uint8`, supplied either as three matching channel arrays or one
interleaved `(..., 3)` array. `is_dense=None` scans XYZ once to infer density.

`PointCloudBatch.from_numpy()` has explicit payload-buffer policies:

- `copy="always"` is the safe default and snapshots every supplied attribute.
- `copy="if_needed"` borrows only exact-dtype, naturally aligned, C-contiguous
  arrays whose visible backing chain is read-only. Inputs that satisfy the shape
  and casting contract but cannot be borrowed are copied.
- `copy="never"` rejects any input that cannot be borrowed. Small scalar and
  Arrow list-offset buffers are still allocated.
- `casting="no"` is the default, so dtype mismatches are rejected. `safe` or
  `same_kind` casting must be requested separately and requires a copy when the
  dtype changes. Float32 and RGB range checks still apply.

A three-array `(red, green, blue)` tuple can use the borrowing path. Interleaved
`(..., 3)` RGB requires deinterleaving into the v1 SoA columns and is therefore
rejected by `copy="never"`.

When borrowing, Arrow retains the exported buffer lifetime, so callers do not
need to keep source-array references alive manually. Callers are still
responsible for ensuring that no remaining writable alias modifies the storage
or re-enables writes until all derived Arrow batches and views are released.
NumPy's read-only flag is a guard, not a guarantee against another alias. Use the
default `copy="always"` whenever immutability cannot be guaranteed. Buffer
sharing applies only to the local NumPy/PyArrow boundary; it does not imply that
Dora IPC, networking, recording, or downstream layout conversion is end-to-end
zero-copy.

## Motion Messages

The motion API provides single-row Arrow payloads for joint trajectories and
configured-group motion actions:

- `JointTrajectoryPoint`, `JointTrajectory`, and `JointTolerance`
- `FollowJointTrajectoryGoal`, `FollowJointTrajectoryFeedback`, and
  `FollowJointTrajectoryResult`
- `GripperCommandGoal`, `GripperCommandFeedback`, and `GripperCommandResult`
- `MoveJointsGoal`, `MoveJointsFeedback`, and `MoveJointsResult`
- `MovePoseGoal`, `MovePoseFeedback`, and `MovePoseResult`

Trajectory points and tolerances are encoded as nested Arrow structs, including
`list<struct>` trajectory and tolerance fields. `MovePose*` messages reuse
`Pose` as a nested struct. Optional scalar and pose fields are represented by
Arrow nulls rather than sentinel values.

`GripperCommand` addresses the coordinate configured for its controller endpoint;
it does not carry `joint_name` or a dynamic unit. Prismatic coordinates use meters,
meters/s, and Newtons. Revolute or rotary actuator coordinates use radians,
radians/s, and Newton-meters. Explicit velocity or effort limits remain nullable so
a position-only backend can reject unsupported requested limits rather than silently
ignore them.

`goal_id` and `goal_status` are Dora action metadata and are intentionally not
included in payload columns. Domain result codes are separate from Dora's
lowercase terminal `goal_status` values.

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
