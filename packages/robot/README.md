# forge_robot

Common robot driver protocol and node runner helpers for Forge robots.

- **RobotDriver**: `typing.Protocol` with `connect`, `disconnect`, `get_state`, and `set_command`.
- **BaseRobotDriver**: abstract base class with an optional `joint_order` property.
- **ActuatorSpec**: driver-facing joint/actuator metadata for limits and safety clipping.
- **device_tools**: shared JSON envelope helpers for device CLI commands.

Message payloads use `forge_msgs.JointState` and `forge_msgs.JointCommand`.

The standard Dora node loop uses:

- input `tick` to publish `joint_state`
- input `command` to call `driver.set_command(...)`
- input `master_joint_state` to mirror a master `JointState` as a position `JointCommand`

Device tool JSON includes `ok`, `capability`, `supported`, and `message`. `list-devices` returns address objects shaped as `{ name, address, status }` with optional `role`.
