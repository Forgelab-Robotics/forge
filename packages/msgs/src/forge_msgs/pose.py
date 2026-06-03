from __future__ import annotations

import math
from typing import Self

import pyarrow as pa
from pydantic import BaseModel, model_validator

from forge_msgs.arrow import ensure_record_batch


def _validate_quaternion(qx: float, qy: float, qz: float, qw: float) -> None:
    if qx == 0.0 and qy == 0.0 and qz == 0.0 and qw == 0.0:
        raise ValueError("quaternion must not be all zero")


def _float_list(values: list[float]) -> pa.Array:
    return pa.array([values], type=pa.list_(pa.float64()))


def _str_list(values: list[str]) -> pa.Array:
    return pa.array([values], type=pa.list_(pa.string()))


def _read_float_list(batch: pa.RecordBatch, field: str) -> list[float]:
    values = batch[field][0].as_py()
    return [float(value) for value in values]


class Pose(BaseModel):
    """Header-less 3D pose payload with position and quaternion orientation."""

    x: float
    y: float
    z: float = 0.0
    qx: float = 0.0
    qy: float = 0.0
    qz: float = 0.0
    qw: float = 1.0

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _validate_quaternion(self.qx, self.qy, self.qz, self.qw)
        return self

    @classmethod
    def from_xy_yaw(cls, x: float, y: float, yaw: float, z: float = 0.0) -> "Pose":
        half = yaw * 0.5
        return cls(
            x=x,
            y=y,
            z=z,
            qx=0.0,
            qy=0.0,
            qz=math.sin(half),
            qw=math.cos(half),
        )

    def to_xy_yaw(self) -> tuple[float, float, float]:
        # Standard yaw extraction from quaternion around Z for planar use.
        yaw = math.atan2(
            2.0 * (self.qw * self.qz + self.qx * self.qy),
            1.0 - 2.0 * (self.qy * self.qy + self.qz * self.qz),
        )
        return self.x, self.y, yaw

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "x": pa.array([self.x], type=pa.float64()),
                "y": pa.array([self.y], type=pa.float64()),
                "z": pa.array([self.z], type=pa.float64()),
                "qx": pa.array([self.qx], type=pa.float64()),
                "qy": pa.array([self.qy], type=pa.float64()),
                "qz": pa.array([self.qz], type=pa.float64()),
                "qw": pa.array([self.qw], type=pa.float64()),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "Pose":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("Pose RecordBatch must contain one row")
        return cls(
            x=float(batch["x"][0].as_py()),
            y=float(batch["y"][0].as_py()),
            z=float(batch["z"][0].as_py()),
            qx=float(batch["qx"][0].as_py()),
            qy=float(batch["qy"][0].as_py()),
            qz=float(batch["qz"][0].as_py()),
            qw=float(batch["qw"][0].as_py()),
        )


class PoseSet(BaseModel):
    """Single-row named collection of poses."""

    name: list[str]
    x: list[float]
    y: list[float]
    z: list[float]
    qx: list[float]
    qy: list[float]
    qz: list[float]
    qw: list[float]

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not self.name:
            raise ValueError("name must contain at least one pose")
        if len(set(self.name)) != len(self.name):
            raise ValueError("name items must be unique")
        for field in ("x", "y", "z", "qx", "qy", "qz", "qw"):
            values = getattr(self, field)
            if len(values) != len(self.name):
                raise ValueError(f"{field} must have the same length as name")
        for values in zip(self.qx, self.qy, self.qz, self.qw, strict=True):
            _validate_quaternion(*values)
        return self

    @classmethod
    def from_poses(cls, poses: dict[str, Pose]) -> "PoseSet":
        names = sorted(poses)
        return cls(
            name=names,
            x=[poses[name].x for name in names],
            y=[poses[name].y for name in names],
            z=[poses[name].z for name in names],
            qx=[poses[name].qx for name in names],
            qy=[poses[name].qy for name in names],
            qz=[poses[name].qz for name in names],
            qw=[poses[name].qw for name in names],
        )

    def to_poses(self) -> dict[str, Pose]:
        return {
            name: Pose(
                x=self.x[i],
                y=self.y[i],
                z=self.z[i],
                qx=self.qx[i],
                qy=self.qy[i],
                qz=self.qz[i],
                qw=self.qw[i],
            )
            for i, name in enumerate(self.name)
        }

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "name": _str_list(self.name),
                "x": _float_list(self.x),
                "y": _float_list(self.y),
                "z": _float_list(self.z),
                "qx": _float_list(self.qx),
                "qy": _float_list(self.qy),
                "qz": _float_list(self.qz),
                "qw": _float_list(self.qw),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "PoseSet":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("PoseSet RecordBatch must contain one row")
        return cls(
            name=list(batch["name"][0].as_py() or []),
            x=_read_float_list(batch, "x"),
            y=_read_float_list(batch, "y"),
            z=_read_float_list(batch, "z"),
            qx=_read_float_list(batch, "qx"),
            qy=_read_float_list(batch, "qy"),
            qz=_read_float_list(batch, "qz"),
            qw=_read_float_list(batch, "qw"),
        )
