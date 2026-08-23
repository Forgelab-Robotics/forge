from __future__ import annotations

import argparse
import importlib.util
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _to_ipc_file(batch, path: Path) -> None:
    import pyarrow as pa

    with path.open("wb") as file:
        with pa.ipc.new_stream(file, batch.schema) as writer:
            writer.write_batch(batch)


def _from_ipc_file(path: Path):
    import pyarrow as pa

    with path.open("rb") as file:
        return pa.ipc.open_stream(file).read_next_batch()


def _list_array(values: list, value_type):
    import pyarrow as pa

    return pa.array([values], type=pa.list_(value_type))


def _record_batch(arrays: list, fields: list[tuple[str, object]]):
    import pyarrow as pa

    schema = pa.schema(
        [pa.field(name, field_type, nullable=False) for name, field_type in fields]
    )
    return pa.RecordBatch.from_arrays(arrays, schema=schema)


def _named_record_batch(columns: list[tuple[str, Any]]):
    return _record_batch(
        [array for _, array in columns],
        [(name, array.type) for name, array in columns],
    )


def _replace_named_array(
    columns: list[tuple[str, Any]], name: str, replacement: Any
) -> list[tuple[str, Any]]:
    return [
        (column_name, replacement if column_name == name else array)
        for column_name, array in columns
    ]


def _assert_point_cloud_rejected(
    driver: Path,
    batch: Any,
    path: Path,
    stderr_fragments: tuple[str, ...],
) -> None:
    _to_ipc_file(batch, path)
    result = subprocess.run(
        [driver, "read-point-cloud", path],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0, f"C++ reader unexpectedly accepted {path.name}"
    for fragment in stderr_fragments:
        assert fragment in result.stderr, (
            f"expected {fragment!r} in stderr for {path.name}, got {result.stderr!r}"
        )


def _assert_schema(batch, fields: list[tuple[str, object]]) -> None:
    assert batch.schema.names == [name for name, _ in fields]
    assert [field.type for field in batch.schema] == [
        field_type for _, field_type in fields
    ]
    assert all(not field.nullable for field in batch.schema)
    assert batch.num_rows == 1


def _assert_exact_schema(batch, schema) -> None:
    assert batch.schema == schema
    assert batch.num_rows == 1
    assert "goal_id" not in batch.schema.names
    assert "goal_status" not in batch.schema.names


def _assert_close(actual: list[float], expected: list[float]) -> None:
    assert len(actual) == len(expected)
    assert all(
        math.isclose(left, right, rel_tol=1e-6) for left, right in zip(actual, expected)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", required=True)
    parser.add_argument("--pythonpath", required=True)
    args = parser.parse_args()

    sys.path.insert(0, args.pythonpath)
    missing_dependencies = [
        name for name in ("numpy", "pyarrow") if importlib.util.find_spec(name) is None
    ]
    if missing_dependencies:  # pragma: no cover - exercised by CTest skip
        print(
            "skipping Python/C++ interop test: missing "
            + ", ".join(missing_dependencies),
            file=sys.stderr,
        )
        return 77

    import numpy as np
    import pyarrow as pa
    from forge_msgs import (
        AudioChunk,
        PointCloud,
        PointCloudBatch,
        PointCloudView,
        Text,
        ToolMessage,
    )

    driver = Path(args.driver)
    if not driver.exists():
        print(f"skipping Python/C++ interop test: missing {driver}", file=sys.stderr)
        return 77

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        cpp_text = tmp_path / "cpp_text.arrow"
        subprocess.run([driver, "write-text", cpp_text], check=True)
        assert Text.from_arrow(cpp_text.read_bytes()).text == "cpp hello"

        py_text = tmp_path / "py_text.arrow"
        _to_ipc_file(Text(text="python hello").to_arrow(), py_text)
        out = subprocess.check_output([driver, "read-text", py_text], text=True).strip()
        assert out == "python hello"

        cpp_tool_message = tmp_path / "cpp_tool_message.arrow"
        subprocess.run([driver, "write-tool-message", cpp_tool_message], check=True)
        tool_message = ToolMessage.from_arrow(cpp_tool_message.read_bytes())
        assert tool_message.message_type == "tool.invoke.request"
        assert tool_message.request_id == "cpp-request-1"
        assert tool_message.invocation_id == "cpp-invocation-1"
        assert tool_message.attempt_id == "cpp-attempt-1"
        assert tool_message.endpoint_id == "vision.yolo"
        assert tool_message.endpoint_instance_id == "cpp-instance-1"
        assert tool_message.operation == "detect"
        assert tool_message.sequence is None
        assert tool_message.payload() == {"arguments": {"class": "cube"}}

        cpp_unresolved = tmp_path / "cpp_unresolved_tool_message.arrow"
        subprocess.run(
            [driver, "write-unresolved-tool-message", cpp_unresolved], check=True
        )
        unresolved = ToolMessage.from_arrow(cpp_unresolved.read_bytes())
        assert unresolved.message_type == "tool.invoke.response"
        assert unresolved.endpoint_instance_id is None
        assert unresolved.payload() == {
            "outcome": "accepted",
            "accepted": {"details": {}},
        }

        py_tool_message = tmp_path / "py_tool_message.arrow"
        _to_ipc_file(
            ToolMessage.from_payload(
                message_type="tool.event",
                invocation_id="py-invocation-1",
                attempt_id="py-attempt-1",
                endpoint_id="policy.lerobot",
                endpoint_instance_id="py-instance-1",
                operation="execute",
                sequence=7,
                payload={"type": "progress", "data": {"fraction": 0.5}},
            ).to_arrow(),
            py_tool_message,
        )
        out = subprocess.check_output(
            [driver, "read-tool-message", py_tool_message], text=True
        ).strip()
        assert out == (
            "tool.event null py-invocation-1 py-attempt-1 policy.lerobot "
            'py-instance-1 execute 7 {"data":{"fraction":0.5},"type":"progress"}'
        )

        py_unresolved = tmp_path / "py_unresolved_tool_message.arrow"
        _to_ipc_file(
            ToolMessage.from_payload(
                message_type="tool.error",
                request_id="py-request-1",
                invocation_id="py-invocation-1",
                attempt_id="py-attempt-1",
                endpoint_id="vision.yolo",
                endpoint_instance_id=None,
                operation="detect",
                payload={
                    "error": {
                        "code": "GATEWAY_RESOLUTION_FAILED",
                        "message": "no provider available",
                        "retryable": False,
                        "details": {},
                    }
                },
            ).to_arrow(),
            py_unresolved,
        )
        out = subprocess.check_output(
            [driver, "read-tool-message", py_unresolved], text=True
        ).strip()
        assert out == (
            "tool.error py-request-1 py-invocation-1 py-attempt-1 "
            "vision.yolo null detect null "
            '{"error":{"code":"GATEWAY_RESOLUTION_FAILED",'
            '"details":{},"message":"no provider available","retryable":false}}'
        )

        cpp_audio = tmp_path / "cpp_audio.arrow"
        subprocess.run([driver, "write-audio", cpp_audio], check=True)
        chunk = AudioChunk.from_arrow(cpp_audio.read_bytes())
        assert chunk.sample_rate == 16000
        assert chunk.channels == 1
        assert chunk.sample_format == "f32le"
        assert chunk.frame_count == 2

        py_audio = tmp_path / "py_audio.arrow"
        data = struct.pack("<hh", 100, -200)
        _to_ipc_file(
            AudioChunk(
                sample_rate=48000,
                channels=1,
                sample_format="s16le",
                frame_count=2,
                data=data,
            ).to_arrow(),
            py_audio,
        )
        out = subprocess.check_output(
            [driver, "read-audio", py_audio], text=True
        ).strip()
        assert out == "48000 1 s16le 2 4"

        string_list = pa.list_(pa.string())
        f32_list = pa.list_(pa.float32())
        u8_list = pa.list_(pa.uint8())
        u32_list = pa.list_(pa.uint32())

        point_cloud_schema = pa.schema(
            [
                pa.field("width", pa.uint32(), nullable=False),
                pa.field("height", pa.uint32(), nullable=False),
                pa.field("is_dense", pa.bool_(), nullable=False),
                pa.field("x", f32_list, nullable=False),
                pa.field("y", f32_list, nullable=False),
                pa.field("z", f32_list, nullable=False),
                pa.field("intensity", f32_list, nullable=False),
                pa.field("red", u8_list, nullable=False),
                pa.field("green", u8_list, nullable=False),
                pa.field("blue", u8_list, nullable=False),
            ]
        )
        cpp_point_cloud = tmp_path / "cpp_point_cloud.arrow"
        subprocess.run([driver, "write-point-cloud", cpp_point_cloud], check=True)
        cpp_point_cloud_view = PointCloudView.from_arrow(cpp_point_cloud.read_bytes())
        assert cpp_point_cloud_view.to_owned() == PointCloud(
            width=2,
            height=1,
            is_dense=True,
            x=[1.0, 2.0],
            y=[3.0, 4.0],
            z=[5.0, 6.0],
            red=[255, 0],
            green=[0, 255],
            blue=[0, 0],
        )

        batch = _from_ipc_file(cpp_point_cloud)
        assert batch.schema == point_cloud_schema
        assert batch.num_rows == 1
        assert batch["width"][0].as_py() == 2
        assert batch["height"][0].as_py() == 1
        assert batch["is_dense"][0].as_py() is True
        _assert_close(batch["x"][0].as_py(), [1.0, 2.0])
        _assert_close(batch["y"][0].as_py(), [3.0, 4.0])
        _assert_close(batch["z"][0].as_py(), [5.0, 6.0])
        assert batch["intensity"][0].as_py() == []
        assert batch["red"][0].as_py() == [255, 0]
        assert batch["green"][0].as_py() == [0, 255]
        assert batch["blue"][0].as_py() == [0, 0]

        expected_point_cloud = "2 1 2 1 20 40 60 2 4 6 empty"
        py_owned_point_cloud = tmp_path / "py_owned_point_cloud.arrow"
        _to_ipc_file(
            PointCloud(
                width=2,
                height=1,
                is_dense=True,
                x=[10.0, 20.0],
                y=[30.0, 40.0],
                z=[50.0, 60.0],
                red=[1, 2],
                green=[3, 4],
                blue=[5, 6],
            ).to_arrow(),
            py_owned_point_cloud,
        )
        out = subprocess.check_output(
            [driver, "read-point-cloud", py_owned_point_cloud], text=True
        ).strip()
        assert out == expected_point_cloud

        py_point_cloud_batch = PointCloudBatch.from_numpy(
            x=np.array([10.0, 20.0], dtype=np.float32),
            y=np.array([30.0, 40.0], dtype=np.float32),
            z=np.array([50.0, 60.0], dtype=np.float32),
            rgb=(
                np.array([1, 2], dtype=np.uint8),
                np.array([3, 4], dtype=np.uint8),
                np.array([5, 6], dtype=np.uint8),
            ),
        ).to_arrow()
        py_point_cloud = tmp_path / "py_point_cloud_batch.arrow"
        _to_ipc_file(py_point_cloud_batch, py_point_cloud)
        out = subprocess.check_output(
            [driver, "read-point-cloud", py_point_cloud], text=True
        ).strip()
        assert out == expected_point_cloud

        point_cloud_columns = list(
            zip(
                py_point_cloud_batch.schema.names,
                py_point_cloud_batch.columns,
                strict=True,
            )
        )
        reordered_point_cloud = tmp_path / "py_point_cloud_reordered_extra.arrow"
        _to_ipc_file(
            _named_record_batch(
                [
                    *reversed(point_cloud_columns),
                    ("extra", pa.array(["ignored"], type=pa.string())),
                ]
            ),
            reordered_point_cloud,
        )
        out = subprocess.check_output(
            [driver, "read-point-cloud", reordered_point_cloud], text=True
        ).strip()
        assert out == expected_point_cloud

        width_column = next(column for column in point_cloud_columns if column[0] == "width")
        malformed_point_clouds = [
            (
                "two_rows",
                _named_record_batch(
                    [
                        (name, pa.concat_arrays([array, array]))
                        for name, array in point_cloud_columns
                    ]
                ),
                ("RecordBatch", "one row"),
            ),
            (
                "null_scalar",
                _named_record_batch(
                    _replace_named_array(
                        point_cloud_columns,
                        "width",
                        pa.array([None], type=pa.uint32()),
                    )
                ),
                ("width", "non-null scalar"),
            ),
            (
                "null_list_cell",
                _named_record_batch(
                    _replace_named_array(
                        point_cloud_columns,
                        "x",
                        pa.array([None], type=f32_list),
                    )
                ),
                ("x", "non-null list"),
            ),
            (
                "null_list_item",
                _named_record_batch(
                    _replace_named_array(
                        point_cloud_columns,
                        "x",
                        pa.array([[10.0, None]], type=f32_list),
                    )
                ),
                ("x", "must not contain nulls"),
            ),
            (
                "wrong_list_primitive",
                _named_record_batch(
                    _replace_named_array(
                        point_cloud_columns,
                        "x",
                        pa.array([[10.0, 20.0]], type=pa.list_(pa.float64())),
                    )
                ),
                ("x", "float32"),
            ),
            (
                "missing_required_field",
                _named_record_batch(
                    [column for column in point_cloud_columns if column[0] != "width"]
                ),
                ("missing", "width"),
            ),
            (
                "duplicate_required_field",
                _named_record_batch([width_column, *point_cloud_columns]),
                ("width", "column"),
            ),
        ]
        for case_name, malformed_batch, stderr_fragments in malformed_point_clouds:
            _assert_point_cloud_rejected(
                driver,
                malformed_batch,
                tmp_path / f"py_point_cloud_{case_name}.arrow",
                stderr_fragments,
            )

        cpp_classification = tmp_path / "cpp_classification.arrow"
        subprocess.run([driver, "write-classification", cpp_classification], check=True)
        batch = _from_ipc_file(cpp_classification)
        _assert_schema(batch, [("class_id", string_list), ("score", f32_list)])
        assert batch["class_id"][0].as_py() == ["person", "vehicle"]
        _assert_close(batch["score"][0].as_py(), [0.9, 0.1])

        py_classification = tmp_path / "py_classification.arrow"
        _to_ipc_file(
            _record_batch(
                [
                    _list_array(["cat", "dog"], pa.string()),
                    _list_array([0.75, 0.25], pa.float32()),
                ],
                [("class_id", string_list), ("score", f32_list)],
            ),
            py_classification,
        )
        out = subprocess.check_output(
            [driver, "read-classification", py_classification], text=True
        ).strip()
        assert out == "2 cat 0.75"

        multi_batch_classification = tmp_path / "multi_batch_classification.arrow"
        classification_batch = _from_ipc_file(py_classification)
        with multi_batch_classification.open("wb") as file:
            with pa.ipc.new_stream(file, classification_batch.schema) as writer:
                writer.write_batch(classification_batch)
                writer.write_batch(classification_batch)
        result = subprocess.run(
            [driver, "read-classification", multi_batch_classification],
            text=True,
            capture_output=True,
        )
        assert result.returncode != 0
        assert "exactly one RecordBatch" in result.stderr

        py_empty_classification = tmp_path / "empty_classification.arrow"
        _to_ipc_file(
            _record_batch(
                [_list_array([], pa.string()), _list_array([], pa.float32())],
                [("class_id", string_list), ("score", f32_list)],
            ),
            py_empty_classification,
        )
        out = subprocess.check_output(
            [driver, "read-classification", py_empty_classification], text=True
        ).strip()
        assert out == "0 empty"

        keypoint2d_fields = [
            ("instance_id", string_list),
            ("detection_id", string_list),
            ("track_id", string_list),
            ("keypoint_offset", u32_list),
            ("keypoint_id", string_list),
            ("x", f32_list),
            ("y", f32_list),
            ("score", f32_list),
        ]
        cpp_keypoint2d = tmp_path / "cpp_keypoint2d.arrow"
        subprocess.run([driver, "write-keypoint2d", cpp_keypoint2d], check=True)
        batch = _from_ipc_file(cpp_keypoint2d)
        _assert_schema(batch, keypoint2d_fields)
        assert batch["keypoint_offset"][0].as_py() == [0, 2]
        assert batch["keypoint_id"][0].as_py() == ["left_eye", "right_eye"]

        py_keypoint2d = tmp_path / "py_keypoint2d.arrow"
        _to_ipc_file(
            _record_batch(
                [
                    _list_array(["animal-0"], pa.string()),
                    _list_array(["d7"], pa.string()),
                    _list_array(["track-7"], pa.string()),
                    _list_array([0, 1], pa.uint32()),
                    _list_array(["nose"], pa.string()),
                    _list_array([4.0], pa.float32()),
                    _list_array([5.0], pa.float32()),
                    _list_array([0.8], pa.float32()),
                ],
                keypoint2d_fields,
            ),
            py_keypoint2d,
        )
        out = subprocess.check_output(
            [driver, "read-keypoint2d", py_keypoint2d], text=True
        ).strip()
        assert out == "animal-0 1 4 0.8"

        py_empty_keypoint2d = tmp_path / "py_empty_keypoint2d.arrow"
        _to_ipc_file(
            _record_batch(
                [
                    _list_array([], pa.string()),
                    _list_array([], pa.string()),
                    _list_array([], pa.string()),
                    _list_array([0], pa.uint32()),
                    _list_array([], pa.string()),
                    _list_array([], pa.float32()),
                    _list_array([], pa.float32()),
                    _list_array([], pa.float32()),
                ],
                keypoint2d_fields,
            ),
            py_empty_keypoint2d,
        )
        out = subprocess.check_output(
            [driver, "read-keypoint2d", py_empty_keypoint2d], text=True
        ).strip()
        assert out == "0 0 empty"

        keypoint3d_fields = keypoint2d_fields[:-1] + [
            ("z", f32_list),
            ("score", f32_list),
        ]
        cpp_keypoint3d = tmp_path / "cpp_keypoint3d.arrow"
        subprocess.run([driver, "write-keypoint3d", cpp_keypoint3d], check=True)
        batch = _from_ipc_file(cpp_keypoint3d)
        _assert_schema(batch, keypoint3d_fields)
        _assert_close(batch["z"][0].as_py(), [3.0])

        py_keypoint3d = tmp_path / "py_keypoint3d.arrow"
        _to_ipc_file(
            _record_batch(
                [
                    _list_array(["animal-0"], pa.string()),
                    _list_array(["d7"], pa.string()),
                    _list_array(["track-7"], pa.string()),
                    _list_array([0, 1], pa.uint32()),
                    _list_array(["nose"], pa.string()),
                    _list_array([1.0], pa.float32()),
                    _list_array([2.0], pa.float32()),
                    _list_array([3.0], pa.float32()),
                    _list_array([0.9], pa.float32()),
                ],
                keypoint3d_fields,
            ),
            py_keypoint3d,
        )
        out = subprocess.check_output(
            [driver, "read-keypoint3d", py_keypoint3d], text=True
        ).strip()
        assert out == "animal-0 nose 3 0.9"

        py_empty_keypoint3d = tmp_path / "py_empty_keypoint3d.arrow"
        _to_ipc_file(
            _record_batch(
                [
                    _list_array([], pa.string()),
                    _list_array([], pa.string()),
                    _list_array([], pa.string()),
                    _list_array([0], pa.uint32()),
                    _list_array([], pa.string()),
                    _list_array([], pa.float32()),
                    _list_array([], pa.float32()),
                    _list_array([], pa.float32()),
                    _list_array([], pa.float32()),
                ],
                keypoint3d_fields,
            ),
            py_empty_keypoint3d,
        )
        out = subprocess.check_output(
            [driver, "read-keypoint3d", py_empty_keypoint3d], text=True
        ).strip()
        assert out == "0 0 empty"

        segmentation_fields = [
            ("mask_id", string_list),
            ("detection_id", string_list),
            ("track_id", string_list),
            ("x_offset", u32_list),
            ("y_offset", u32_list),
            ("width", u32_list),
            ("height", u32_list),
            ("encoding", pa.string()),
            ("data", pa.list_(pa.large_binary())),
            ("score", f32_list),
        ]
        cpp_segmentation = tmp_path / "cpp_segmentation.arrow"
        subprocess.run([driver, "write-segmentation", cpp_segmentation], check=True)
        batch = _from_ipc_file(cpp_segmentation)
        _assert_schema(batch, segmentation_fields)
        _assert_close(batch["score"][0].as_py(), [0.98])

        py_segmentation = tmp_path / "py_segmentation.arrow"
        _to_ipc_file(
            _record_batch(
                [
                    _list_array(["mask-7"], pa.string()),
                    _list_array(["d7"], pa.string()),
                    _list_array(["track-7"], pa.string()),
                    _list_array([0], pa.uint32()),
                    _list_array([0], pa.uint32()),
                    _list_array([2], pa.uint32()),
                    _list_array([2], pa.uint32()),
                    pa.array(["mono8"], type=pa.string()),
                    _list_array([bytes((0, 255, 255, 0))], pa.large_binary()),
                    _list_array([0.85], pa.float32()),
                ],
                segmentation_fields,
            ),
            py_segmentation,
        )
        out = subprocess.check_output(
            [driver, "read-segmentation", py_segmentation], text=True
        ).strip()
        assert out == "mask-7 4 0.85"

        py_segmentation_empty_score = tmp_path / "py_segmentation_empty_score.arrow"
        empty_score_arrays = [
            _list_array(["mask-8"], pa.string()),
            _list_array(["d8"], pa.string()),
            _list_array(["track-8"], pa.string()),
            _list_array([0], pa.uint32()),
            _list_array([0], pa.uint32()),
            _list_array([1], pa.uint32()),
            _list_array([1], pa.uint32()),
            pa.array(["mono8"], type=pa.string()),
            _list_array([bytes((255,))], pa.large_binary()),
            _list_array([], pa.float32()),
        ]
        _to_ipc_file(
            _record_batch(empty_score_arrays, segmentation_fields),
            py_segmentation_empty_score,
        )
        out = subprocess.check_output(
            [driver, "read-segmentation", py_segmentation_empty_score], text=True
        ).strip()
        assert out == "mask-8 1 empty"

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
        cpp_follow = tmp_path / "cpp_follow.arrow"
        subprocess.run(
            [driver, "write-follow-joint-trajectory-goal", cpp_follow], check=True
        )
        batch = _from_ipc_file(cpp_follow)
        _assert_exact_schema(batch, follow_schema)
        trajectory = batch["trajectory"][0].as_py()
        assert trajectory["joint_names"] == ["joint_1", "joint_2"]
        assert len(trajectory["points"]) == 2
        assert batch["path_tolerance"][0].as_py()[0]["position"] == 0.05
        assert batch["goal_time_tolerance_ns"][0].as_py() == 2000000

        py_follow = tmp_path / "py_follow.arrow"
        python_trajectory = {
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
        _to_ipc_file(
            pa.RecordBatch.from_arrays(
                [
                    pa.array([python_trajectory], type=trajectory_type),
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
        out = subprocess.check_output(
            [driver, "read-follow-joint-trajectory-goal", py_follow], text=True
        ).strip()
        assert out == "2 2 1 null"

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
        cpp_move_joints = tmp_path / "cpp_move_joints.arrow"
        subprocess.run([driver, "write-move-joints-goal", cpp_move_joints], check=True)
        batch = _from_ipc_file(cpp_move_joints)
        _assert_exact_schema(batch, move_joints_schema)
        assert batch["group_name"][0].as_py() == "arm"
        assert batch["positions"][0].as_py() == [1.0, 1.5]
        assert batch["requested_duration_ns"][0].as_py() is None

        py_move_joints = tmp_path / "py_move_joints.arrow"
        _to_ipc_file(
            pa.RecordBatch.from_arrays(
                [
                    pa.array(["manipulator"], type=pa.string()),
                    _list_array(["a", "b"], pa.string()),
                    _list_array([0.25, -0.5], pa.float64()),
                    pa.array([0.8], type=pa.float64()),
                    pa.array([0.7], type=pa.float64()),
                    pa.array([1500000], type=pa.int64()),
                ],
                schema=move_joints_schema,
            ),
            py_move_joints,
        )
        out = subprocess.check_output(
            [driver, "read-move-joints-goal", py_move_joints], text=True
        ).strip()
        assert out == "manipulator 2 0.25 1500000"

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
        cpp_move_pose = tmp_path / "cpp_move_pose.arrow"
        subprocess.run([driver, "write-move-pose-goal", cpp_move_pose], check=True)
        batch = _from_ipc_file(cpp_move_pose)
        _assert_exact_schema(batch, move_pose_schema)
        assert batch["target_pose"][0].as_py()["x"] == 0.4
        assert batch["requested_duration_ns"][0].as_py() is None
        assert batch["orientation_tolerance_rad"][0].as_py() is None

        py_move_pose = tmp_path / "py_move_pose.arrow"
        _to_ipc_file(
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
        out = subprocess.check_output(
            [driver, "read-move-pose-goal", py_move_pose], text=True
        ).strip()
        assert out == "manipulator base tcp 0.6 null 0.02"

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
