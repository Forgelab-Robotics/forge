from __future__ import annotations

import math

import pyarrow as pa
import pytest
from pydantic import ValidationError

from forge_msgs import Imu, ImuOrientation, ImuVector3


def _ipc_bytes(batch: pa.RecordBatch) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    return sink.getvalue().to_pybytes()


def _replace_column(
    batch: pa.RecordBatch, name: str, column: pa.Array
) -> pa.RecordBatch:
    columns = list(batch.columns)
    columns[batch.schema.get_field_index(name)] = column
    return pa.RecordBatch.from_arrays(columns, names=batch.schema.names)


def _imu() -> Imu:
    return Imu(
        orientation=ImuOrientation(qx=0.0, qy=0.0, qz=0.0, qw=2.0),
        angular_velocity=ImuVector3(x=0.1, y=-0.2, z=0.3),
        linear_acceleration=ImuVector3(x=1.0, y=2.0, z=9.81),
        orientation_covariance=[
            1.0,
            0.1,
            0.0,
            0.1,
            2.0,
            0.0,
            0.0,
            0.0,
            3.0,
        ],
        angular_velocity_covariance=[],
        linear_acceleration_covariance=[
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
        temperature_celsius=24.5,
    )


def test_imu_uses_canonical_schema_and_round_trips_without_normalizing() -> None:
    orientation_type = pa.struct(
        [
            pa.field("qx", pa.float64(), nullable=False),
            pa.field("qy", pa.float64(), nullable=False),
            pa.field("qz", pa.float64(), nullable=False),
            pa.field("qw", pa.float64(), nullable=False),
        ]
    )
    vector_type = pa.struct(
        [
            pa.field("x", pa.float64(), nullable=False),
            pa.field("y", pa.float64(), nullable=False),
            pa.field("z", pa.float64(), nullable=False),
        ]
    )
    covariance_type = pa.list_(pa.float64())
    expected_schema = pa.schema(
        [
            pa.field("orientation", orientation_type, nullable=True),
            pa.field("angular_velocity", vector_type, nullable=False),
            pa.field("linear_acceleration", vector_type, nullable=False),
            pa.field("orientation_covariance", covariance_type, nullable=False),
            pa.field("angular_velocity_covariance", covariance_type, nullable=False),
            pa.field("linear_acceleration_covariance", covariance_type, nullable=False),
            pa.field("temperature_celsius", pa.float64(), nullable=True),
        ]
    )
    imu = _imu()

    batch = imu.to_arrow()

    assert batch.schema == expected_schema
    assert batch.num_rows == 1
    assert batch.schema.names == [
        "orientation",
        "angular_velocity",
        "linear_acceleration",
        "orientation_covariance",
        "angular_velocity_covariance",
        "linear_acceleration_covariance",
        "temperature_celsius",
    ]
    assert batch["orientation"][0]["qw"].as_py() == 2.0
    assert Imu.from_arrow(batch) == imu
    assert Imu.from_arrow(pa.Table.from_batches([batch])) == imu
    assert Imu.from_arrow(_ipc_bytes(batch)) == imu


def test_imu_null_orientation_and_temperature_use_arrow_nulls() -> None:
    imu = Imu(
        angular_velocity=ImuVector3(x=0.0, y=0.0, z=0.0),
        linear_acceleration=ImuVector3(x=0.0, y=0.0, z=9.81),
    )

    batch = imu.to_arrow()

    assert batch["orientation"].null_count == 1
    assert batch["temperature_celsius"].null_count == 1
    assert batch["orientation_covariance"][0].as_py() == []
    assert Imu.from_arrow(batch) == imu


@pytest.mark.parametrize(
    ("orientation", "match"),
    [
        (ImuOrientation, "quaternion must not be all zero"),
    ],
)
def test_imu_orientation_rejects_zero_quaternion(
    orientation: type[ImuOrientation], match: str
) -> None:
    with pytest.raises((ValueError, ValidationError), match=match):
        orientation(qx=0.0, qy=0.0, qz=0.0, qw=0.0)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_imu_requires_finite_vectors_orientation_and_temperature(value: float) -> None:
    with pytest.raises((ValueError, ValidationError), match="vector components"):
        ImuVector3(x=value, y=0.0, z=0.0)
    with pytest.raises((ValueError, ValidationError), match="orientation components"):
        ImuOrientation(qx=value, qy=0.0, qz=0.0, qw=1.0)
    with pytest.raises((ValueError, ValidationError), match="temperature_celsius"):
        Imu(
            angular_velocity=ImuVector3(x=0.0, y=0.0, z=0.0),
            linear_acceleration=ImuVector3(x=0.0, y=0.0, z=0.0),
            temperature_celsius=value,
        )


@pytest.mark.parametrize(
    ("covariance", "match"),
    [
        ([0.0], "exactly 9"),
        ([0.0] * 8 + [math.nan], "finite"),
        ([-1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "non-negative"),
        ([0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0], "non-negative"),
        ([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0], "non-negative"),
    ],
)
def test_imu_covariance_rules(covariance: list[float], match: str) -> None:
    with pytest.raises((ValueError, ValidationError), match=match):
        Imu(
            orientation=ImuOrientation(qx=0.0, qy=0.0, qz=0.0, qw=1.0),
            angular_velocity=ImuVector3(x=0.0, y=0.0, z=0.0),
            linear_acceleration=ImuVector3(x=0.0, y=0.0, z=0.0),
            angular_velocity_covariance=covariance,
        )


def test_imu_allows_negative_off_diagonal_covariance_values() -> None:
    covariance = [1.0, -0.5, 0.0, -0.5, 2.0, 0.0, 0.0, 0.0, 3.0]
    imu = Imu(
        angular_velocity=ImuVector3(x=0.0, y=0.0, z=0.0),
        linear_acceleration=ImuVector3(x=0.0, y=0.0, z=0.0),
        angular_velocity_covariance=covariance,
    )
    assert imu.angular_velocity_covariance == covariance


def test_imu_orientation_covariance_requires_orientation() -> None:
    with pytest.raises((ValueError, ValidationError), match="when orientation is null"):
        Imu(
            angular_velocity=ImuVector3(x=0.0, y=0.0, z=0.0),
            linear_acceleration=ImuVector3(x=0.0, y=0.0, z=0.0),
            orientation_covariance=[0.0] * 9,
        )


def test_imu_reader_accepts_reorder_and_extras() -> None:
    imu = _imu()
    canonical = imu.to_arrow()
    names = list(reversed(canonical.schema.names))
    payload = pa.RecordBatch.from_arrays(
        [pa.array(["ignored"])] + [canonical[name] for name in names],
        names=["frame_id"] + names,
    )

    assert Imu.from_arrow(payload) == imu


def test_imu_reader_rejects_missing_duplicate_wrong_type_and_null_required_fields() -> (
    None
):
    canonical = _imu().to_arrow()

    missing = canonical.select(
        [name for name in canonical.schema.names if name != "temperature_celsius"]
    )
    with pytest.raises(
        ValueError, match="missing required fields: temperature_celsius"
    ):
        Imu.from_arrow(missing)

    duplicate = pa.RecordBatch.from_arrays(
        [*canonical.columns, canonical["orientation"]],
        names=[*canonical.schema.names, "orientation"],
    )
    with pytest.raises(ValueError, match="orientation must appear exactly once"):
        Imu.from_arrow(duplicate)

    wrong_vector_type = pa.struct(
        [
            pa.field("x", pa.float32()),
            pa.field("y", pa.float32()),
            pa.field("z", pa.float32()),
        ]
    )
    wrong_type = _replace_column(
        canonical,
        "angular_velocity",
        pa.array([{"x": 1.0, "y": 2.0, "z": 3.0}], type=wrong_vector_type),
    )
    with pytest.raises(TypeError, match="angular_velocity must have type"):
        Imu.from_arrow(wrong_type)

    null_required = _replace_column(
        canonical,
        "linear_acceleration",
        pa.array([None], type=canonical.schema.field("linear_acceleration").type),
    )
    with pytest.raises(ValueError, match="linear_acceleration struct cell"):
        Imu.from_arrow(null_required)


def test_imu_reader_rejects_null_struct_and_covariance_children() -> None:
    canonical = _imu().to_arrow()
    nullable_vector = pa.struct(
        [
            pa.field("x", pa.float64()),
            pa.field("y", pa.float64()),
            pa.field("z", pa.float64()),
        ]
    )
    null_vector_child = _replace_column(
        canonical,
        "angular_velocity",
        pa.array([{"x": None, "y": 0.0, "z": 0.0}], type=nullable_vector),
    )
    with pytest.raises(ValueError, match="struct child x must not be null"):
        Imu.from_arrow(null_vector_child)

    null_covariance = _replace_column(
        canonical,
        "angular_velocity_covariance",
        pa.array([None], type=pa.list_(pa.float64())),
    )
    with pytest.raises(ValueError, match="list cell must not be null"):
        Imu.from_arrow(null_covariance)

    null_covariance_item = _replace_column(
        canonical,
        "angular_velocity_covariance",
        pa.array([[0.0, None, 0.0]], type=pa.list_(pa.float64())),
    )
    with pytest.raises(ValueError, match="list items must not be null"):
        Imu.from_arrow(null_covariance_item)


def test_imu_reader_enforces_semantics_after_decoding() -> None:
    canonical = _imu().to_arrow()
    null_orientation = _replace_column(
        canonical,
        "orientation",
        pa.array([None], type=canonical.schema.field("orientation").type),
    )
    with pytest.raises(ValueError, match="when orientation is null"):
        Imu.from_arrow(null_orientation)

    nan_temperature = _replace_column(
        canonical, "temperature_celsius", pa.array([math.nan], type=pa.float64())
    )
    with pytest.raises(ValueError, match="temperature_celsius"):
        Imu.from_arrow(nan_temperature)


def test_imu_reader_enforces_row_and_ipc_framing() -> None:
    canonical = _imu().to_arrow()
    with pytest.raises(ValueError, match="exactly one row, got 0"):
        Imu.from_arrow(canonical.slice(0, 0))

    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, canonical.schema) as writer:
        writer.write_batch(canonical)
        writer.write_batch(canonical)
    with pytest.raises(ValueError, match="exactly one RecordBatch"):
        Imu.from_arrow(sink.getvalue().to_pybytes())

    with pytest.raises(ValueError, match="trailing bytes"):
        Imu.from_arrow(_ipc_bytes(canonical) + b"JUNK")
