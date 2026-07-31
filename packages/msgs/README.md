# forge-msgs

Forge message definitions for Dora dataflow.

The canonical cross-language contract starts at
`interfaces/forge_msgs/forge_msgs.v1.yaml`. That manifest references the
versioned domain schemas that Python, Rust, and future C++ implementations
should follow.

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
