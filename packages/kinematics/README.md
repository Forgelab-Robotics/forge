# forge-kinematics

Optional PyBullet URDF kinematics **library** for Forge capabilities.

## Boundary

| In scope | Out of scope |
|----------|----------------|
| Forward kinematics (`solve_fk`) | Dora capability / skill nodes |
| Inverse kinematics (`solve_ik`) | Real-robot execution & proprio convergence |
| Generic URDF loading (meshes stripped) | Grasp verify, timeouts, joint streaming |

Robot-specific motion runtime stays in capability packages such as
`pybullet_ik_motion`. Those packages should depend on `forge-kinematics` for
solvers and keep Dora / execution semantics locally.

This package is **not** part of the default `forge` meta dependency set (so
installing `forge` does not pull PyBullet). Depend on `forge-kinematics`
explicitly where needed.

## Install

From the `forge` workspace:

```bash
uv sync --package forge-kinematics
```

Or path-depend from a capability repo:

```toml
dependencies = ["forge-kinematics"]

[tool.uv.sources]
forge-kinematics = { path = "../../forge/packages/kinematics", editable = true }
```

## Usage

```python
from forge_kinematics import PyBulletKinematics, PyBulletIKPlanner

fk = PyBulletKinematics(urdf_path, controlled_joint_names=["joint1", ...], ee_link_name="link6")
T = fk.solve_fk(joints)

ik = PyBulletIKPlanner(urdf_path, controlled_joint_names=["joint1", ...], ee_link_name="link6")
q = ik.solve_ik(target_pos, target_rpy, current_joints)
```
