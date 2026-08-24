from __future__ import annotations

from typing import ClassVar, Literal, Self

import numpy as np
import pyarrow as pa
from pydantic import BaseModel, model_validator

from forge_msgs._arrow_read import (
    ArrowInput,
    normalize_single_row,
    required_field_indices,
)

_UINT32_MAX = 2**32 - 1
_UINT64_MAX = 2**64 - 1

PointFieldDatatype = Literal[
    "int8",
    "uint8",
    "int16",
    "uint16",
    "int32",
    "uint32",
    "int64",
    "uint64",
    "float32",
    "float64",
]
PointCloudByteOrder = Literal["little_endian", "big_endian"]

_DATATYPE_SIZE: dict[str, int] = {
    "int8": 1,
    "uint8": 1,
    "int16": 2,
    "uint16": 2,
    "int32": 4,
    "uint32": 4,
    "int64": 8,
    "uint64": 8,
    "float32": 4,
    "float64": 8,
}
_DATATYPE_NUMPY_CODE: dict[str, str] = {
    "int8": "i1",
    "uint8": "u1",
    "int16": "i2",
    "uint16": "u2",
    "int32": "i4",
    "uint32": "u4",
    "int64": "i8",
    "uint64": "u8",
    "float32": "f4",
    "float64": "f8",
}

_POINT_FIELD_TYPE = pa.struct(
    [
        pa.field("name", pa.string(), nullable=False),
        pa.field("offset", pa.uint32(), nullable=False),
        pa.field("datatype", pa.string(), nullable=False),
        pa.field("count", pa.uint32(), nullable=False),
    ]
)
_POINT_FIELDS_TYPE = pa.list_(pa.field("item", _POINT_FIELD_TYPE, nullable=True))
_POINT_CLOUD_BUFFER_ARROW_SCHEMA = pa.schema(
    [
        pa.field("width", pa.uint32(), nullable=False),
        pa.field("height", pa.uint32(), nullable=False),
        pa.field("is_dense", pa.bool_(), nullable=False),
        pa.field("byte_order", pa.string(), nullable=False),
        pa.field("point_stride", pa.uint32(), nullable=False),
        pa.field("row_stride", pa.uint64(), nullable=False),
        pa.field("fields", _POINT_FIELDS_TYPE, nullable=False),
        pa.field("data", pa.large_binary(), nullable=False),
    ]
)


class PointField(BaseModel):
    """One fixed-width field within a PointCloudBuffer point record."""

    name: str
    offset: int
    datatype: PointFieldDatatype
    count: int

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not self.name:
            raise ValueError("PointField name must be non-empty")
        try:
            self.name.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("PointField name must be valid UTF-8") from None
        if not 0 <= self.offset <= _UINT32_MAX:
            raise ValueError("PointField offset must be in the uint32 range")
        if not 1 <= self.count <= _UINT32_MAX:
            raise ValueError("PointField count must be in the positive uint32 range")
        return self


def _checked_mul_u64(left: int, right: int, expression: str) -> int:
    value = left * right
    if value > _UINT64_MAX:
        raise ValueError(f"PointCloudBuffer {expression} exceeds the uint64 range")
    return value


def _checked_add_u64(left: int, right: int, expression: str) -> int:
    value = left + right
    if value > _UINT64_MAX:
        raise ValueError(f"PointCloudBuffer {expression} exceeds the uint64 range")
    return value


def _validate_layout(
    *,
    width: int,
    height: int,
    point_stride: int,
    row_stride: int,
    fields: list[PointField],
    data_length: int,
) -> tuple[PointField, ...]:
    if not 0 <= width <= _UINT32_MAX:
        raise ValueError("PointCloudBuffer width must be in the uint32 range")
    if not 1 <= height <= _UINT32_MAX:
        raise ValueError("PointCloudBuffer height must be in the positive uint32 range")
    if not 1 <= point_stride <= _UINT32_MAX:
        raise ValueError(
            "PointCloudBuffer point_stride must be in the positive uint32 range"
        )
    if not 0 <= row_stride <= _UINT64_MAX:
        raise ValueError("PointCloudBuffer row_stride must be in the uint64 range")
    if width == 0:
        if height != 1:
            raise ValueError("PointCloudBuffer zero-width shape must use height=1")
        if row_stride != 0:
            raise ValueError("PointCloudBuffer zero-width shape must use row_stride=0")

    _checked_mul_u64(width, height, "width * height")
    minimum_row_stride = _checked_mul_u64(width, point_stride, "width * point_stride")
    if row_stride < minimum_row_stride:
        raise ValueError(
            "PointCloudBuffer row_stride must be at least width * point_stride"
        )
    expected_data_length = _checked_mul_u64(row_stride, height, "row_stride * height")
    if data_length != expected_data_length:
        raise ValueError(
            "PointCloudBuffer data length must equal row_stride * height "
            f"({expected_data_length}), got {data_length}"
        )

    if not fields:
        raise ValueError("PointCloudBuffer fields must not be empty")
    names = [field.name for field in fields]
    if len(set(names)) != len(names):
        raise ValueError("PointCloudBuffer field names must be unique")

    sorted_fields = tuple(sorted(fields, key=lambda field: (field.offset, field.name)))
    previous_field: PointField | None = None
    previous_end = 0
    for field in sorted_fields:
        field_size = _checked_mul_u64(
            _DATATYPE_SIZE[field.datatype],
            field.count,
            f"field {field.name!r} datatype_size * count",
        )
        field_end = _checked_add_u64(
            field.offset, field_size, f"field {field.name!r} end offset"
        )
        if field_end > point_stride:
            raise ValueError(
                f"PointCloudBuffer field {field.name!r} exceeds point_stride"
            )
        if previous_field is not None and field.offset < previous_end:
            raise ValueError(
                "PointCloudBuffer fields must not overlap: "
                f"{previous_field.name!r} and {field.name!r}"
            )
        previous_field = field
        previous_end = field_end

    fields_by_name = {field.name: field for field in sorted_fields}
    missing_xyz = [name for name in ("x", "y", "z") if name not in fields_by_name]
    if missing_xyz:
        raise ValueError(
            "PointCloudBuffer must contain scalar x, y, and z fields; missing "
            + ", ".join(missing_xyz)
        )
    xyz = tuple(fields_by_name[name] for name in ("x", "y", "z"))
    if any(field.count != 1 for field in xyz):
        raise ValueError("PointCloudBuffer x, y, and z fields must be scalar")
    xyz_datatypes = {field.datatype for field in xyz}
    if len(xyz_datatypes) != 1 or next(iter(xyz_datatypes)) not in {
        "float32",
        "float64",
    }:
        raise ValueError(
            "PointCloudBuffer x, y, and z fields must use the same float32 "
            "or float64 datatype"
        )
    return sorted_fields


def _numpy_dtype(datatype: str, byte_order: PointCloudByteOrder) -> np.dtype:
    prefix = "<" if byte_order == "little_endian" else ">"
    return np.dtype(prefix + _DATATYPE_NUMPY_CODE[datatype])


def _numpy_field_view(
    data: pa.Buffer | memoryview | bytes,
    *,
    width: int,
    height: int,
    point_stride: int,
    row_stride: int,
    byte_order: PointCloudByteOrder,
    descriptor: PointField,
) -> np.ndarray:
    dtype = _numpy_dtype(descriptor.datatype, byte_order)
    if height == 1:
        shape: tuple[int, ...] = (width,)
        strides: tuple[int, ...] = (point_stride,)
    else:
        shape = (height, width)
        strides = (row_stride, point_stride)
    if descriptor.count > 1:
        shape += (descriptor.count,)
        strides += (dtype.itemsize,)

    point_count = width * height
    offset = descriptor.offset if point_count else 0
    raw_data = memoryview(data).toreadonly()
    view = np.ndarray(
        shape=shape,
        dtype=dtype,
        buffer=raw_data,
        offset=offset,
        strides=strides,
    )
    view.setflags(write=False)
    return view


def _validate_dense_xyz(
    data: pa.Buffer | memoryview | bytes,
    *,
    width: int,
    height: int,
    point_stride: int,
    row_stride: int,
    byte_order: PointCloudByteOrder,
    fields: tuple[PointField, ...],
) -> None:
    if width == 0:
        return
    fields_by_name = {field.name: field for field in fields}
    for name in ("x", "y", "z"):
        values = _numpy_field_view(
            data,
            width=width,
            height=height,
            point_stride=point_stride,
            row_stride=row_stride,
            byte_order=byte_order,
            descriptor=fields_by_name[name],
        )
        if not np.isfinite(values).all():
            raise ValueError(
                "dense PointCloudBuffer values must contain finite XYZ components"
            )


def _canonical_little_endian_data(value: PointCloudBuffer) -> bytes:
    if value.byte_order == "little_endian":
        return value.data

    data = bytearray(value.data)
    for row in range(value.height):
        row_offset = row * value.row_stride
        for column in range(value.width):
            point_offset = row_offset + column * value.point_stride
            for field in value.fields:
                element_size = _DATATYPE_SIZE[field.datatype]
                if element_size == 1:
                    continue
                field_offset = point_offset + field.offset
                for element in range(field.count):
                    start = field_offset + element * element_size
                    end = start + element_size
                    data[start:end] = data[start:end][::-1]
    return bytes(data)


def _read_non_null_scalar(batch: pa.RecordBatch, index: int, name: str) -> object:
    cell = batch.column(index)[0]
    if not cell.is_valid:
        raise ValueError(f"PointCloudBuffer Arrow field {name} cell must not be null")
    return cell.as_py()


def _read_point_fields(batch: pa.RecordBatch, index: int) -> list[PointField]:
    cell = batch.column(index)[0]
    if not cell.is_valid:
        raise ValueError(
            "PointCloudBuffer Arrow field fields list cell must not be null"
        )
    values = cell.values
    if values.null_count:
        raise ValueError(
            "PointCloudBuffer Arrow field fields struct items must not be null"
        )
    for child_name in ("name", "offset", "datatype", "count"):
        if values.field(child_name).null_count:
            raise ValueError(
                "PointCloudBuffer Arrow field fields struct child "
                f"{child_name} must not be null"
            )
    return [PointField.model_validate(value) for value in values.to_pylist()]


def _read_data_buffer(batch: pa.RecordBatch, index: int) -> pa.Buffer:
    array = batch.column(index)
    if not array[0].is_valid:
        raise ValueError("PointCloudBuffer Arrow field data cell must not be null")

    offsets_buffer = array.buffers()[1]
    values_buffer = array.buffers()[2]
    if offsets_buffer is None or values_buffer is None:
        raise ValueError("PointCloudBuffer Arrow field data has missing buffers")
    offsets = pa.Array.from_buffers(
        pa.int64(), 2, [None, offsets_buffer], offset=array.offset
    )
    start = int(offsets[0].as_py())
    end = int(offsets[1].as_py())
    return values_buffer.slice(start, end - start)


class PointCloudBuffer(BaseModel):
    """Owned layout-preserving Cartesian point-record buffer."""

    _ARROW_SCHEMA: ClassVar[pa.Schema] = _POINT_CLOUD_BUFFER_ARROW_SCHEMA

    width: int
    height: int
    is_dense: bool
    byte_order: PointCloudByteOrder
    point_stride: int
    row_stride: int
    fields: list[PointField]
    data: bytes

    @model_validator(mode="after")
    def _validate(self) -> Self:
        sorted_fields = _validate_layout(
            width=self.width,
            height=self.height,
            point_stride=self.point_stride,
            row_stride=self.row_stride,
            fields=self.fields,
            data_length=len(self.data),
        )
        self.fields = list(sorted_fields)
        if self.is_dense:
            _validate_dense_xyz(
                self.data,
                width=self.width,
                height=self.height,
                point_stride=self.point_stride,
                row_stride=self.row_stride,
                byte_order=self.byte_order,
                fields=sorted_fields,
            )
        return self

    def to_arrow(self) -> pa.RecordBatch:
        validated = type(self).model_validate(self.model_dump(mode="python"))
        descriptors = [field.model_dump(mode="python") for field in validated.fields]
        canonical_data = _canonical_little_endian_data(validated)
        arrays: list[pa.Array] = [
            pa.array([validated.width], type=pa.uint32()),
            pa.array([validated.height], type=pa.uint32()),
            pa.array([validated.is_dense], type=pa.bool_()),
            pa.array(["little_endian"], type=pa.string()),
            pa.array([validated.point_stride], type=pa.uint32()),
            pa.array([validated.row_stride], type=pa.uint64()),
            pa.array([descriptors], type=_POINT_FIELDS_TYPE),
            pa.array([canonical_data], type=pa.large_binary()),
        ]
        return pa.RecordBatch.from_arrays(arrays, schema=self._ARROW_SCHEMA)

    @classmethod
    def from_arrow(cls, data: ArrowInput) -> PointCloudBuffer:
        return PointCloudBufferView.from_arrow(data).to_owned()


class PointCloudBufferView:
    """Validated metadata and read-only strided NumPy views over Arrow data."""

    __slots__ = (
        "_byte_order",
        "_data_buffer",
        "_field_by_name",
        "_fields",
        "_height",
        "_is_dense",
        "_point_stride",
        "_record_batch",
        "_row_stride",
        "_width",
    )

    _byte_order: PointCloudByteOrder
    _data_buffer: pa.Buffer
    _field_by_name: dict[str, PointField]
    _fields: tuple[PointField, ...]
    _height: int
    _is_dense: bool
    _point_stride: int
    _record_batch: pa.RecordBatch
    _row_stride: int
    _width: int

    def __init__(self) -> None:
        raise TypeError("use PointCloudBufferView.from_arrow()")

    @classmethod
    def from_arrow(cls, data: ArrowInput) -> PointCloudBufferView:
        batch = normalize_single_row(data, "PointCloudBuffer")
        indices = required_field_indices(
            batch, _POINT_CLOUD_BUFFER_ARROW_SCHEMA, "PointCloudBuffer"
        )
        width = int(_read_non_null_scalar(batch, indices["width"], "width"))
        height = int(_read_non_null_scalar(batch, indices["height"], "height"))
        is_dense = bool(_read_non_null_scalar(batch, indices["is_dense"], "is_dense"))
        byte_order = _read_non_null_scalar(batch, indices["byte_order"], "byte_order")
        if byte_order not in ("little_endian", "big_endian"):
            raise ValueError(
                "PointCloudBuffer byte_order must be 'little_endian' or 'big_endian'"
            )
        point_stride = int(
            _read_non_null_scalar(batch, indices["point_stride"], "point_stride")
        )
        row_stride = int(
            _read_non_null_scalar(batch, indices["row_stride"], "row_stride")
        )
        fields = _read_point_fields(batch, indices["fields"])
        data_buffer = _read_data_buffer(batch, indices["data"])
        sorted_fields = _validate_layout(
            width=width,
            height=height,
            point_stride=point_stride,
            row_stride=row_stride,
            fields=fields,
            data_length=data_buffer.size,
        )
        if is_dense:
            _validate_dense_xyz(
                data_buffer,
                width=width,
                height=height,
                point_stride=point_stride,
                row_stride=row_stride,
                byte_order=byte_order,
                fields=sorted_fields,
            )

        value = object.__new__(cls)
        value._record_batch = batch
        value._width = width
        value._height = height
        value._is_dense = is_dense
        value._byte_order = byte_order
        value._point_stride = point_stride
        value._row_stride = row_stride
        value._fields = sorted_fields
        value._field_by_name = {field.name: field for field in sorted_fields}
        value._data_buffer = data_buffer
        return value

    @property
    def record_batch(self) -> pa.RecordBatch:
        return self._record_batch

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def point_count(self) -> int:
        return self._width * self._height

    @property
    def is_dense(self) -> bool:
        return self._is_dense

    @property
    def byte_order(self) -> PointCloudByteOrder:
        return self._byte_order

    @property
    def point_stride(self) -> int:
        return self._point_stride

    @property
    def row_stride(self) -> int:
        return self._row_stride

    @property
    def fields(self) -> tuple[PointField, ...]:
        return tuple(field.model_copy(deep=True) for field in self._fields)

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self._fields)

    @property
    def raw_data(self) -> memoryview:
        return memoryview(self._data_buffer).toreadonly()

    def has_field(self, name: str) -> bool:
        return name in self._field_by_name

    def descriptor(self, name: str) -> PointField:
        return self._field_by_name[name].model_copy(deep=True)

    def field(self, name: str) -> np.ndarray:
        descriptor = self._field_by_name[name]
        return _numpy_field_view(
            self._data_buffer,
            width=self._width,
            height=self._height,
            point_stride=self._point_stride,
            row_stride=self._row_stride,
            byte_order=self._byte_order,
            descriptor=descriptor,
        )

    def validate_values(self) -> None:
        if self._is_dense:
            _validate_dense_xyz(
                self._data_buffer,
                width=self._width,
                height=self._height,
                point_stride=self._point_stride,
                row_stride=self._row_stride,
                byte_order=self._byte_order,
                fields=self._fields,
            )

    def to_owned(self) -> PointCloudBuffer:
        return PointCloudBuffer(
            width=self._width,
            height=self._height,
            is_dense=self._is_dense,
            byte_order=self._byte_order,
            point_stride=self._point_stride,
            row_stride=self._row_stride,
            fields=[field.model_copy(deep=True) for field in self._fields],
            data=bytes(self.raw_data),
        )
