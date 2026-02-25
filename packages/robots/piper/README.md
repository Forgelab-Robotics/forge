# forge_robots_piper

Piper robot and driver for the Forge robotics framework.

## Units

All values use unified units:
- **Angles**: radians
- **Distances**: meters
- **Velocities**: radians/s (for revolute joints) or millimeters/s (for prismatic joints)

The driver automatically converts between hardware-specific units and unified units:
- Hardware joint angles: degrees × 1000 → radians
- Hardware gripper: millimeters × 1000 → meters

## Usage

```python
from forge_robots_piper import PiperRobot

robot = PiperRobot(port="can0")

# RobotState / RobotAction (forge_msgs)
state = robot.get_state(timestamp=0.0)
robot.set_actuators(action)
```

PiperDriver 作为内部类，需要直接使用驱动时可单独导入：

```python
from forge_robots_piper import PiperDriver
driver = PiperDriver(port="can0")  # 低层硬件接口
```
