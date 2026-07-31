from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import pyarrow as pa


def write_ipc(batch: pa.RecordBatch, path: Path) -> None:
    with path.open("wb") as file:
        with pa.ipc.new_stream(file, batch.schema) as writer:
            writer.write_batch(batch)


def read_ipc(path: Path) -> pa.RecordBatch:
    with path.open("rb") as file:
        return pa.ipc.open_stream(file).read_next_batch()


def assert_schema(batch: pa.RecordBatch, schema: pa.Schema) -> None:
    assert batch.schema == schema
    assert batch.num_rows == 1
    assert "goal_id" not in batch.schema.names
    assert "goal_status" not in batch.schema.names


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", required=True)
    parser.add_argument("--pythonpath", required=True)
    args = parser.parse_args()
    driver = Path(args.driver)

    sys.path.insert(0, args.pythonpath)
    from forge_msgs import (
        GripperCommandFeedback,
        GripperCommandGoal,
        GripperCommandResult,
    )

    string_list = pa.list_(pa.string())
    f64_list = pa.list_(pa.float64())
    point_type = pa.struct(
        [
            pa.field("positions", f64_list, nullable=False),
            pa.field("velocities", f64_list, nullable=False),
            pa.field("accelerations", f64_list, nullable=False),
            pa.field("effort", f64_list, nullable=False),
            pa.field("time_from_start_ns", pa.int64(), nullable=False),
        ]
    )
    trajectory_type = pa.struct(
        [
            pa.field("joint_names", string_list, nullable=False),
            pa.field("points", pa.list_(point_type), nullable=False),
        ]
    )
    tolerance_type = pa.struct(
        [
            pa.field("joint_name", pa.string(), nullable=False),
            pa.field("position", pa.float64(), nullable=True),
            pa.field("velocity", pa.float64(), nullable=True),
            pa.field("acceleration", pa.float64(), nullable=True),
        ]
    )
    pose_type = pa.struct(
        [
            pa.field("x", pa.float64(), nullable=False),
            pa.field("y", pa.float64(), nullable=False),
            pa.field("z", pa.float64(), nullable=False),
            pa.field("qx", pa.float64(), nullable=False),
            pa.field("qy", pa.float64(), nullable=False),
            pa.field("qz", pa.float64(), nullable=False),
            pa.field("qw", pa.float64(), nullable=False),
        ]
    )

    gripper_goal_schema = pa.schema(
        [
            pa.field("position", pa.float64(), nullable=False),
            pa.field("max_velocity", pa.float64(), nullable=True),
            pa.field("max_effort", pa.float64(), nullable=True),
        ]
    )
    gripper_feedback_schema = pa.schema(
        [
            pa.field("elapsed_ns", pa.int64(), nullable=False),
            pa.field("position", pa.float64(), nullable=False),
            pa.field("velocity", pa.float64(), nullable=True),
            pa.field("effort", pa.float64(), nullable=True),
            pa.field("stalled", pa.bool_(), nullable=False),
            pa.field("reached_goal", pa.bool_(), nullable=False),
        ]
    )
    gripper_result_schema = pa.schema(
        [
            pa.field("error_code", pa.string(), nullable=False),
            pa.field("message", pa.string(), nullable=False),
            pa.field("elapsed_ns", pa.int64(), nullable=False),
            pa.field("position", pa.float64(), nullable=True),
            pa.field("velocity", pa.float64(), nullable=True),
            pa.field("effort", pa.float64(), nullable=True),
            pa.field("stalled", pa.bool_(), nullable=False),
            pa.field("reached_goal", pa.bool_(), nullable=False),
        ]
    )

    follow_schema = pa.schema(
        [
            pa.field("trajectory", trajectory_type, nullable=False),
            pa.field("path_tolerance", pa.list_(tolerance_type), nullable=False),
            pa.field("goal_tolerance", pa.list_(tolerance_type), nullable=False),
            pa.field("goal_time_tolerance_ns", pa.int64(), nullable=True),
        ]
    )
    move_joints_schema = pa.schema(
        [
            pa.field("group_name", pa.string(), nullable=False),
            pa.field("joint_names", string_list, nullable=False),
            pa.field("positions", f64_list, nullable=False),
            pa.field("velocity_scale", pa.float64(), nullable=False),
            pa.field("acceleration_scale", pa.float64(), nullable=False),
            pa.field("requested_duration_ns", pa.int64(), nullable=True),
        ]
    )
    move_pose_schema = pa.schema(
        [
            pa.field("group_name", pa.string(), nullable=False),
            pa.field("reference_frame", pa.string(), nullable=False),
            pa.field("target_frame", pa.string(), nullable=False),
            pa.field("target_pose", pose_type, nullable=False),
            pa.field("velocity_scale", pa.float64(), nullable=False),
            pa.field("acceleration_scale", pa.float64(), nullable=False),
            pa.field("requested_duration_ns", pa.int64(), nullable=True),
            pa.field("position_tolerance_m", pa.float64(), nullable=True),
            pa.field("orientation_tolerance_rad", pa.float64(), nullable=True),
        ]
    )

    trajectory = {
        "joint_names": ["joint_1", "joint_2"],
        "points": [
            {
                "positions": [0.0, 0.5],
                "velocities": [],
                "accelerations": [],
                "effort": [],
                "time_from_start_ns": 0,
            },
            {
                "positions": [1.0, 1.5],
                "velocities": [0.1, 0.2],
                "accelerations": [],
                "effort": [],
                "time_from_start_ns": 1000000,
            },
        ],
    }

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        cpp_gripper_goal = root / "cpp_gripper_goal.arrow"
        subprocess.run(
            [driver, "write-gripper-command-goal", cpp_gripper_goal], check=True
        )
        batch = read_ipc(cpp_gripper_goal)
        assert_schema(batch, gripper_goal_schema)
        assert "joint_name" not in batch.schema.names
        assert batch["position"][0].as_py() == 0.08
        assert batch["max_velocity"][0].as_py() is None
        assert batch["max_effort"][0].as_py() == 12.0
        assert GripperCommandGoal.from_arrow(
            cpp_gripper_goal.read_bytes()
        ) == GripperCommandGoal(
            position=0.08,
            max_velocity=None,
            max_effort=12.0,
        )

        py_gripper_goal = root / "py_gripper_goal.arrow"
        write_ipc(
            GripperCommandGoal(
                position=0.04,
                max_velocity=0.1,
                max_effort=None,
            ).to_arrow(),
            py_gripper_goal,
        )
        output = subprocess.check_output(
            [driver, "read-gripper-command-goal", py_gripper_goal], text=True
        ).strip()
        assert output == "0.04 0.1 null"

        cpp_gripper_feedback = root / "cpp_gripper_feedback.arrow"
        subprocess.run(
            [driver, "write-gripper-command-feedback", cpp_gripper_feedback], check=True
        )
        batch = read_ipc(cpp_gripper_feedback)
        assert_schema(batch, gripper_feedback_schema)
        assert batch["velocity"][0].as_py() is None
        assert batch["effort"][0].as_py() == -0.25
        assert batch["stalled"][0].as_py() is False
        assert GripperCommandFeedback.from_arrow(
            cpp_gripper_feedback.read_bytes()
        ) == GripperCommandFeedback(
            elapsed_ns=15,
            position=1.2,
            velocity=None,
            effort=-0.25,
            stalled=False,
            reached_goal=False,
        )

        py_gripper_feedback = root / "py_gripper_feedback.arrow"
        write_ipc(
            GripperCommandFeedback(
                elapsed_ns=25,
                position=0.5,
                velocity=-0.1,
                effort=None,
                stalled=True,
                reached_goal=False,
            ).to_arrow(),
            py_gripper_feedback,
        )
        output = subprocess.check_output(
            [driver, "read-gripper-command-feedback", py_gripper_feedback], text=True
        ).strip()
        assert output == "25 0.5 -0.1 null 1 0"

        cpp_gripper_result = root / "cpp_gripper_result.arrow"
        subprocess.run(
            [driver, "write-gripper-command-result", cpp_gripper_result], check=True
        )
        batch = read_ipc(cpp_gripper_result)
        assert_schema(batch, gripper_result_schema)
        assert batch["error_code"][0].as_py() == "NO_FRESH_ROBOT_STATE"
        assert batch["position"][0].as_py() is None
        assert batch["reached_goal"][0].as_py() is False
        assert GripperCommandResult.from_arrow(
            cpp_gripper_result.read_bytes()
        ) == GripperCommandResult(
            error_code="NO_FRESH_ROBOT_STATE",
            message="state_unavailable",
            elapsed_ns=0,
            position=None,
            velocity=None,
            effort=None,
            stalled=False,
            reached_goal=False,
        )

        py_gripper_result = root / "py_gripper_result.arrow"
        write_ipc(
            GripperCommandResult(
                error_code="SUCCESS",
                message="done",
                elapsed_ns=20,
                position=0.0,
                velocity=0.0,
                effort=None,
                stalled=False,
                reached_goal=True,
            ).to_arrow(),
            py_gripper_result,
        )
        output = subprocess.check_output(
            [driver, "read-gripper-command-result", py_gripper_result], text=True
        ).strip()
        assert output == "SUCCESS done 20 0 0 null 0 1"

        cpp_follow = root / "cpp_follow.arrow"
        subprocess.run(
            [driver, "write-follow-joint-trajectory-goal", cpp_follow], check=True
        )
        batch = read_ipc(cpp_follow)
        assert_schema(batch, follow_schema)
        assert batch["trajectory"][0].as_py()["joint_names"] == ["joint_1", "joint_2"]
        assert len(batch["trajectory"][0].as_py()["points"]) == 2
        assert batch["path_tolerance"][0].as_py()[0]["position"] == 0.05

        py_follow = root / "py_follow.arrow"
        write_ipc(
            pa.RecordBatch.from_arrays(
                [
                    pa.array([trajectory], type=trajectory_type),
                    pa.array(
                        [
                            [
                                {
                                    "joint_name": "joint_2",
                                    "position": None,
                                    "velocity": 0.1,
                                    "acceleration": None,
                                }
                            ]
                        ],
                        type=pa.list_(tolerance_type),
                    ),
                    pa.array([[]], type=pa.list_(tolerance_type)),
                    pa.array([None], type=pa.int64()),
                ],
                schema=follow_schema,
            ),
            py_follow,
        )
        output = subprocess.check_output(
            [driver, "read-follow-joint-trajectory-goal", py_follow], text=True
        ).strip()
        assert output == "2 2 1 null"

        cpp_move_joints = root / "cpp_move_joints.arrow"
        subprocess.run([driver, "write-move-joints-goal", cpp_move_joints], check=True)
        batch = read_ipc(cpp_move_joints)
        assert_schema(batch, move_joints_schema)
        assert batch["positions"][0].as_py() == [1.0, 1.5]
        assert batch["requested_duration_ns"][0].as_py() is None

        py_move_joints = root / "py_move_joints.arrow"
        write_ipc(
            pa.RecordBatch.from_arrays(
                [
                    pa.array(["manipulator"], type=pa.string()),
                    pa.array([["a", "b"]], type=string_list),
                    pa.array([[0.25, -0.5]], type=f64_list),
                    pa.array([0.8], type=pa.float64()),
                    pa.array([0.7], type=pa.float64()),
                    pa.array([1500000], type=pa.int64()),
                ],
                schema=move_joints_schema,
            ),
            py_move_joints,
        )
        output = subprocess.check_output(
            [driver, "read-move-joints-goal", py_move_joints], text=True
        ).strip()
        assert output == "manipulator 2 0.25 1500000"

        cpp_move_pose = root / "cpp_move_pose.arrow"
        subprocess.run([driver, "write-move-pose-goal", cpp_move_pose], check=True)
        batch = read_ipc(cpp_move_pose)
        assert_schema(batch, move_pose_schema)
        assert batch["target_pose"][0].as_py()["x"] == 0.4
        assert batch["requested_duration_ns"][0].as_py() is None
        assert batch["orientation_tolerance_rad"][0].as_py() is None

        py_move_pose = root / "py_move_pose.arrow"
        write_ipc(
            pa.RecordBatch.from_arrays(
                [
                    pa.array(["manipulator"], type=pa.string()),
                    pa.array(["base"], type=pa.string()),
                    pa.array(["tcp"], type=pa.string()),
                    pa.array(
                        [
                            {
                                "x": 0.6,
                                "y": 0.1,
                                "z": 0.2,
                                "qx": 0.0,
                                "qy": 0.0,
                                "qz": 0.0,
                                "qw": 1.0,
                            }
                        ],
                        type=pose_type,
                    ),
                    pa.array([0.8], type=pa.float64()),
                    pa.array([0.7], type=pa.float64()),
                    pa.array([None], type=pa.int64()),
                    pa.array([0.02], type=pa.float64()),
                    pa.array([None], type=pa.float64()),
                ],
                schema=move_pose_schema,
            ),
            py_move_pose,
        )
        output = subprocess.check_output(
            [driver, "read-move-pose-goal", py_move_pose], text=True
        ).strip()
        assert output == "manipulator base tcp 0.6 null 0.02"

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
