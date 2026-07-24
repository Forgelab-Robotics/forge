"""PyBullet URDF forward kinematics."""

from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
import pybullet as p
import pybullet_data


class PyBulletKinematics:
    """Load a kinematics-only URDF and solve forward kinematics."""

    def __init__(self, urdf_path, controlled_joint_names=None, ee_link_name=None):
        self.client_id = p.connect(p.DIRECT)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())

        if not os.path.exists(urdf_path):
            raise FileNotFoundError(f"URDF model not found: {urdf_path}")

        # Strip visual/collision so missing meshes do not block FK.
        tree = ET.parse(urdf_path)
        root = tree.getroot()
        for link in root.findall("link"):
            for vis in link.findall("visual"):
                link.remove(vis)
            for col in link.findall("collision"):
                link.remove(col)

        fd, temp_urdf_path = tempfile.mkstemp(suffix=".urdf")
        with os.fdopen(fd, "wb") as f:
            tree.write(f)

        try:
            self.robot_id = p.loadURDF(temp_urdf_path, [0, 0, 0], useFixedBase=True)
        finally:
            os.remove(temp_urdf_path)

        self.joint_indices = []
        self.ll = []
        self.ul = []
        self.jr = []
        self.rp = []
        revolute_by_name = {}
        for i in range(p.getNumJoints(self.robot_id)):
            info = p.getJointInfo(self.robot_id, i)
            if info[2] == p.JOINT_REVOLUTE:
                name = info[1].decode("utf-8")
                lower = info[8]
                upper = info[9]
                if lower >= upper:
                    lower, upper = -3.14, 3.14
                revolute_by_name[name] = (i, lower, upper)

        if controlled_joint_names:
            chosen = []
            missing = []
            for joint_name in controlled_joint_names:
                if joint_name not in revolute_by_name:
                    missing.append(joint_name)
                    continue
                chosen.append((joint_name, *revolute_by_name[joint_name]))
            if missing:
                raise ValueError(f"URDF missing controlled joints: {missing}")
        else:
            chosen = []
            for i in range(p.getNumJoints(self.robot_id)):
                info = p.getJointInfo(self.robot_id, i)
                if info[2] == p.JOINT_REVOLUTE:
                    name = info[1].decode("utf-8")
                    idx, lower, upper = revolute_by_name[name]
                    chosen.append((name, idx, lower, upper))
            # Legacy default: first 6 revolute joints.
            chosen = chosen[:6]

        self.joint_names = []
        for name, idx, lower, upper in chosen:
            self.joint_names.append(name)
            self.joint_indices.append(idx)
            self.ll.append(lower)
            self.ul.append(upper)
            self.jr.append(upper - lower)
            self.rp.append((lower + upper) / 2.0)

        if len(self.joint_indices) < 1:
            raise ValueError("URDF parse failed: no controlled revolute joints found.")

        if ee_link_name:
            self.ee_link_idx = None
            for i in range(p.getNumJoints(self.robot_id)):
                info = p.getJointInfo(self.robot_id, i)
                link_name = info[12].decode("utf-8")
                if link_name == ee_link_name:
                    self.ee_link_idx = i
                    break
            if self.ee_link_idx is None:
                raise ValueError(f"URDF missing end-effector link: {ee_link_name}")
        else:
            self.ee_link_idx = self.joint_indices[-1]

    def solve_fk(self, current_joints):
        """Return 4x4 base<-ee transform for the given arm joints."""
        n = min(len(current_joints), len(self.joint_indices))
        for i, idx in enumerate(self.joint_indices[:n]):
            p.resetJointState(self.robot_id, idx, current_joints[i])

        info = p.getLinkState(self.robot_id, self.ee_link_idx)
        pos = info[4]
        orn = info[5]

        R = p.getMatrixFromQuaternion(orn)
        R = np.array(R).reshape(3, 3)
        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = pos
        return T

    def destroy(self):
        try:
            p.disconnect(self.client_id)
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.destroy()
        return False
