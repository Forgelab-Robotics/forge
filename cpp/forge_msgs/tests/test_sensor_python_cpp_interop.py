from __future__ import annotations

import argparse
import importlib.util
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _write_ipc(batch: Any, path: Path) -> None:
    import pyarrow as pa

    with path.open("wb") as file:
        with pa.ipc.new_stream(file, batch.schema) as writer:
            writer.write_batch(batch)


def _read_ipc(path: Path):
    import pyarrow as pa

    with path.open("rb") as file:
        return pa.ipc.open_stream(file).read_next_batch()


def _batch_from_columns(columns: list[tuple[Any, Any]]):
    import pyarrow as pa

    return pa.RecordBatch.from_arrays(
        [array for _, array in columns],
        schema=pa.schema([field for field, _ in columns]),
    )


def _columns(batch: Any) -> list[tuple[Any, Any]]:
    return [
        (batch.schema.field(index), batch.column(index))
        for index in range(batch.num_columns)
    ]


def _replace_column(
    columns: list[tuple[Any, Any]], name: str, field: Any, array: Any
) -> list[tuple[Any, Any]]:
    return [
        (field, array) if old_field.name == name else (old_field, old_array)
        for old_field, old_array in columns
    ]


def _without_column(columns: list[tuple[Any, Any]], name: str):
    return [(field, array) for field, array in columns if field.name != name]


def _assert_rejected(
    driver: Path,
    command: str,
    batch: Any,
    path: Path,
    stderr_fragments: tuple[str, ...],
) -> None:
    _write_ipc(batch, path)
    result = subprocess.run(
        [driver, command, path],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0, f"C++ reader unexpectedly accepted {path.name}"
    for fragment in stderr_fragments:
        assert fragment in result.stderr, (
            f"expected {fragment!r} in stderr for {path.name}, "
            f"got {result.stderr!r}"
        )


def _point_cloud_buffer_types():
    import pyarrow as pa

    point_field = pa.struct(
        [
            pa.field("name", pa.string(), nullable=False),
            pa.field("offset", pa.uint32(), nullable=False),
            pa.field("datatype", pa.string(), nullable=False),
            pa.field("count", pa.uint32(), nullable=False),
        ]
    )
    point_fields = pa.list_(point_field)
    schema = pa.schema(
        [
            pa.field("width", pa.uint32(), nullable=False),
            pa.field("height", pa.uint32(), nullable=False),
            pa.field("is_dense", pa.bool_(), nullable=False),
            pa.field("byte_order", pa.string(), nullable=False),
            pa.field("point_stride", pa.uint32(), nullable=False),
            pa.field("row_stride", pa.uint64(), nullable=False),
            pa.field("fields", point_fields, nullable=False),
            pa.field("data", pa.large_binary(), nullable=False),
        ]
    )
    return point_field, point_fields, schema


def _imu_types():
    import pyarrow as pa

    orientation = pa.struct(
        [
            pa.field("qx", pa.float64(), nullable=False),
            pa.field("qy", pa.float64(), nullable=False),
            pa.field("qz", pa.float64(), nullable=False),
            pa.field("qw", pa.float64(), nullable=False),
        ]
    )
    vector3 = pa.struct(
        [
            pa.field("x", pa.float64(), nullable=False),
            pa.field("y", pa.float64(), nullable=False),
            pa.field("z", pa.float64(), nullable=False),
        ]
    )
    covariance = pa.list_(pa.float64())
    schema = pa.schema(
        [
            pa.field("orientation", orientation, nullable=True),
            pa.field("angular_velocity", vector3, nullable=False),
            pa.field("linear_acceleration", vector3, nullable=False),
            pa.field("orientation_covariance", covariance, nullable=False),
            pa.field("angular_velocity_covariance", covariance, nullable=False),
            pa.field("linear_acceleration_covariance", covariance, nullable=False),
            pa.field("temperature_celsius", pa.float64(), nullable=True),
        ]
    )
    return orientation, vector3, covariance, schema


def _python_point_cloud_buffer(PointCloudBuffer, PointField):
    fields = [
        PointField(name="ring", offset=13, datatype="uint16", count=1),
        PointField(name="z", offset=9, datatype="float32", count=1),
        PointField(name="x", offset=1, datatype="float32", count=1),
        PointField(name="y", offset=5, datatype="float32", count=1),
    ]
    data = bytearray([0xA5] * 70)
    for row in range(2):
        for column in range(2):
            index = row * 2 + column
            point = row * 35 + column * 16
            struct.pack_into(">f", data, point + 1, float(index + 1))
            struct.pack_into(">f", data, point + 5, float(index + 11))
            struct.pack_into(">f", data, point + 9, float(index + 21))
            struct.pack_into(">H", data, point + 13, index + 100)
    value = PointCloudBuffer(
        width=2,
        height=2,
        is_dense=True,
        byte_order="big_endian",
        point_stride=16,
        row_stride=35,
        fields=fields,
        data=bytes(data),
    )
    descriptors = [field.model_dump(mode="python") for field in value.fields]
    return value, descriptors


def _python_imu(Imu, ImuOrientation, ImuVector3):
    return Imu(
        orientation=ImuOrientation(qx=0.0, qy=0.0, qz=0.0, qw=3.0),
        angular_velocity=ImuVector3(x=0.4, y=0.5, z=0.6),
        linear_acceleration=ImuVector3(x=1.0, y=2.0, z=9.7),
        orientation_covariance=[1.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 3.0],
        angular_velocity_covariance=[
            4.0,
            0.0,
            0.0,
            0.0,
            5.0,
            0.0,
            0.0,
            0.0,
            6.0,
        ],
        linear_acceleration_covariance=[],
        temperature_celsius=26.5,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", required=True)
    parser.add_argument("--pythonpath", required=True)
    args = parser.parse_args()

    sys.path.insert(0, args.pythonpath)
    missing_dependencies = [
        name
        for name in ("numpy", "pyarrow", "pydantic")
        if importlib.util.find_spec(name) is None
    ]
    if missing_dependencies:  # pragma: no cover - exercised by CTest skip
        print(
            "skipping sensor interop test: missing "
            + ", ".join(missing_dependencies),
            file=sys.stderr,
        )
        return 77

    import pyarrow as pa
    from forge_msgs import (
        Imu,
        ImuOrientation,
        ImuVector3,
        PointCloudBuffer,
        PointCloudBufferView,
        PointField,
    )

    driver = Path(args.driver)
    if not driver.exists():
        print(f"skipping sensor interop test: missing {driver}", file=sys.stderr)
        return 77

    _, point_fields, point_cloud_buffer_schema = _point_cloud_buffer_types()
    orientation, vector3, covariance, imu_schema = _imu_types()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        cpp_point_cloud_buffer = tmp_path / "cpp_point_cloud_buffer.arrow"
        subprocess.run(
            [driver, "write-point-cloud-buffer", cpp_point_cloud_buffer], check=True
        )
        point_cloud_buffer_batch = _read_ipc(cpp_point_cloud_buffer)
        assert point_cloud_buffer_batch.schema == point_cloud_buffer_schema
        assert point_cloud_buffer_batch.num_rows == 1
        assert point_cloud_buffer_batch["byte_order"][0].as_py() == "little_endian"
        assert [
            descriptor["name"]
            for descriptor in point_cloud_buffer_batch["fields"][0].as_py()
        ] == ["x", "y", "z", "ring"]
        cpp_data = point_cloud_buffer_batch["data"][0].as_py()
        assert struct.unpack_from("<fffH", cpp_data, 0) == (1.0, 2.0, 3.0, 7)
        assert struct.unpack_from("<fffH", cpp_data, 16) == (4.0, 5.0, 6.0, 8)

        cpp_point_cloud_buffer_view = PointCloudBufferView.from_arrow(
            cpp_point_cloud_buffer.read_bytes()
        )
        cpp_point_cloud_buffer_owned = PointCloudBuffer.from_arrow(
            cpp_point_cloud_buffer.read_bytes()
        )
        assert cpp_point_cloud_buffer_view.width == 2
        assert cpp_point_cloud_buffer_view.height == 1
        assert cpp_point_cloud_buffer_view.byte_order == "little_endian"
        assert cpp_point_cloud_buffer_view.field_names == ("x", "y", "z", "ring")
        assert cpp_point_cloud_buffer_view.field("x").tolist() == [1.0, 4.0]
        assert cpp_point_cloud_buffer_view.field("ring").tolist() == [7, 8]
        assert len(cpp_point_cloud_buffer_view.raw_data) == 32
        assert all(
            isinstance(field, PointField)
            for field in cpp_point_cloud_buffer_owned.fields
        )
        assert cpp_point_cloud_buffer_view.to_owned() == cpp_point_cloud_buffer_owned

        python_point_cloud_buffer, descriptors = _python_point_cloud_buffer(
            PointCloudBuffer, PointField
        )
        assert all(
            isinstance(field, PointField) for field in python_point_cloud_buffer.fields
        )
        python_point_cloud_buffer_batch = python_point_cloud_buffer.to_arrow()
        assert python_point_cloud_buffer_batch.schema == point_cloud_buffer_schema
        python_point_cloud_buffer_view = PointCloudBufferView.from_arrow(
            python_point_cloud_buffer_batch
        )
        assert python_point_cloud_buffer_view.byte_order == "little_endian"
        assert python_point_cloud_buffer_view.field("x").tolist() == [
            [1.0, 2.0],
            [3.0, 4.0],
        ]
        python_pcb_columns = _columns(python_point_cloud_buffer_view.record_batch)
        reordered_point_cloud_buffer = _batch_from_columns(
            [
                *reversed(python_pcb_columns),
                (
                    pa.field("extra", pa.string(), nullable=False),
                    pa.array(["ignored"], type=pa.string()),
                ),
            ]
        )
        py_point_cloud_buffer = tmp_path / "py_point_cloud_buffer.arrow"
        _write_ipc(reordered_point_cloud_buffer, py_point_cloud_buffer)
        output = subprocess.check_output(
            [driver, "read-point-cloud-buffer", py_point_cloud_buffer], text=True
        ).strip()
        assert output == "2 2 little_endian 4 70 4 14 24 103", output

        malformed_point_cloud_buffers = [
            (
                "missing_data",
                _batch_from_columns(_without_column(python_pcb_columns, "data")),
                ("missing", "data"),
            ),
            (
                "duplicate_width",
                _batch_from_columns(
                    [
                        *python_pcb_columns,
                        next(
                            column
                            for column in python_pcb_columns
                            if column[0].name == "width"
                        ),
                    ]
                ),
                ("width", "exactly once"),
            ),
            (
                "wrong_width_type",
                _batch_from_columns(
                    _replace_column(
                        python_pcb_columns,
                        "width",
                        pa.field("width", pa.int32(), nullable=False),
                        pa.array([2], type=pa.int32()),
                    )
                ),
                ("width", "physical type"),
            ),
            (
                "null_fields_cell",
                _batch_from_columns(
                    _replace_column(
                        python_pcb_columns,
                        "fields",
                        pa.field("fields", point_fields, nullable=True),
                        pa.array([None], type=point_fields),
                    )
                ),
                ("fields", "non-null"),
            ),
            (
                "null_descriptor",
                _batch_from_columns(
                    _replace_column(
                        python_pcb_columns,
                        "fields",
                        pa.field("fields", point_fields, nullable=False),
                        pa.array([[None, *descriptors]], type=point_fields),
                    )
                ),
                ("fields", "null structs"),
            ),
            (
                "null_descriptor_child",
                _batch_from_columns(
                    _replace_column(
                        python_pcb_columns,
                        "fields",
                        pa.field("fields", point_fields, nullable=False),
                        pa.array(
                            [
                                [
                                    {
                                        "name": None,
                                        "offset": 13,
                                        "datatype": "uint16",
                                        "count": 1,
                                    },
                                    *descriptors[1:],
                                ]
                            ],
                            type=point_fields,
                        ),
                    )
                ),
                ("fields", "children", "null"),
            ),
        ]
        for case_name, malformed, fragments in malformed_point_cloud_buffers:
            _assert_rejected(
                driver,
                "read-point-cloud-buffer",
                malformed,
                tmp_path / f"py_point_cloud_buffer_{case_name}.arrow",
                fragments,
            )

        cpp_imu = tmp_path / "cpp_imu.arrow"
        subprocess.run([driver, "write-imu", cpp_imu], check=True)
        imu_batch = _read_ipc(cpp_imu)
        assert imu_batch.schema == imu_schema
        assert imu_batch.num_rows == 1
        assert imu_batch["orientation"][0].as_py() == {
            "qx": 0.0,
            "qy": 0.0,
            "qz": 0.0,
            "qw": 2.0,
        }
        assert imu_batch["angular_velocity"][0].as_py() == {
            "x": 0.1,
            "y": 0.2,
            "z": 0.3,
        }
        assert imu_batch["orientation_covariance"][0].as_py() == [
            1.0,
            0.0,
            0.0,
            0.0,
            2.0,
            0.0,
            0.0,
            0.0,
            3.0,
        ]
        assert imu_batch["angular_velocity_covariance"][0].as_py() == []
        assert imu_batch["temperature_celsius"][0].as_py() is None

        cpp_imu_model = Imu.from_arrow(cpp_imu.read_bytes())
        assert isinstance(cpp_imu_model.orientation, ImuOrientation)
        assert cpp_imu_model.orientation.qw == 2.0
        assert isinstance(cpp_imu_model.angular_velocity, ImuVector3)
        assert cpp_imu_model.angular_velocity.z == 0.3
        assert isinstance(cpp_imu_model.linear_acceleration, ImuVector3)
        assert cpp_imu_model.linear_acceleration.z == 9.8
        assert cpp_imu_model.temperature_celsius is None

        python_imu = _python_imu(Imu, ImuOrientation, ImuVector3)
        assert isinstance(python_imu.orientation, ImuOrientation)
        assert isinstance(python_imu.angular_velocity, ImuVector3)
        assert isinstance(python_imu.linear_acceleration, ImuVector3)
        python_imu_batch = python_imu.to_arrow()
        assert python_imu_batch.schema == imu_schema
        python_imu_columns = _columns(python_imu_batch)
        reordered_imu = _batch_from_columns(
            [
                *reversed(python_imu_columns),
                (
                    pa.field("extra", pa.uint8(), nullable=False),
                    pa.array([7], type=pa.uint8()),
                ),
            ]
        )
        py_imu = tmp_path / "py_imu.arrow"
        _write_ipc(reordered_imu, py_imu)
        output = subprocess.check_output([driver, "read-imu", py_imu], text=True).strip()
        assert output == "3 0.6 9.7 9 9 0 26.5"

        malformed_imus = [
            (
                "missing_temperature",
                _batch_from_columns(
                    _without_column(python_imu_columns, "temperature_celsius")
                ),
                ("missing", "temperature_celsius"),
            ),
            (
                "duplicate_angular_velocity",
                _batch_from_columns(
                    [
                        *python_imu_columns,
                        next(
                            column
                            for column in python_imu_columns
                            if column[0].name == "angular_velocity"
                        ),
                    ]
                ),
                ("angular_velocity", "exactly once"),
            ),
            (
                "wrong_temperature_type",
                _batch_from_columns(
                    _replace_column(
                        python_imu_columns,
                        "temperature_celsius",
                        pa.field("temperature_celsius", pa.float32(), nullable=True),
                        pa.array([26.5], type=pa.float32()),
                    )
                ),
                ("temperature_celsius", "physical type"),
            ),
            (
                "null_angular_velocity",
                _batch_from_columns(
                    _replace_column(
                        python_imu_columns,
                        "angular_velocity",
                        pa.field("angular_velocity", vector3, nullable=True),
                        pa.array([None], type=vector3),
                    )
                ),
                ("angular_velocity", "non-null struct"),
            ),
            (
                "null_angular_velocity_child",
                _batch_from_columns(
                    _replace_column(
                        python_imu_columns,
                        "angular_velocity",
                        pa.field("angular_velocity", vector3, nullable=False),
                        pa.array([{"x": None, "y": 0.5, "z": 0.6}], type=vector3),
                    )
                ),
                ("angular_velocity.x", "null"),
            ),
            (
                "null_orientation_child",
                _batch_from_columns(
                    _replace_column(
                        python_imu_columns,
                        "orientation",
                        pa.field("orientation", orientation, nullable=True),
                        pa.array(
                            [{"qx": None, "qy": 0.0, "qz": 0.0, "qw": 1.0}],
                            type=orientation,
                        ),
                    )
                ),
                ("orientation.qx", "null"),
            ),
            (
                "null_covariance_cell",
                _batch_from_columns(
                    _replace_column(
                        python_imu_columns,
                        "angular_velocity_covariance",
                        pa.field(
                            "angular_velocity_covariance", covariance, nullable=True
                        ),
                        pa.array([None], type=covariance),
                    )
                ),
                ("angular_velocity_covariance", "non-null list"),
            ),
            (
                "null_covariance_item",
                _batch_from_columns(
                    _replace_column(
                        python_imu_columns,
                        "angular_velocity_covariance",
                        pa.field(
                            "angular_velocity_covariance", covariance, nullable=False
                        ),
                        pa.array(
                            [[1.0, 0.0, 0.0, 0.0, None, 0.0, 0.0, 0.0, 1.0]],
                            type=covariance,
                        ),
                    )
                ),
                ("angular_velocity_covariance", "nulls"),
            ),
        ]
        for case_name, malformed, fragments in malformed_imus:
            _assert_rejected(
                driver,
                "read-imu",
                malformed,
                tmp_path / f"py_imu_{case_name}.arrow",
                fragments,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
