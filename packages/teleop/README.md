# forge-teleop

`forge-teleop` 是通用遥操作工具包，面向 raw-policy 流程中各构型 teleop policy 复用。

它主要做两件事：

- 处理通用按键语义：短按激活、长按复位、解除遥操。
- 过滤 policy 输出动作：硬安全兜底 + 可选软运动整形，避免把危险指令发给机器人。

## 适用数据流

```text
VR / 手柄输入
  -> 构型相关 teleop policy
  -> forge_teleop 安全过滤
  -> task_robot / robot driver
```

构型相关 teleop policy 仍然负责 IK、坐标系映射、workspace 等机器人相关逻辑。`forge-teleop` 只处理可以通用复用的遥操按键和输出安全策略。

## 按键控制

默认按键行为与 `vr_device` 保持一致：

- 左手 `X` / 右手 `A`：激活键
- 左手 `Y` / 右手 `B`：解除键
- 激活键短按：松开时触发激活
- 激活键长按：超过 `home.hold_seconds` 后触发复位/home
- 解除键按下：立即解除遥操

## 输出动作类型

`forge-teleop` 支持两类遥操作输出：

- `JointCommand`：关节空间 action，适合 low-level / gravity compensation 等逐关节控制。
- `HighLevelTeleopAction`：末端位姿 action，适合机器人 driver 调用 high-level 内部 IK / 轨迹接口。

`HighLevelTeleopAction` 不应被塞进 `JointCommand.position`。它有独立的 Arrow schema，字段如下：

| 字段 | 作用 |
| --- | --- |
| `action_type` | 固定为 `high_level_teleop`，用于和 `JointCommand` 区分 |
| `robot_id` | 目标机器人，默认 `robot_0` |
| `source` | 来源，如 `teleop` / `home` |
| `waist_pitch` / `waist_yaw` | high-level 腰部目标 |
| `left_position` / `right_position` | 左右手末端在机器人 torso 坐标系下的位置 `[x, y, z]` |
| `left_quaternion` / `right_quaternion` | 左右手末端姿态 `[qx, qy, qz, qw]` |
| `left_gripper` / `right_gripper` | 夹爪开合目标，单位由接入方约定；推荐使用米制开口宽度 |

代码示例：

```python
from forge_teleop import HighLevelArmTarget, HighLevelTeleopAction

action = HighLevelTeleopAction(
    waist_pitch=0.1,
    waist_yaw=0.0,
    left_arm=HighLevelArmTarget(
        position=[0.25, 0.18, 0.05],
        quaternion=[0.0, 0.0, 0.0, 1.0],
    ),
    right_arm=HighLevelArmTarget(
        position=[0.25, -0.18, 0.05],
        quaternion=[0.0, 0.0, 0.0, 1.0],
    ),
    left_gripper=0.08,
    right_gripper=0.08,
)
node.send_output("action", action.to_arrow())
```

## 输出安全分层

安全控制分为两层：

```text
raw JointCommand
  -> 硬安全（Hard Safety）
  -> 软运动整形（Motion Shaper）
  -> safe JointCommand
```

对于 `HighLevelTeleopAction`，安全过滤对象从关节变为末端位姿：

```text
raw HighLevelTeleopAction
  -> 输入新鲜度 / 有限值 / 四元数归一化
  -> workspace 限制
  -> 末端 position / orientation 单 tick 跳变限制
  -> safe HighLevelTeleopAction
```

### 硬安全（建议始终保留）

这些参数主要保护真机底线，一般不建议关闭：

| 参数 | 作用 |
| --- | --- |
| `enabled` | 总开关 |
| `feedback_timeout_seconds` | `joint_state` 超时则 hold |
| `teleop_timeout_seconds` | `teleop_observation` 超时则 hold |
| `max_vr_position_jump_m` | VR 位置大跳变检测 |
| `max_vr_angular_jump_rad` | VR 姿态大跳变检测 |
| `hold_last_on_failure` | 异常时保持上次安全命令 |
| `fault_after_failures` | 连续失败进入 fault |
| `joint_limits.*.min_position` / `max_position` | 关节硬限位 |

high-level 末端位姿安全参数：

| 参数 | 作用 |
| --- | --- |
| `high_level_safety.enabled` | 是否启用 high-level action 安全过滤 |
| `high_level_safety.feedback_timeout_seconds` | `joint_state` 超时则 hold |
| `high_level_safety.teleop_timeout_seconds` | `teleop_observation` 超时则 hold |
| `high_level_safety.enable_pose_step_limit` | 是否限制末端位姿单 tick 跳变 |
| `high_level_safety.max_eef_position_delta_m` | 末端位置单 tick 最大变化 |
| `high_level_safety.max_eef_angular_delta_rad` | 末端姿态单 tick 最大角度变化 |
| `high_level_safety.left_arm.min_position/max_position` | 左手末端 workspace 限制 |
| `high_level_safety.right_arm.min_position/max_position` | 右手末端 workspace 限制 |

### Home / 回零参数

长按激活键只负责产生 `home` 事件。具体机器人要怎么回零，由接入方决定。通用配置提供这些字段：

| 参数 | 作用 |
| --- | --- |
| `home.enabled` | 是否启用长按 home |
| `home.hold_seconds` | 按住激活键多久触发 home |
| `home.deactivate_teleop` | 触发 home 后是否退出遥操 |
| `home.move_seconds` | 建议的回零插值时间 |
| `home.targets` | 可选的命名目标，接入方可按 robot/config 读取 |

例如 `zerith_teleop` 会默认让腰部和双臂回到 `0`，夹爪打开；如果配置了 `home.targets.robot_0`，则用配置值覆盖默认目标。

### 软运动整形（影响手感和卡顿）

这些参数主要影响遥操作是否跟手，可按场景调节：

| 参数 | 作用 |
| --- | --- |
| `enable_soft_limits` | 是否启用软限速/平滑 |
| `enable_velocity_limit` | 按最大关节速度限制单 tick 变化 |
| `enable_step_limit` | 按固定单 tick 步长限制 |
| `enable_low_pass` | 是否对目标做低通平滑 |
| `max_joint_velocity_rad_s` | 全局最大关节速度 |
| `max_joint_delta_per_tick` | 全局单 tick 最大位移 |
| `low_pass_alpha` | 低通系数，越小越平滑但越拖滞 |
| `joint_limits.*.max_velocity_rad_s` | 单关节速度覆盖 |
| `joint_limits.*.max_delta_per_tick` | 单关节步长覆盖 |

经验上，**同时开启 velocity + step + low_pass 很容易卡顿**。推荐优先只保留一层软限制。

## 安全模式

通过 `safety_mode` 快速选择预设：

| 模式 | 适用场景 | 默认行为 |
| --- | --- | --- |
| `strict` | 真机初次测试 | 速度 + 步长 + 低通都开启，限速保守 |
| `balanced` | 日常遥操推荐 | 仅速度限制，关闭 step 和低通 |
| `responsive` | 追求跟手 | 仅拦截异常大跳变，不做速度/低通限制 |

示例：

```yaml
teleop_safety:
  enabled: true
  safety_mode: balanced
```

如需覆盖预设，可显式写开关和数值，例如：

```yaml
teleop_safety:
  safety_mode: balanced
  enable_velocity_limit: true
  enable_step_limit: false
  enable_low_pass: false
  max_joint_velocity_rad_s: 3.0
```

## 推荐调参顺序

如果遥操作感觉卡顿，建议按这个顺序调整：

1. 先切到 `balanced` 或 `responsive`
2. 关闭 `enable_low_pass`
3. 提高 `max_joint_velocity_rad_s`
4. 关闭 `enable_step_limit`
5. 最后再考虑 `enable_soft_limits: false`（硬安全仍保留）

## 配置示例

```yaml
activation_buttons:
  left: X
  right: A

deactivate_buttons:
  left: Y
  right: B

home:
  enabled: true
  hold_seconds: 1.0
  deactivate_teleop: true
  move_seconds: 2.0
  targets:
    robot_0:
      left_arm_4: -0.5
      right_arm_4: -0.5

teleop_safety:
  enabled: true
  safety_mode: balanced
  tick_seconds: 0.02
  feedback_timeout_seconds: 0.2
  teleop_timeout_seconds: 0.2
  hold_last_on_failure: true
  fault_after_failures: 10
  joint_limits:
    waist_down:
      max_velocity_rad_s: 1.0
    left_arm_1:
      max_velocity_rad_s: 3.0

high_level_safety:
  enabled: true
  enable_pose_step_limit: true
  max_eef_position_delta_m: 0.08
  max_eef_angular_delta_rad: 0.5
  left_arm:
    min_position: [-0.4, -0.2, -0.4]
    max_position: [0.8, 0.6, 0.8]
  right_arm:
    min_position: [-0.4, -0.6, -0.4]
    max_position: [0.8, 0.2, 0.8]
```

## 代码示例

```python
import time

from forge_teleop import TeleopSafetyConfig, TeleopSafetyController, TeleopSafetyContext

safety = TeleopSafetyController(TeleopSafetyConfig.from_dict({
    "safety_mode": "balanced",
}))
safety.seed(initial_command)

result = safety.filter_joint_command(
    raw_command,
    current_state,
    context=TeleopSafetyContext(now=time.monotonic(), ...),
)
```

## 设计边界

`forge-teleop` 不做机器人几何相关判断，例如 IK、workspace、自碰撞、末端高度限制等。这些逻辑应留在具体构型的 teleop policy 中。

推荐做法是：具体 policy 先生成 raw action，然后统一交给 `forge-teleop` 做最后一道通用安全过滤。
