# forge_robots_drivers_mujoco

MuJoCo simulator driver for the Forge robotics framework.

## Architecture

This package provides `MuJoCoDriver` - a local/in-process driver that interfaces directly with MuJoCo model/data.

- **No mujoco dependency** - this is a pure library
- MuJoCo dependency is maintained by the caller (e.g., simulator node)
- Used by MuJoCo simulator nodes in `forge_nodes`
- Can also be used for local simulation scenarios

## Units

All values use unified units:
- **Angles**: radians
- **Distances**: meters
- **Velocities**: radians/s (for revolute joints) or meters/s (for prismatic joints)

MuJoCo natively uses radians for angles and meters for distances, so no conversion is needed.
The driver directly uses MuJoCo's native units, which match the unified unit system.

## Usage

### In Simulator Node (forge_nodes)

```python
import mujoco
from forge_robots_drivers_mujoco import MuJoCoDriver

# Load MuJoCo model and data
model = mujoco.MjModel.from_xml_path("scene.xml")
data = mujoco.MjData(model)

# Create driver with joints and actuators
joints = [...]
actuators = [...]
driver = MuJoCoDriver(model=model, data=data, joints=joints, actuators=actuators, prefix="robot1/")

# Use driver to set actuators and get joint positions
driver.set_actuators([...])
positions = driver.get_joint_positions()
```

### In Local Simulation

```python
import mujoco
from forge_robots_drivers_mujoco import MuJoCoDriver
from forge_robots_piper import PiperRobot

# Load MuJoCo model and data
model = mujoco.MjModel.from_xml_path("scene.xml")
data = mujoco.MjData(model)

# Create driver
driver = MuJoCoDriver(model=model, data=data, joints=joints, actuators=actuators)

# Use with robot model
robot = PiperRobot(driver=driver)

# All values are in unified units (radians, meters)
positions = robot.get_joint_positions()  # Returns radians/meters
robot.set_actuators([...])  # Input in radians/meters
```
