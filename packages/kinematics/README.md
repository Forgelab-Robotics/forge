# forge-kinematics

Deterministic URDF forward kinematics, geometric Jacobians, and damped-least-squares inverse kinematics backed by [Pinocchio](https://stack-of-tasks.github.io/pinocchio/).

## Scope

The package is a model and solver library. It does not depend on ROS, Dora, robot drivers, teleoperation policies, collision checking, or motion execution. The DLS solver uses Pinocchio's numerical API and NumPy directly; it does not require CasADi or Conda.

- A `RobotModel` owns the immutable full URDF model, while `RobotState` carries a complete named-joint configuration.
- A `KinematicGroup` declares ordered active joints, a base frame, one or more tip frames, and optional permanently locked joints.
- `KinematicsContext` owns mutable Pinocchio evaluation storage. Contexts are per-thread; each IK solve creates and reuses one private context.
- `IKRequest` groups the seed, targets, full context state, dynamic fixed joints, options, and an optional state-validity callback.
- `KinematicsSolver` is the backend-independent solver protocol implemented by `PinocchioDlsSolver`.
- Public joint vectors always follow the caller-declared group order, independently of Pinocchio's internal `q`/`v` layout.
- FK returns `T_base_tip`; Jacobians are expressed in base-aligned coordinates with linear rows followed by angular rows.
- `PinocchioDlsSolver` performs one deterministic seed-based solve. It does not perform random restarts or silently accept approximate results.

Version 1 supports independent single-DoF revolute, continuous, and prismatic active joints. Floating, planar, mimic, collision-aware, and search IK are intentionally out of scope.

## Install

From the Forge workspace:

```bash
uv sync --package forge-kinematics
```

The top-level `forge` meta package does not depend on `forge-kinematics`, so downstream projects opt into the Pinocchio dependency explicitly.

## Distribution and platform support

Build both the wheel and source distribution from the Forge workspace root:

```bash
uv build --package forge-kinematics
```

The package uses the `pin` wheels published on PyPI. Those wheels are currently validated for Linux with glibc and for macOS; Windows and Linux with musl are not guaranteed. Neither Conda nor CasADi is required.

## Example

```python
import numpy as np

from forge_kinematics import (
    DlsConfig,
    IKOptions,
    IKRequest,
    PinocchioDlsSolver,
    PoseTarget,
    RobotModel,
)

model = RobotModel.from_urdf("robot.urdf")
arm = model.create_group(
    name="arm",
    joint_names=("joint1", "joint2", "joint3"),
    base_frame="base_link",
    tip_frames=("tool0",),
)

state = model.create_state()
context = model.create_context()
seed = arm.neutral_positions
current_pose = arm.forward(seed, state=state, context=context)
current_jacobian = arm.jacobian(seed, state=state, context=context)

target_pose = current_pose.copy()
target_pose[0, 3] += 0.05
target = PoseTarget(
    tip_frame="tool0",
    reference_frame="base_link",
    pose=target_pose,
    # xyz + rotation-vector axes; zero disables one task-space axis.
    task_weights=(1.0, 1.0, 1.0, 1.0, 0.0, 1.0),
    orientation_weight=0.1,
)
options = IKOptions(
    timeout_s=0.05,
    max_solution_joint_displacement=0.5,
)
dls_config = DlsConfig(
    max_iteration_joint_step=0.1,
    singularity_threshold=0.05,
    singularity_damping=0.2,
    joint_limit_avoidance_weight=0.05,
)
request = IKRequest(
    seed=seed,
    targets=(target,),
    options=options,
    context_state=state,
    # Dynamic hard constraints are applied per solve, without rebuilding the group.
    fixed_joint_positions={"joint1": 0.0},
    # Collision or application constraints remain outside the solver.
    state_validator=lambda candidate: True,
)
result = PinocchioDlsSolver(arm, config=dls_config).solve(request)
if not result.success:
    raise RuntimeError(result.message)
commanded_positions = result.solution
```

`task_weights` are per-axis and are multiplied by the overall position and orientation weights. This supports position-only, orientation-only, or partially constrained poses. Backend-independent request controls such as timeout, tolerances, approximate-result policy, and total displacement live in `IKOptions`. DLS algorithm controls such as damping, iteration step, singularity handling, and null-space avoidance live in the solver's immutable `DlsConfig`. `max_iteration_joint_step` limits each numerical update, while `max_solution_joint_displacement` independently limits each joint's total tangent displacement from the effective seed. The solver reports adaptive damping, singularity, joint-limit margin, and the null-space avoidance activation coefficient. Limit avoidance never moves an already satisfied target away from its seed.

Failed solves return no `solution`; callers must explicitly opt into `approximate_solution` through `IKOptions`. Dynamic `fixed_joint_positions` remain present in the caller-ordered result but are removed from the IK Jacobian for that solve. A converged candidate rejected by the validator returns `REJECTED_BY_VALIDATOR` and is never exposed as a solution; rejected approximate candidates are omitted while preserving the solve's original failure status.

Every target names its `reference_frame`, which must equal the group's base frame; frame transforms stay in the adapter layer. `IKResult.raw_*` errors describe the complete pose difference, while `active_*` errors include only enabled task axes and determine convergence. `timeout_s` is a soft deadline: native Pinocchio or linear-algebra calls already in progress cannot be preempted.
