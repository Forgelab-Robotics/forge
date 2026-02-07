# forge-msgs

Forge 消息定义，用于 Dora 数据流。

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

## 与 dora-rs 的转换

所有消息类型均提供 `to_arrow()` 和 `from_arrow()`，用于与 dora-rs 的 Apache Arrow 格式互通。

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

# 发送 PolicyObservation
obs = PolicyObservation(
    timestamp=1.0,
    joints={
        "joint1": JointValue(value=0.5, mode="position", unit="radians"),
        "joint2": JointValue(value=0.1, mode="velocity", unit="radians/s"),
    },
)
node.send_output("observation", obs.to_arrow())

# 发送 PolicyAction
action = PolicyAction(
    ref_timestamp=2.0,
    joints={"joint1": JointValue(value=0.6, mode="position", unit="radians")},
)
node.send_output("action", action.to_arrow())

# 发送 DriverFeedback
feedback = DriverFeedback(
    timestamp=1.0,
    actuators={"act1": ActuatorValue(value=0.5, mode="position", unit="radians")},
)
node.send_output("feedback", feedback.to_arrow())

# 发送 DriverCommand
command = DriverCommand(
    timestamp=2.0,
    actuators={"act1": ActuatorValue(value=0.6, mode="torque", unit="Nm")},
)
node.send_output("command", command.to_arrow())
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

for event in node:
    if event["type"] != "INPUT":
        continue

    match event["id"]:
        case "observation":
            obs = PolicyObservation.from_arrow(event["value"])
            # 使用 obs.timestamp, obs.joints ...

        case "action":
            action = PolicyAction.from_arrow(event["value"])
            # 使用 action.ref_timestamp, action.joints ...

        case "feedback":
            feedback = DriverFeedback.from_arrow(event["value"])
            # 使用 feedback.timestamp, feedback.actuators ...

        case "command":
            command = DriverCommand.from_arrow(event["value"])
            # 使用 command.timestamp, command.actuators ...
```
