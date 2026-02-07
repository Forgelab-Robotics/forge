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
  - `unit`: `"radians"` | `"meters"` | `"radians/s"` | `"meters/s"` | `"Nm"` | `"A"`

- **`ActuatorValue`**：执行器/驱动空间量，字段与 `JointValue` 相同

- **`JointMode`** / **`JointUnit`**：IntEnum，用于 Arrow 列式格式的零拷贝（mode/unit 以 int8 存储）

### 策略消息

- **`PolicyObservation`**：策略观测
  - `timestamp`: float
  - `joints`: Dict[str, JointValue]

- **`PolicyAction`**：策略动作
  - `ref_timestamp`: float
  - `joints`: Dict[str, JointValue]

### 驱动消息

- **`DriverFeedback`**：驱动反馈
  - `timestamp`: float
  - `actuators`: Dict[str, ActuatorValue]

- **`DriverCommand`**：驱动指令
  - `timestamp`: float
  - `actuators`: Dict[str, ActuatorValue]

## 列式 Arrow 格式

所有消息使用列式 `pa.RecordBatch`，支持零拷贝。`to_arrow()` 和 `from_arrow()` 均需传入 `joint_order` 或 `actuator_order` 以确定列顺序。

### 发送数据

```python
from dora import Node
from forge_msgs import (
    PolicyObservation,
    PolicyAction,
    DriverFeedback,
    DriverCommand,
    JointValue,
    ActuatorValue,
)

node = Node()
joint_order = ["joint1", "joint2"]
actuator_order = ["act1"]

# 发送 PolicyObservation
obs = PolicyObservation(
    timestamp=1.0,
    joints={
        "joint1": JointValue(value=0.5, mode="position", unit="radians"),
        "joint2": JointValue(value=0.1, mode="velocity", unit="radians/s"),
    },
)
node.send_output("observation", obs.to_arrow(joint_order))

# 发送 PolicyAction
action = PolicyAction(
    ref_timestamp=2.0,
    joints={"joint1": JointValue(value=0.6, mode="position", unit="radians")},
)
node.send_output("action", action.to_arrow(joint_order))

# 发送 DriverFeedback
feedback = DriverFeedback(
    timestamp=1.0,
    actuators={"act1": ActuatorValue(value=0.5, mode="position", unit="radians")},
)
node.send_output("feedback", feedback.to_arrow(actuator_order))

# 发送 DriverCommand
command = DriverCommand(
    timestamp=2.0,
    actuators={"act1": ActuatorValue(value=0.6, mode="torque", unit="Nm")},
)
node.send_output("command", command.to_arrow(actuator_order))
```

### 接收数据

```python
from dora import Node
from forge_msgs import (
    PolicyObservation,
    PolicyAction,
    DriverFeedback,
    DriverCommand,
)

node = Node()
joint_order = ["joint1", "joint2"]
actuator_order = ["act1"]

for event in node:
    if event["type"] != "INPUT":
        continue

    match event["id"]:
        case "observation":
            obs = PolicyObservation.from_arrow(event["value"], joint_order)
            # 或零拷贝直接得到 numpy：
            obs_np = PolicyObservation.to_np_from_arrow(event["value"], joint_order)

        case "action":
            action = PolicyAction.from_arrow(event["value"], joint_order)
            # 使用 action.ref_timestamp, action.joints ...

        case "feedback":
            feedback = DriverFeedback.from_arrow(event["value"], actuator_order)
            # 或零拷贝：fb_np = DriverFeedback.to_np_from_arrow(event["value"], actuator_order)

        case "command":
            command = DriverCommand.from_arrow(event["value"], actuator_order)
```

### 零拷贝与 numpy 互转

```python
# 观测 -> numpy（零拷贝）
obs_np = PolicyObservation.to_np_from_arrow(event["value"], joint_order)

# 反馈 -> numpy（零拷贝）
fb_np = DriverFeedback.to_np_from_arrow(event["value"], actuator_order)

# numpy -> 动作
action = PolicyAction.from_np(action_np, joint_order, ref_timestamp=2.0)

# numpy -> 指令
command = DriverCommand.from_np(cmd_np, actuator_order, timestamp=2.0)
```
