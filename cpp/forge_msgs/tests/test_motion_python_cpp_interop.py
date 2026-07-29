from __future__ import annotations

import argparse
import subprocess
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
    args = parser.parse_args()
    driver = Path(args.driver)

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

        cpp_follow = root / "cpp_follow.arrow"
        subprocess.run([driver, "write-follow-joint-trajectory-goal", cpp_follow], check=True)
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
                        [[{"joint_name": "joint_2", "position": None,
                           "velocity": 0.1, "acceleration": None}]],
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
                        [{"x": 0.6, "y": 0.1, "z": 0.2, "qx": 0.0, "qy": 0.0,
                          "qz": 0.0, "qw": 1.0}],
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
