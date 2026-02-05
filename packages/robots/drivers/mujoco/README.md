# forge_robots_drivers_mujoco

MuJoCo simulator driver for the Forge robotics framework.

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
```
