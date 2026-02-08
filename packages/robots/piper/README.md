# forge_robots_piper

Piper robot and driver for the Forge robotics framework.

## Units

All values use unified units:
- **Angles**: radians
- **Distances**: meters
- **Velocities**: radians/s (for revolute joints) or meters/s (for prismatic joints)

The driver automatically converts between hardware-specific units and unified units:
- Hardware joint angles: degrees × 1000 → radians
- Hardware gripper: millimeters × 1000 → meters

## Usage

```python
from forge_robots_piper import PiperDriver, PiperRobot

# Create driver (uses default joints/actuators if not specified)
driver = PiperDriver(port="can0", is_follower=True)

# Use with robot model
robot = PiperRobot(driver=driver)

# Communication uses forge_msgs format (RobotState, RobotAction)
state = robot.get_state(timestamp=0.0)  # RobotState
robot.set_actuators(action)  # RobotAction
```
