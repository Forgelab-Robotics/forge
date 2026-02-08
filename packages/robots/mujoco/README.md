# forge_robots_mujoco

MuJoCo robot and driver for the Forge robotics framework.

## Architecture

This package provides:

- **MuJoCoDriver**: Low-level interface to MuJoCo model/data
- **MuJoCoRobot**: Robot + Driver merged, for simulator nodes (includes reset logic)

- **No mujoco dependency** - this is a pure library
- MuJoCo dependency is maintained by the caller (e.g., simulator node)

## Units

All values use unified units:
- **Angles**: radians
- **Distances**: meters
- **Velocities**: radians/s (for revolute joints) or meters/s (for prismatic joints)

## Usage

### MuJoCoRobot (simulator node, scene robot)

```python
import mujoco
from forge_robots_mujoco import MuJoCoRobot

model = mujoco.MjModel.from_xml_path("scene.xml")
data = mujoco.MjData(model)

joints = [...]
actuators = [...]
robot = MuJoCoRobot(
    model=model,
    data=data,
    joints=joints,
    actuators=actuators,
    prefix="robot1/",
)

robot.reset()  # Reset to model qpos0, zero velocity
state = robot.get_state(timestamp=0.0)  # RobotState (msgs format)
robot.set_actuators(action)  # RobotAction (msgs format)
```

### MuJoCoDriver with PiperRobot (Piper in simulation)

```python
import mujoco
from forge_robots_mujoco import MuJoCoDriver
from forge_robots_piper import PiperRobot

model = mujoco.MjModel.from_xml_path("scene.xml")
data = mujoco.MjData(model)

joints = [...]
actuators = [...]
driver = MuJoCoDriver(model=model, data=data, joints=joints, actuators=actuators, prefix="robot1/")

robot = PiperRobot(driver=driver)
state = robot.get_state(timestamp=0.0)  # RobotState
robot.set_actuators(action)  # RobotAction
```

### MuJoCoDriver standalone (low-level)

```python
import mujoco
from forge_robots_mujoco import MuJoCoDriver

driver = MuJoCoDriver(model=model, data=data, joints=joints, actuators=actuators, prefix="robot1/")

driver.set_actuators(action)  # RobotAction
state = driver.get_state(timestamp=0.0)  # RobotState
```
