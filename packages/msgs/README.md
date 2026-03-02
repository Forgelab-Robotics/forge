# forge-msgs

Forge 消息定义，用于 Dora 数据流。采用列式 Arrow 格式，支持零拷贝序列化。

## 安装

```bash
uv add forge-msgs
# 或
pip install forge-msgs
```

## 数据类型

### 基础值类型

- **`JointValue`**：关节/关节空间量
  - `value`: float
  - `mode`: `"position"` | `"velocity"` | `"torque"` | `"prismatic"`
  - `unit`: `"radians"` | `"millimeters"` | `"meters"` | `"radians/s"` | `"millimeters/s"` | `"meters/s"` | `"Nm"` | `"A"`（直线关节默认 millimeters / millimeters/s）

- **`ActuatorValue`**：执行器/驱动空间量，字段与 `JointValue` 相同

- **`JointMode`** / **`JointUnit`**：IntEnum，用于 Arrow 列式格式的零拷贝（mode/unit 以 int8 存储）

### TaskRobot 层

- **`ProprioState`**：TaskRobot 产出，本体状态（joints，不含图像）
  - `timestamp`: float
  - `joints`: Dict[str, JointValue]

- **`Action`**：输入 TaskRobot 的动作
  - `ref_timestamp`: float
  - `joints`: Dict[str, JointValue]

### Robot 层

- **`RobotState`**：Robot 产出，机器人状态
  - `timestamp`: float
  - `actuators`: Dict[str, ActuatorValue]

- **`RobotAction`**：输入 Robot 的动作
  - `timestamp`: float
  - `actuators`: Dict[str, ActuatorValue]

## 列式 Arrow 格式

所有消息使用列式 `pa.RecordBatch`，支持零拷贝。`to_arrow()` 和 `from_arrow()` 均需传入 `joint_order` 或 `actuator_order` 以确定列顺序。时间/对齐字段（`ProprioState.timestamp`、`ActionSequence.ref_timestamp`）均作为正式列写入，不使用 schema metadata，避免 dora/IPC 传递时丢失。

### 发送数据

```python
from dora import Node
from forge_msgs import (
    ProprioState,
    Action,
    RobotState,
    RobotAction,
    JointValue,
    ActuatorValue,
)

node = Node()
joint_order = ["joint1", "joint2"]
actuator_order = ["act1"]

# 发送 ProprioState（TaskRobot 产出）
state = ProprioState(
    timestamp=1.0,
    joints={
        "joint1": JointValue(value=0.5, mode="position", unit="radians"),
        "joint2": JointValue(value=0.1, mode="velocity", unit="radians/s"),
    },
)
node.send_output("proprio_state", state.to_arrow(joint_order))

# 发送 Action（输入 TaskRobot）
action = Action(
    ref_timestamp=2.0,
    joints={"joint1": JointValue(value=0.6, mode="position", unit="radians")},
)
node.send_output("action", action.to_arrow(joint_order))

# 发送 RobotState（Robot 产出）
robot_state = RobotState(
    timestamp=1.0,
    actuators={"act1": ActuatorValue(value=0.5, mode="position", unit="radians")},
)
node.send_output("robot_state", robot_state.to_arrow(actuator_order))

# 发送 RobotAction（输入 Robot）
robot_action = RobotAction(
    timestamp=2.0,
    actuators={"act1": ActuatorValue(value=0.6, mode="torque", unit="Nm")},
)
node.send_output("robot_action", robot_action.to_arrow(actuator_order))
```

### 接收数据

```python
from dora import Node
from forge_msgs import (
    ProprioState,
    Action,
    RobotState,
    RobotAction,
)

node = Node()
joint_order = ["joint1", "joint2"]
actuator_order = ["act1"]

for event in node:
    if event["type"] != "INPUT":
        continue

    match event["id"]:
        case "proprio_state":
            state = ProprioState.from_arrow(event["value"], joint_order)
            # 或零拷贝直接得到 numpy：
            state_np = ProprioState.to_np_from_arrow(event["value"], joint_order)

        case "action":
            action = Action.from_arrow(event["value"], joint_order)
            # 使用 action.ref_timestamp, action.joints ...

        case "robot_state":
            robot_state = RobotState.from_arrow(event["value"], actuator_order)
            # 或零拷贝：state_np = RobotState.to_np_from_arrow(event["value"], actuator_order)

        case "robot_action":
            robot_action = RobotAction.from_arrow(event["value"], actuator_order)
```

### 零拷贝与 numpy 互转

```python
# ProprioState -> numpy（零拷贝）
state_np = ProprioState.to_np_from_arrow(event["value"], joint_order)

# RobotState -> numpy（零拷贝）
state_np = RobotState.to_np_from_arrow(event["value"], actuator_order)

# numpy -> Action
action = Action.from_np(action_np, joint_order, ref_timestamp=2.0)

# numpy -> RobotAction
robot_action = RobotAction.from_np(action_np, actuator_order, timestamp=2.0)
```
