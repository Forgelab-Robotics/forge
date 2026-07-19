from __future__ import annotations

import argparse
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


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

    schema = pa.schema([pa.field(name, field_type, nullable=False) for name, field_type in fields])
    return pa.RecordBatch.from_arrays(arrays, schema=schema)


def _assert_schema(batch, fields: list[tuple[str, object]]) -> None:
    assert batch.schema.names == [name for name, _ in fields]
    assert [field.type for field in batch.schema] == [field_type for _, field_type in fields]
    assert all(not field.nullable for field in batch.schema)
    assert batch.num_rows == 1


def _assert_close(actual: list[float], expected: list[float]) -> None:
    assert len(actual) == len(expected)
    assert all(math.isclose(left, right, rel_tol=1e-6) for left, right in zip(actual, expected))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", required=True)
    parser.add_argument("--pythonpath", required=True)
    args = parser.parse_args()

    sys.path.insert(0, args.pythonpath)
    try:
        import pyarrow as pa
        from forge_msgs import AudioChunk, Text
    except Exception as exc:  # pragma: no cover - exercised by CTest skip
        print(f"skipping Python/C++ interop test: {exc}", file=sys.stderr)
        return 77

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
        out = subprocess.check_output([driver, "read-audio", py_audio], text=True).strip()
        assert out == "48000 1 s16le 2 4"

        string_list = pa.list_(pa.string())
        f32_list = pa.list_(pa.float32())
        u32_list = pa.list_(pa.uint32())

        cpp_classification = tmp_path / "cpp_classification.arrow"
        subprocess.run([driver, "write-classification", cpp_classification], check=True)
        batch = _from_ipc_file(cpp_classification)
        _assert_schema(batch, [("class_id", string_list), ("score", f32_list)])
        assert batch["class_id"][0].as_py() == ["person", "vehicle"]
        _assert_close(batch["score"][0].as_py(), [0.9, 0.1])

        py_classification = tmp_path / "py_classification.arrow"
        _to_ipc_file(
            _record_batch(
                [_list_array(["cat", "dog"], pa.string()), _list_array([0.75, 0.25], pa.float32())],
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
        out = subprocess.check_output([driver, "read-keypoint2d", py_keypoint2d], text=True).strip()
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

        keypoint3d_fields = keypoint2d_fields[:-1] + [("z", f32_list), ("score", f32_list)]
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
        out = subprocess.check_output([driver, "read-keypoint3d", py_keypoint3d], text=True).strip()
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
