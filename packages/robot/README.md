# forge_robot

forge_robots 通用机器人驱动协议与抽象基类。各机器人实现（如 piper）可依赖本包并实现 `RobotDriver` 协议或继承 `BaseRobotDriver`。

- **RobotDriver**：`typing.Protocol`，约定 `connect`、`disconnect`、`get_state`、`set_actuators`。
- **BaseRobotDriver**：抽象基类，实现上述协议并增加可选属性 `actuator_order`。
- **ActuatorSpec**：通用执行器语义规格，描述 name、kind、mode、单位与位置限位。
- **port_tools**：端口 CLI 结果 helper，统一 `list-ports`、`activate-ports`、`check-ports`、`check-role`、`set-role`、`test`、`cancel-test` 的 JSON envelope。

消息格式统一使用 forge_msgs 的 `RobotState`、`RobotAction`。

端口工具 JSON 统一包含 `ok`、`capability`、`supported`、`message`。发现/检查类命令在 `ports` 中返回统一 address 对象 `{ name, address, status }`，角色检测在 `roles` 中返回 `{ name, role }`。不适用于某个机器人时命令仍返回 `ok: true, supported: false`，便于前端统一调用。
