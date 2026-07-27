"""Smoke tests for forge-kinematics FK/IK on a tiny planar URDF."""

from __future__ import annotations

import textwrap
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pybullet")

from forge_kinematics import PyBulletIKPlanner, PyBulletKinematics


MINIMAL_URDF = textwrap.dedent(
    """\
    <?xml version="1.0"?>
    <robot name="two_link">
      <link name="base"/>
      <link name="link1"/>
      <link name="link2"/>
      <joint name="joint1" type="revolute">
        <parent link="base"/>
        <child link="link1"/>
        <origin xyz="0 0 0" rpy="0 0 0"/>
        <axis xyz="0 0 1"/>
        <limit lower="-3.14" upper="3.14" effort="1" velocity="1"/>
      </joint>
      <joint name="joint2" type="revolute">
        <parent link="link1"/>
        <child link="link2"/>
        <origin xyz="0.2 0 0" rpy="0 0 0"/>
        <axis xyz="0 0 1"/>
        <limit lower="-3.14" upper="3.14" effort="1" velocity="1"/>
      </joint>
    </robot>
    """
)


@pytest.fixture()
def urdf_path(tmp_path: Path) -> Path:
    path = tmp_path / "two_link.urdf"
    path.write_text(MINIMAL_URDF, encoding="utf-8")
    return path


def test_solve_fk_returns_homogeneous_transform(urdf_path: Path) -> None:
    with PyBulletKinematics(
        str(urdf_path),
        controlled_joint_names=["joint1", "joint2"],
        ee_link_name="link2",
    ) as kin:
        T = kin.solve_fk([0.0, 0.0])
    assert T.shape == (4, 4)
    assert np.isclose(T[3, 3], 1.0)
    assert np.allclose(T[3, :3], 0.0)


def test_solve_ik_returns_controlled_dof(urdf_path: Path) -> None:
    with PyBulletIKPlanner(
        str(urdf_path),
        controlled_joint_names=["joint1", "joint2"],
        ee_link_name="link2",
    ) as kin:
        seed = np.array([0.1, -0.2], dtype=float)
        T = kin.solve_fk(seed)
        q = kin.solve_ik(T[:3, 3], [0.0, 0.0, 0.0], seed)
    assert q.shape == (2,)
