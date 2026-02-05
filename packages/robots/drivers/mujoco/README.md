# forge_robots_drivers_mujoco

MuJoCo simulator driver for the Forge robotics framework.

## Units

All values use unified units:
- **Angles**: radians
- **Distances**: meters
- **Velocities**: radians/s (for revolute joints) or meters/s (for prismatic joints)

MuJoCo natively uses radians for angles and meters for distances, so no conversion is needed.
The driver directly uses MuJoCo's native units, which match the unified unit system.

## Usage

```python
from forge_robots_drivers_mujoco import MuJoCoDriver
from forge_robots_piper import PiperRobot

# Create MuJoCo environment (DmControlEnv-like interface)
env = create_mujoco_env(...)

# Create driver with joints and actuators
joints = [...]
actuators = [...]
driver = MuJoCoDriver(env=env, joints=joints, actuators=actuators, prefix="robot1/")

# Use with robot model
robot = PiperRobot(driver=driver)

# All values are in unified units (radians, meters)
positions = robot.get_joint_positions()  # Returns radians/meters
robot.set_actuators([...])  # Input in radians/meters
```
