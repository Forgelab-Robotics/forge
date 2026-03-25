# forge-configs

统一的任务配置与节点配置生成库。

目标：

- 使用一份任务级配置（`TaskConfig`）描述机器人、关节、相机、tick 周期等信息
- 从任务配置生成各个节点的 YAML 配置（如 simulator、task_robot、dataflow）
- 在 `forge_runtime` 以及其他 runtime / 工具之间共享同一份「真相来源」

当前已提供：

- `TaskConfig`/`RobotConfig`/`CameraConfig`/`SimulatorConfig`/`TaskRobotConfig` 数据模型
- `load_task(path)`：从 YAML 载入任务配置

后续可以在此基础上继续扩展生成器，例如：

- `to_mujoco_config(scenario) -> dict` 对应 `simulator.yaml`
- `to_task_robot_config(scenario) -> dict` 对应 `task_robot.yaml`
- `to_dataflow_config(scenario) -> dict` 对应 `dataflow.yaml`

