from __future__ import annotations

import math
from typing import ClassVar, Self, TypeVar

import pyarrow as pa
from pydantic import BaseModel, Field, model_validator

from forge_msgs.arrow import ensure_record_batch

_UINT32_MAX = 2**32 - 1
_FLOAT32_MAX = float.fromhex("0x1.fffffep+127")
_ListItemT = TypeVar("_ListItemT", float, int)


def _required_field_indices(
    batch: pa.RecordBatch, schema: pa.Schema
) -> dict[str, int]:
    missing = [field.name for field in schema if field.name not in batch.schema.names]
    if missing:
        raise ValueError(
            "PointCloud RecordBatch is missing required fields: " + ", ".join(missing)
        )

    indices: dict[str, int] = {}
    for expected_field in schema:
        matching_indices = [
            index
            for index, name in enumerate(batch.schema.names)
            if name == expected_field.name
        ]
        if len(matching_indices) != 1:
            raise ValueError(
                f"PointCloud RecordBatch field {expected_field.name} must appear "
                f"exactly once, got {len(matching_indices)}"
            )
        index = matching_indices[0]
        actual_type = batch.schema.field(index).type
        types_match = actual_type == expected_field.type
        if pa.types.is_list(expected_field.type):
            types_match = (
                pa.types.is_list(actual_type)
                and actual_type.value_type == expected_field.type.value_type
            )
        if not types_match:
            raise TypeError(
                f"PointCloud Arrow field {expected_field.name} must have type "
                f"{expected_field.type}, got {actual_type}"
            )
        indices[expected_field.name] = index
    return indices


def _read_scalar(batch: pa.RecordBatch, index: int, name: str) -> int | bool:
    cell = batch.column(index)[0]
    if not cell.is_valid:
        raise ValueError(f"PointCloud Arrow field {name} cell must not be null")
    return cell.as_py()


def _read_list(
    batch: pa.RecordBatch,
    index: int,
    name: str,
    item_type: type[_ListItemT],
) -> list[_ListItemT]:
    cell = batch.column(index)[0]
    if not cell.is_valid:
        raise ValueError(f"PointCloud Arrow field {name} list cell must not be null")
    values = cell.values
    if values.null_count:
        raise ValueError(f"PointCloud Arrow field {name} list items must not be null")
    return [item_type(value) for value in values.to_pylist()]


class PointCloud(BaseModel):
    """Organized or unorganized XYZ point cloud.

    Instances are validated at construction and should be treated as immutable
    message values. Build a new instance instead of mutating fields in place.
    """

    _ARROW_SCHEMA: ClassVar[pa.Schema] = pa.schema(
        [
            pa.field("width", pa.uint32(), nullable=False),
            pa.field("height", pa.uint32(), nullable=False),
            pa.field("is_dense", pa.bool_(), nullable=False),
            pa.field("x", pa.list_(pa.float32()), nullable=False),
            pa.field("y", pa.list_(pa.float32()), nullable=False),
            pa.field("z", pa.list_(pa.float32()), nullable=False),
            pa.field("intensity", pa.list_(pa.float32()), nullable=False),
            pa.field("red", pa.list_(pa.uint8()), nullable=False),
            pa.field("green", pa.list_(pa.uint8()), nullable=False),
            pa.field("blue", pa.list_(pa.uint8()), nullable=False),
        ]
    )

    width: int | None = None
    height: int | None = None
    is_dense: bool | None = None
    x: list[float]
    y: list[float]
    z: list[float]
    intensity: list[float] = Field(default_factory=list)
    red: list[int] = Field(default_factory=list)
    green: list[int] = Field(default_factory=list)
    blue: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        point_count = len(self.x)
        if len(self.y) != point_count or len(self.z) != point_count:
            raise ValueError("x, y, and z must have the same length")
        if self.height is None:
            self.height = 1
        if self.width is None:
            if self.height == 0:
                self.width = 0
            elif point_count % self.height == 0:
                self.width = point_count // self.height
            else:
                raise ValueError("point count must be divisible by height when width is omitted")
        if not 0 <= self.width <= _UINT32_MAX or not 0 <= self.height <= _UINT32_MAX:
            raise ValueError("width and height must be in the uint32 range")
        if self.width * self.height != point_count:
            raise ValueError("width * height must equal the point count")
        for name in ("intensity", "red", "green", "blue"):
            values = getattr(self, name)
            if values and len(values) != point_count:
                raise ValueError(f"{name} must be empty or have the same length as x")
        for name in ("red", "green", "blue"):
            if any(value < 0 or value > 255 for value in getattr(self, name)):
                raise ValueError(f"{name} values must be in the range [0, 255]")
        xyz_is_finite = True
        for name in ("x", "y", "z"):
            for value in getattr(self, name):
                finite = math.isfinite(value)
                xyz_is_finite = xyz_is_finite and finite
                if finite and abs(value) > _FLOAT32_MAX:
                    raise ValueError(
                        f"{name} contains a finite value outside the float32 range"
                    )
        for value in self.intensity:
            if math.isfinite(value) and abs(value) > _FLOAT32_MAX:
                raise ValueError(
                    "intensity contains a finite value outside the float32 range"
                )
        populated_rgb = [bool(self.red), bool(self.green), bool(self.blue)]
        if any(populated_rgb) and not all(populated_rgb):
            raise ValueError("red, green, and blue must all be empty or all be populated")
        if self.is_dense is None:
            self.is_dense = xyz_is_finite
        elif self.is_dense and not xyz_is_finite:
            raise ValueError("dense point clouds must contain finite XYZ values")
        return self

    def to_arrow(self) -> pa.RecordBatch:
        arrays = [
            pa.array([getattr(self, field.name)], type=field.type)
            for field in self._ARROW_SCHEMA
        ]
        return pa.RecordBatch.from_arrays(arrays, schema=self._ARROW_SCHEMA)

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "PointCloud":
        if isinstance(data, bytes):
            reader = pa.ipc.open_stream(data)
            try:
                batch = reader.read_next_batch()
            except StopIteration:
                raise ValueError(
                    "PointCloud IPC stream must contain exactly one RecordBatch"
                ) from None
            try:
                reader.read_next_batch()
            except StopIteration:
                pass
            else:
                raise ValueError(
                    "PointCloud IPC stream must contain exactly one RecordBatch"
                )
        elif isinstance(data, pa.Table):
            if data.num_rows != 1:
                raise ValueError(
                    "PointCloud RecordBatch must contain exactly one row, "
                    f"got {data.num_rows}"
                )
            combined = data.combine_chunks()
            batch = pa.RecordBatch.from_arrays(
                [column.chunk(0) for column in combined.columns],
                schema=combined.schema,
            )
        else:
            batch = ensure_record_batch(data)
        if batch.num_rows != 1:
            raise ValueError(
                "PointCloud RecordBatch must contain exactly one row, "
                f"got {batch.num_rows}"
            )
        if isinstance(data, pa.StructArray) and data.null_count:
            raise ValueError("PointCloud StructArray row must not be null")
        indices = _required_field_indices(batch, cls._ARROW_SCHEMA)
        return cls(
            width=int(_read_scalar(batch, indices["width"], "width")),
            height=int(_read_scalar(batch, indices["height"], "height")),
            is_dense=bool(_read_scalar(batch, indices["is_dense"], "is_dense")),
            x=_read_list(batch, indices["x"], "x", float),
            y=_read_list(batch, indices["y"], "y", float),
            z=_read_list(batch, indices["z"], "z", float),
            intensity=_read_list(
                batch, indices["intensity"], "intensity", float
            ),
            red=_read_list(batch, indices["red"], "red", int),
            green=_read_list(batch, indices["green"], "green", int),
            blue=_read_list(batch, indices["blue"], "blue", int),
        )
