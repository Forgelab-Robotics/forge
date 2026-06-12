from __future__ import annotations

import math
from typing import Self

import pyarrow as pa
from pydantic import BaseModel, Field, model_validator

from forge_msgs.arrow import ensure_record_batch

_UINT32_MAX = 2**32 - 1


def _list_array(values: list, value_type: pa.DataType) -> pa.Array:
    return pa.array([values], type=pa.list_(value_type))


def _read_list(batch: pa.RecordBatch, name: str) -> list:
    return list(batch[name][0].as_py() or [])


class PointCloud(BaseModel):
    """Organized or unorganized XYZ point cloud."""

    width: int
    height: int
    is_dense: bool
    x: list[float]
    y: list[float]
    z: list[float]
    intensity: list[float] = Field(default_factory=list)
    red: list[int] = Field(default_factory=list)
    green: list[int] = Field(default_factory=list)
    blue: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not 0 <= self.width <= _UINT32_MAX or not 0 <= self.height <= _UINT32_MAX:
            raise ValueError("width and height must be in the uint32 range")
        point_count = len(self.x)
        if len(self.y) != point_count or len(self.z) != point_count:
            raise ValueError("x, y, and z must have the same length")
        if self.width * self.height != point_count:
            raise ValueError("width * height must equal the point count")
        for name in ("intensity", "red", "green", "blue"):
            values = getattr(self, name)
            if values and len(values) != point_count:
                raise ValueError(f"{name} must be empty or have the same length as x")
        for name in ("red", "green", "blue"):
            if any(value < 0 or value > 255 for value in getattr(self, name)):
                raise ValueError(f"{name} values must be in the range [0, 255]")
        populated_rgb = [bool(self.red), bool(self.green), bool(self.blue)]
        if any(populated_rgb) and not all(populated_rgb):
            raise ValueError("red, green, and blue must all be empty or all be populated")
        if self.is_dense and any(
            not math.isfinite(value) for values in (self.x, self.y, self.z) for value in values
        ):
            raise ValueError("dense point clouds must contain finite XYZ values")
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "width": pa.array([self.width], type=pa.uint32()),
                "height": pa.array([self.height], type=pa.uint32()),
                "is_dense": pa.array([self.is_dense], type=pa.bool_()),
                "x": _list_array(self.x, pa.float32()),
                "y": _list_array(self.y, pa.float32()),
                "z": _list_array(self.z, pa.float32()),
                "intensity": _list_array(self.intensity, pa.float32()),
                "red": _list_array(self.red, pa.uint8()),
                "green": _list_array(self.green, pa.uint8()),
                "blue": _list_array(self.blue, pa.uint8()),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "PointCloud":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("PointCloud RecordBatch must contain one row")
        return cls(
            width=int(batch["width"][0].as_py()),
            height=int(batch["height"][0].as_py()),
            is_dense=bool(batch["is_dense"][0].as_py()),
            x=_read_list(batch, "x"),
            y=_read_list(batch, "y"),
            z=_read_list(batch, "z"),
            intensity=_read_list(batch, "intensity"),
            red=_read_list(batch, "red"),
            green=_read_list(batch, "green"),
            blue=_read_list(batch, "blue"),
        )
