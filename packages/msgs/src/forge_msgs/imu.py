from __future__ import annotations

import math
from typing import ClassVar, Self

import pyarrow as pa
from pydantic import BaseModel, Field, model_validator

from forge_msgs._arrow_read import (
    ArrowInput,
    normalize_single_row,
    required_field_indices,
)

_ORIENTATION_TYPE = pa.struct(
    [
        pa.field("qx", pa.float64(), nullable=False),
        pa.field("qy", pa.float64(), nullable=False),
        pa.field("qz", pa.float64(), nullable=False),
        pa.field("qw", pa.float64(), nullable=False),
    ]
)
_VECTOR3_TYPE = pa.struct(
    [
        pa.field("x", pa.float64(), nullable=False),
        pa.field("y", pa.float64(), nullable=False),
        pa.field("z", pa.float64(), nullable=False),
    ]
)
_COVARIANCE_TYPE = pa.list_(pa.float64())
_IMU_ARROW_SCHEMA = pa.schema(
    [
        pa.field("orientation", _ORIENTATION_TYPE, nullable=True),
        pa.field("angular_velocity", _VECTOR3_TYPE, nullable=False),
        pa.field("linear_acceleration", _VECTOR3_TYPE, nullable=False),
        pa.field("orientation_covariance", _COVARIANCE_TYPE, nullable=False),
        pa.field("angular_velocity_covariance", _COVARIANCE_TYPE, nullable=False),
        pa.field("linear_acceleration_covariance", _COVARIANCE_TYPE, nullable=False),
        pa.field("temperature_celsius", pa.float64(), nullable=True),
    ]
)


class ImuOrientation(BaseModel):
    """Quaternion orientation with explicitly named XYZW components."""

    qx: float
    qy: float
    qz: float
    qw: float

    @model_validator(mode="after")
    def _validate(self) -> Self:
        values = (self.qx, self.qy, self.qz, self.qw)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("Imu orientation components must be finite")
        if all(value == 0.0 for value in values):
            raise ValueError("Imu orientation quaternion must not be all zero")
        return self


class ImuVector3(BaseModel):
    """Three-axis SI-unit inertial vector."""

    x: float
    y: float
    z: float

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if any(not math.isfinite(value) for value in (self.x, self.y, self.z)):
            raise ValueError("Imu vector components must be finite")
        return self


def _validate_covariance(name: str, values: list[float]) -> None:
    if len(values) not in (0, 9):
        raise ValueError(f"Imu {name} must be empty or contain exactly 9 values")
    if any(not math.isfinite(value) for value in values):
        raise ValueError(f"Imu {name} values must be finite")
    if values and any(values[index] < 0.0 for index in (0, 4, 8)):
        raise ValueError(f"Imu {name} diagonal values must be non-negative")


def _read_struct(
    batch: pa.RecordBatch,
    index: int,
    name: str,
    child_names: tuple[str, ...],
    *,
    nullable: bool,
) -> dict[str, float] | None:
    cell = batch.column(index)[0]
    if not cell.is_valid:
        if nullable:
            return None
        raise ValueError(f"Imu Arrow field {name} struct cell must not be null")

    values: dict[str, float] = {}
    for child_name in child_names:
        child = cell[child_name]
        if not child.is_valid:
            raise ValueError(
                f"Imu Arrow field {name} struct child {child_name} must not be null"
            )
        values[child_name] = float(child.as_py())
    return values


def _read_covariance(batch: pa.RecordBatch, index: int, name: str) -> list[float]:
    cell = batch.column(index)[0]
    if not cell.is_valid:
        raise ValueError(f"Imu Arrow field {name} list cell must not be null")
    values = cell.values
    if values.null_count:
        raise ValueError(f"Imu Arrow field {name} list items must not be null")
    return [float(value) for value in values.to_pylist()]


def _read_optional_float(batch: pa.RecordBatch, index: int) -> float | None:
    cell = batch.column(index)[0]
    if not cell.is_valid:
        return None
    return float(cell.as_py())


class Imu(BaseModel):
    """Single SI-unit inertial measurement sample."""

    _ARROW_SCHEMA: ClassVar[pa.Schema] = _IMU_ARROW_SCHEMA

    orientation: ImuOrientation | None = None
    angular_velocity: ImuVector3
    linear_acceleration: ImuVector3
    orientation_covariance: list[float] = Field(default_factory=list)
    angular_velocity_covariance: list[float] = Field(default_factory=list)
    linear_acceleration_covariance: list[float] = Field(default_factory=list)
    temperature_celsius: float | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _validate_covariance("orientation_covariance", self.orientation_covariance)
        _validate_covariance(
            "angular_velocity_covariance", self.angular_velocity_covariance
        )
        _validate_covariance(
            "linear_acceleration_covariance", self.linear_acceleration_covariance
        )
        if self.orientation is None and self.orientation_covariance:
            raise ValueError(
                "Imu orientation_covariance must be empty when orientation is null"
            )
        if self.temperature_celsius is not None and not math.isfinite(
            self.temperature_celsius
        ):
            raise ValueError("Imu temperature_celsius must be finite when present")
        return self

    def to_arrow(self) -> pa.RecordBatch:
        validated = type(self).model_validate(self.model_dump(mode="python"))
        orientation = (
            None
            if validated.orientation is None
            else validated.orientation.model_dump(mode="python")
        )
        arrays: list[pa.Array] = [
            pa.array([orientation], type=_ORIENTATION_TYPE),
            pa.array(
                [validated.angular_velocity.model_dump(mode="python")],
                type=_VECTOR3_TYPE,
            ),
            pa.array(
                [validated.linear_acceleration.model_dump(mode="python")],
                type=_VECTOR3_TYPE,
            ),
            pa.array([validated.orientation_covariance], type=_COVARIANCE_TYPE),
            pa.array([validated.angular_velocity_covariance], type=_COVARIANCE_TYPE),
            pa.array([validated.linear_acceleration_covariance], type=_COVARIANCE_TYPE),
            pa.array([validated.temperature_celsius], type=pa.float64()),
        ]
        return pa.RecordBatch.from_arrays(arrays, schema=self._ARROW_SCHEMA)

    @classmethod
    def from_arrow(cls, data: ArrowInput) -> Imu:
        batch = normalize_single_row(data, "Imu")
        indices = required_field_indices(batch, _IMU_ARROW_SCHEMA, "Imu")
        orientation_values = _read_struct(
            batch,
            indices["orientation"],
            "orientation",
            ("qx", "qy", "qz", "qw"),
            nullable=True,
        )
        angular_velocity_values = _read_struct(
            batch,
            indices["angular_velocity"],
            "angular_velocity",
            ("x", "y", "z"),
            nullable=False,
        )
        linear_acceleration_values = _read_struct(
            batch,
            indices["linear_acceleration"],
            "linear_acceleration",
            ("x", "y", "z"),
            nullable=False,
        )
        assert angular_velocity_values is not None
        assert linear_acceleration_values is not None
        return cls(
            orientation=(
                None
                if orientation_values is None
                else ImuOrientation.model_validate(orientation_values)
            ),
            angular_velocity=ImuVector3.model_validate(angular_velocity_values),
            linear_acceleration=ImuVector3.model_validate(linear_acceleration_values),
            orientation_covariance=_read_covariance(
                batch,
                indices["orientation_covariance"],
                "orientation_covariance",
            ),
            angular_velocity_covariance=_read_covariance(
                batch,
                indices["angular_velocity_covariance"],
                "angular_velocity_covariance",
            ),
            linear_acceleration_covariance=_read_covariance(
                batch,
                indices["linear_acceleration_covariance"],
                "linear_acceleration_covariance",
            ),
            temperature_celsius=_read_optional_float(
                batch, indices["temperature_celsius"]
            ),
        )
