# forge_simulators_mujoco

MuJoCo 仿真器节点，用于 Forge 机器人框架。

## 架构

作为独立 Dora 节点运行：

- **输入**：RobotAction（来自 TaskRobot）
- **输出**：RobotState（发给 TaskRobot）

TaskRobot 与 Simulator 之间通过 RobotState / RobotAction 通信。

## 单位

接口统一使用：

- **角度**：radians
- **距离**：millimeters（直线关节）
- **速度**：radians/s（旋转）或 millimeters/s（直线）

MuJoCo 内部为 radians/meters，在边界处与 millimeters 互相转换。

## 使用

```python
import mujoco
from forge_simulators_mujoco import MuJoCoSimulator

model = mujoco.MjModel.from_xml_path("scene.xml")
data = mujoco.MjData(model)

joints = [...]
actuators = [...]
sim = MuJoCoSimulator(
    model=model,
    data=data,
    joints=joints,
    actuators=actuators,
    prefix="robot1/",
)

# 仿真循环
sim.reset()
while True:
    state = sim.get_state()  # RobotState
    # 发送 state 给 TaskRobot（通过 Dora）

    # 接收 action 来自 TaskRobot（通过 Dora）
    sim.set_action(action)  # RobotAction

    mujoco.mj_step(model, data)
```

## 依赖

- `mujoco`：由调用方安装（本包不强制依赖，便于灵活部署）
