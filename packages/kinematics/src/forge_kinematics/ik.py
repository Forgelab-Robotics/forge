"""PyBullet URDF inverse kinematics."""

from __future__ import annotations

import numpy as np
import pybullet as p

from forge_kinematics.fk import PyBulletKinematics


class PyBulletIKPlanner(PyBulletKinematics):
    """URDF inverse kinematics on top of :class:`PyBulletKinematics`."""

    def solve_ik(self, target_pos, target_rpy, current_joints):
        """Solve IK for a Cartesian pose, seeded by the current joint state."""
        n = min(len(current_joints), len(self.joint_indices))
        for i, idx in enumerate(self.joint_indices[:n]):
            p.resetJointState(self.robot_id, idx, current_joints[i])

        rest_poses = list(self.rp)
        for i in range(n):
            rest_poses[i] = float(np.clip(current_joints[i], self.ll[i], self.ul[i]))

        target_orn = p.getQuaternionFromEuler(target_rpy)

        # Null-space IK with joint limits. restPoses use the current joints so
        # consecutive pose steps keep wrist/elbow configuration stable.
        ik_solution = p.calculateInverseKinematics(
            self.robot_id,
            self.ee_link_idx,
            target_pos,
            target_orn,
            lowerLimits=self.ll,
            upperLimits=self.ul,
            jointRanges=self.jr,
            restPoses=rest_poses,
            maxNumIterations=500,
            residualThreshold=1e-5,
        )
        return np.array(ik_solution[: len(self.joint_indices)])
