# forge_robot

Common robot driver protocol and node runner helpers for Forge robots.

- **RobotDriver**: `typing.Protocol` with `connect`, `disconnect`, `get_state`, and `set_command`.
- **LocomotionRobotDriver**: optional protocol for drivers that accept `forge_msgs.LocomotionCommand`.
- **BaseRobotDriver**: abstract base class with an optional `joint_order` property.
- **ActuatorSpec**: driver-facing joint/actuator metadata for limits and safety clipping.
- **device_tools**: shared JSON envelope helpers for device CLI commands.

Message payloads use `forge_msgs.JointState`, `forge_msgs.JointCommand`, and optional `forge_msgs.LocomotionCommand`.

The standard Dora node loop uses fixed input semantics:

- input `tick` to publish `state`
- input `action` as a low-level `JointCommand` for VLA/policy joint actions
- input `master_state` as a leader `JointState` mirrored to a low-level position `JointCommand`
- input `locomotion_command` as a high-level `LocomotionCommand` when the driver implements `LocomotionRobotDriver`

Device tool JSON includes `ok`, `capability`, `supported`, and `message`. `list-devices` returns address objects shaped as `{ name, address, status }` with optional `role`.
