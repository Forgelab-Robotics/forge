from __future__ import annotations

import math
from numbers import Integral
from typing import ClassVar, Literal, Self, TypeVar

import numpy as np
import pyarrow as pa
from pydantic import BaseModel, Field, model_validator

from forge_msgs.arrow import ensure_record_batch

_UINT32_MAX = 2**32 - 1
_LIST_OFFSET_MAX = 2**31 - 1
_FLOAT32_MAX = float.fromhex("0x1.fffffep+127")
_ListItemT = TypeVar("_ListItemT", float, int)

PointCloudCopyPolicy = Literal["always", "if_needed", "never"]
PointCloudCastingPolicy = Literal["no", "safe", "same_kind"]
PointCloudRgbInput = np.ndarray | tuple[np.ndarray, np.ndarray, np.ndarray]

_POINT_CLOUD_ARROW_SCHEMA = pa.schema(
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


def _read_list_values(batch: pa.RecordBatch, index: int, name: str) -> pa.Array:
    cell = batch.column(index)[0]
    if not cell.is_valid:
        raise ValueError(f"PointCloud Arrow field {name} list cell must not be null")
    values = cell.values
    if values.null_count:
        raise ValueError(f"PointCloud Arrow field {name} list items must not be null")
    return values


def _read_list(
    batch: pa.RecordBatch,
    index: int,
    name: str,
    item_type: type[_ListItemT],
) -> list[_ListItemT]:
    values = _read_list_values(batch, index, name)
    return [item_type(value) for value in values.to_pylist()]


def _normalize_point_cloud_batch(
    data: pa.RecordBatch | pa.Table | pa.StructArray | bytes,
) -> pa.RecordBatch:
    if isinstance(data, bytes):
        source = pa.BufferReader(data)
        reader = pa.ipc.open_stream(source)
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
        if source.tell() != len(data):
            raise ValueError("PointCloud IPC stream must not contain trailing bytes")
    elif isinstance(data, pa.Table):
        if data.num_rows != 1:
            raise ValueError(
                "PointCloud RecordBatch must contain exactly one row, "
                f"got {data.num_rows}"
            )
        arrays: list[pa.Array] = []
        for column in data.columns:
            non_empty = [chunk for chunk in column.chunks if len(chunk)]
            if len(non_empty) != 1:
                raise ValueError(
                    "PointCloud single-row Table columns must contain one value"
                )
            arrays.append(non_empty[0])
        batch = pa.RecordBatch.from_arrays(arrays, schema=data.schema)
    else:
        batch = ensure_record_batch(data)
    if batch.num_rows != 1:
        raise ValueError(
            "PointCloud RecordBatch must contain exactly one row, "
            f"got {batch.num_rows}"
        )
    if isinstance(data, pa.StructArray) and data.null_count:
        raise ValueError("PointCloud StructArray row must not be null")
    return batch


def _validate_copy_policy(copy: PointCloudCopyPolicy) -> None:
    if copy not in ("always", "if_needed", "never"):
        raise ValueError(
            "PointCloud copy policy must be 'always', 'if_needed', or 'never'"
        )


def _validate_casting_policy(casting: PointCloudCastingPolicy) -> None:
    if casting not in ("no", "safe", "same_kind"):
        raise ValueError(
            "PointCloud casting policy must be 'no', 'safe', or 'same_kind'"
        )


def _normalize_numpy_array(value: np.ndarray, *, name: str) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise TypeError(f"PointCloud {name} must be a numpy.ndarray")
    if isinstance(value, np.ma.MaskedArray):
        raise TypeError(f"PointCloud {name} must not be a numpy.ma.MaskedArray")
    return np.asarray(value)


def _storage_is_readonly(value: np.ndarray) -> bool:
    current: object | None = value
    seen: set[int] = set()
    while current is not None:
        identity = id(current)
        if identity in seen:
            return False
        seen.add(identity)
        if isinstance(current, np.ndarray):
            if current.flags.writeable:
                return False
            current = current.base
            continue
        if isinstance(current, memoryview):
            if not current.readonly:
                return False
            current = current.obj
            continue
        if isinstance(current, bytes):
            return True
        try:
            exported = memoryview(current)
        except TypeError:
            return False
        if not exported.readonly or exported.obj is current:
            return False
        current = exported.obj
    return True


def _prepare_numpy_column(
    value: np.ndarray,
    *,
    name: str,
    dtype: np.dtype,
    copy: PointCloudCopyPolicy,
    casting: PointCloudCastingPolicy,
) -> np.ndarray:
    source = _normalize_numpy_array(value, name=name)
    if source.ndim not in (1, 2):
        raise ValueError(
            f"PointCloud {name} must be one- or two-dimensional, got shape {source.shape}"
        )

    dtype_matches = source.dtype == dtype
    if not dtype_matches:
        if copy == "never":
            raise ValueError(
                f"PointCloud {name} requires dtype {dtype} but copy='never'"
            )
        if casting == "no" or not np.can_cast(source.dtype, dtype, casting=casting):
            raise TypeError(
                f"PointCloud {name} requires dtype {dtype}, got {source.dtype}; "
                f"casting={casting!r} does not allow conversion"
            )
        if dtype == np.dtype(np.float32) and np.issubdtype(
            source.dtype, np.floating
        ):
            source_info = np.finfo(source.dtype)
            float32_info = np.finfo(np.float32)
            if (source_info.maxexp, source_info.nmant) > (
                float32_info.maxexp,
                float32_info.nmant,
            ):
                source_limit = np.asarray(_FLOAT32_MAX, dtype=source.dtype)
                finite = np.isfinite(source)
                if np.any(finite & (np.abs(source) > source_limit)):
                    raise ValueError(
                        f"PointCloud {name} contains a finite value outside the float32 range"
                    )
        if dtype == np.dtype(np.uint8) and np.issubdtype(
            source.dtype, np.integer
        ):
            if np.any(source < 0) or np.any(source > 255):
                raise ValueError(
                    f"PointCloud {name} values must be in the range [0, 255]"
                )

    storage_is_readonly = _storage_is_readonly(source)
    borrowable = (
        dtype_matches
        and source.flags.c_contiguous
        and source.flags.aligned
        and storage_is_readonly
    )
    if copy == "never" and not borrowable:
        reasons: list[str] = []
        if not dtype_matches:
            reasons.append(f"dtype must be {dtype}")
        if not source.flags.c_contiguous:
            reasons.append("array must be C-contiguous")
        if not source.flags.aligned:
            reasons.append("array must be aligned")
        if not storage_is_readonly:
            reasons.append("array and its backing storage must be read-only")
        raise ValueError(
            f"PointCloud {name} cannot be borrowed with copy='never': "
            + ", ".join(reasons)
        )

    if copy == "always" or not borrowable:
        if dtype_matches:
            prepared = np.array(source, dtype=dtype, order="C", copy=True)
        else:
            prepared = source.astype(dtype, order="C", casting=casting, copy=True)
    else:
        prepared = source

    flattened = prepared.reshape(-1)
    flattened.setflags(write=False)
    return flattened


def _resolve_dimensions(
    shape: tuple[int, ...],
    point_count: int,
    width: int | None,
    height: int | None,
) -> tuple[int, int]:
    if (width is None) != (height is None):
        raise ValueError("PointCloud width and height must be provided together")
    if width is None:
        if len(shape) == 2:
            resolved_height, resolved_width = shape
        else:
            resolved_height, resolved_width = 1, point_count
    else:
        if not isinstance(width, Integral) or isinstance(width, bool):
            raise TypeError("PointCloud width must be an integer")
        if not isinstance(height, Integral) or isinstance(height, bool):
            raise TypeError("PointCloud height must be an integer")
        resolved_width = int(width)
        resolved_height = int(height)
        if len(shape) == 2 and shape != (resolved_height, resolved_width):
            raise ValueError(
                "PointCloud two-dimensional XYZ shape must match height and width"
            )

    if not 0 <= resolved_width <= _UINT32_MAX:
        raise ValueError("PointCloud width must be in the uint32 range")
    if not 0 <= resolved_height <= _UINT32_MAX:
        raise ValueError("PointCloud height must be in the uint32 range")
    if resolved_width * resolved_height != point_count:
        raise ValueError("PointCloud width * height must equal the point count")
    if point_count > _LIST_OFFSET_MAX:
        raise ValueError("PointCloud point count exceeds the Arrow list offset range")
    return resolved_width, resolved_height


def _empty_numpy_column(dtype: np.dtype) -> np.ndarray:
    value = np.empty(0, dtype=dtype)
    value.setflags(write=False)
    return value


def _numpy_list_array(value: np.ndarray, value_type: pa.DataType) -> pa.ListArray:
    if type(value) is not np.ndarray or value.ndim != 1:
        raise TypeError(
            "PointCloud prepared columns must be plain one-dimensional numpy.ndarray values"
        )
    length = int(value.size)
    values = pa.Array.from_buffers(
        value_type,
        length,
        [None, pa.py_buffer(value)],
        null_count=0,
    )
    offsets = pa.array([0, length], type=pa.int32())
    return pa.ListArray.from_arrays(offsets, values)


def _numpy_view(value: pa.Array) -> np.ndarray:
    view = value.to_numpy(zero_copy_only=True)
    view.setflags(write=False)
    return view


class PointCloud(BaseModel):
    """Organized or unorganized XYZ point cloud.

    Instances are validated at construction and should be treated as immutable
    message values. Build a new instance instead of mutating fields in place.
    """

    _ARROW_SCHEMA: ClassVar[pa.Schema] = _POINT_CLOUD_ARROW_SCHEMA

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
                raise ValueError(
                    "point count must be divisible by height when width is omitted"
                )
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
            raise ValueError(
                "red, green, and blue must all be empty or all be populated"
            )
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
        batch = _normalize_point_cloud_batch(data)
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


class PointCloudBatch:
    """Canonical PointCloud RecordBatch backed by typed NumPy buffers."""

    __slots__ = ("_owners", "_record_batch")

    _owners: tuple[np.ndarray, ...]
    _record_batch: pa.RecordBatch

    def __init__(self) -> None:
        raise TypeError("use PointCloudBatch.from_numpy()")

    @classmethod
    def from_numpy(
        cls,
        *,
        x: np.ndarray,
        y: np.ndarray,
        z: np.ndarray,
        intensity: np.ndarray | None = None,
        rgb: PointCloudRgbInput | None = None,
        width: int | None = None,
        height: int | None = None,
        is_dense: bool | None = None,
        copy: PointCloudCopyPolicy = "always",
        casting: PointCloudCastingPolicy = "no",
    ) -> "PointCloudBatch":
        """Build a canonical Arrow batch from NumPy point columns.

        ``copy='always'`` creates an immutable snapshot. ``if_needed`` borrows
        only exact-dtype, naturally aligned, C-contiguous arrays whose visible
        backing chain is read-only. ``never`` rejects any input that cannot be
        borrowed. While borrowed payloads exist, callers must not mutate their
        storage through any alias or re-enable writes. Copy policy applies to
        the large payload buffers; small Arrow scalar and list-offset arrays are
        always allocated.
        """

        _validate_copy_policy(copy)
        _validate_casting_policy(casting)
        x = _normalize_numpy_array(x, name="x")
        y = _normalize_numpy_array(y, name="y")
        z = _normalize_numpy_array(z, name="z")
        for name, value in (("x", x), ("y", y), ("z", z)):
            if value.ndim not in (1, 2):
                raise ValueError(
                    f"PointCloud {name} must be one- or two-dimensional, "
                    f"got shape {value.shape}"
                )
        if y.shape != x.shape or z.shape != x.shape:
            raise ValueError("PointCloud x, y, and z must have the same shape")

        point_count = int(x.size)
        resolved_width, resolved_height = _resolve_dimensions(
            x.shape, point_count, width, height
        )
        float32 = np.dtype(np.float32)
        uint8 = np.dtype(np.uint8)
        prepared_x = _prepare_numpy_column(
            x, name="x", dtype=float32, copy=copy, casting=casting
        )
        prepared_y = _prepare_numpy_column(
            y, name="y", dtype=float32, copy=copy, casting=casting
        )
        prepared_z = _prepare_numpy_column(
            z, name="z", dtype=float32, copy=copy, casting=casting
        )

        if intensity is None:
            prepared_intensity = _empty_numpy_column(float32)
        else:
            intensity = _normalize_numpy_array(intensity, name="intensity")
            if intensity.shape not in (x.shape, (point_count,)):
                raise ValueError(
                    "PointCloud intensity shape must match XYZ or be flat"
                )
            prepared_intensity = _prepare_numpy_column(
                intensity,
                name="intensity",
                dtype=float32,
                copy=copy,
                casting=casting,
            )

        if rgb is None:
            prepared_red = _empty_numpy_column(uint8)
            prepared_green = _empty_numpy_column(uint8)
            prepared_blue = _empty_numpy_column(uint8)
        elif isinstance(rgb, tuple):
            if len(rgb) != 3:
                raise ValueError("PointCloud RGB tuple must contain three channels")
            channels: list[np.ndarray] = []
            for name, channel in zip(("red", "green", "blue"), rgb, strict=True):
                channel = _normalize_numpy_array(channel, name=name)
                if channel.shape not in (x.shape, (point_count,)):
                    raise ValueError(
                        f"PointCloud {name} shape must match XYZ or be flat"
                    )
                channels.append(
                    _prepare_numpy_column(
                        channel,
                        name=name,
                        dtype=uint8,
                        copy=copy,
                        casting=casting,
                    )
                )
            prepared_red, prepared_green, prepared_blue = channels
        elif isinstance(rgb, np.ndarray):
            rgb = _normalize_numpy_array(rgb, name="rgb")
            expected_shapes = (x.shape + (3,), (point_count, 3))
            if rgb.shape not in expected_shapes:
                raise ValueError(
                    "PointCloud interleaved RGB shape must be XYZ shape + (3,) "
                    "or (point_count, 3)"
                )
            if copy == "never":
                raise ValueError(
                    "PointCloud interleaved RGB requires deinterleaving and cannot "
                    "be used with copy='never'"
                )
            interleaved = rgb.reshape(point_count, 3)
            prepared_red = _prepare_numpy_column(
                interleaved[:, 0],
                name="red",
                dtype=uint8,
                copy=copy,
                casting=casting,
            )
            prepared_green = _prepare_numpy_column(
                interleaved[:, 1],
                name="green",
                dtype=uint8,
                copy=copy,
                casting=casting,
            )
            prepared_blue = _prepare_numpy_column(
                interleaved[:, 2],
                name="blue",
                dtype=uint8,
                copy=copy,
                casting=casting,
            )
        else:
            raise TypeError(
                "PointCloud rgb must be a numpy.ndarray or a three-array tuple"
            )

        if is_dense is None:
            resolved_dense = bool(
                np.isfinite(prepared_x).all()
                and np.isfinite(prepared_y).all()
                and np.isfinite(prepared_z).all()
            )
        else:
            if not isinstance(is_dense, (bool, np.bool_)):
                raise TypeError("PointCloud is_dense must be a boolean")
            resolved_dense = bool(is_dense)
            if resolved_dense and not (
                np.isfinite(prepared_x).all()
                and np.isfinite(prepared_y).all()
                and np.isfinite(prepared_z).all()
            ):
                raise ValueError(
                    "dense point clouds must contain finite XYZ values"
                )

        owners = (
            prepared_x,
            prepared_y,
            prepared_z,
            prepared_intensity,
            prepared_red,
            prepared_green,
            prepared_blue,
        )
        arrays: list[pa.Array] = [
            pa.array([resolved_width], type=pa.uint32()),
            pa.array([resolved_height], type=pa.uint32()),
            pa.array([resolved_dense], type=pa.bool_()),
            _numpy_list_array(prepared_x, pa.float32()),
            _numpy_list_array(prepared_y, pa.float32()),
            _numpy_list_array(prepared_z, pa.float32()),
            _numpy_list_array(prepared_intensity, pa.float32()),
            _numpy_list_array(prepared_red, pa.uint8()),
            _numpy_list_array(prepared_green, pa.uint8()),
            _numpy_list_array(prepared_blue, pa.uint8()),
        ]
        value = object.__new__(cls)
        value._owners = owners
        value._record_batch = pa.RecordBatch.from_arrays(
            arrays, schema=_POINT_CLOUD_ARROW_SCHEMA
        )
        return value

    @property
    def record_batch(self) -> pa.RecordBatch:
        return self._record_batch

    def to_arrow(self) -> pa.RecordBatch:
        return self._record_batch

    def view(self) -> "PointCloudView":
        return PointCloudView.from_arrow(self._record_batch)


class PointCloudView:
    """Validated, read-only NumPy views over an Arrow PointCloud payload."""

    __slots__ = (
        "_blue",
        "_green",
        "_height",
        "_intensity",
        "_is_dense",
        "_record_batch",
        "_red",
        "_width",
        "_x",
        "_y",
        "_z",
    )

    _blue: np.ndarray
    _green: np.ndarray
    _height: int
    _intensity: np.ndarray
    _is_dense: bool
    _record_batch: pa.RecordBatch
    _red: np.ndarray
    _width: int
    _x: np.ndarray
    _y: np.ndarray
    _z: np.ndarray

    def __init__(self) -> None:
        raise TypeError("use PointCloudView.from_arrow()")

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "PointCloudView":
        batch = _normalize_point_cloud_batch(data)
        indices = _required_field_indices(batch, _POINT_CLOUD_ARROW_SCHEMA)
        width = int(_read_scalar(batch, indices["width"], "width"))
        height = int(_read_scalar(batch, indices["height"], "height"))
        is_dense = bool(_read_scalar(batch, indices["is_dense"], "is_dense"))
        values = {
            name: _read_list_values(batch, indices[name], name)
            for name in ("x", "y", "z", "intensity", "red", "green", "blue")
        }

        point_count = len(values["x"])
        if len(values["y"]) != point_count or len(values["z"]) != point_count:
            raise ValueError("x, y, and z must have the same length")
        if width * height != point_count:
            raise ValueError("width * height must equal the point count")
        for name in ("intensity", "red", "green", "blue"):
            length = len(values[name])
            if length not in (0, point_count):
                raise ValueError(
                    f"{name} must be empty or have the same length as x"
                )
        populated_rgb = [bool(len(values[name])) for name in ("red", "green", "blue")]
        if any(populated_rgb) and not all(populated_rgb):
            raise ValueError(
                "red, green, and blue must all be empty or all be populated"
            )

        numpy_values = {name: _numpy_view(array) for name, array in values.items()}
        if is_dense and not (
            np.isfinite(numpy_values["x"]).all()
            and np.isfinite(numpy_values["y"]).all()
            and np.isfinite(numpy_values["z"]).all()
        ):
            raise ValueError("dense point clouds must contain finite XYZ values")

        value = object.__new__(cls)
        value._record_batch = batch
        value._width = width
        value._height = height
        value._is_dense = is_dense
        value._x = numpy_values["x"]
        value._y = numpy_values["y"]
        value._z = numpy_values["z"]
        value._intensity = numpy_values["intensity"]
        value._red = numpy_values["red"]
        value._green = numpy_values["green"]
        value._blue = numpy_values["blue"]
        return value

    @staticmethod
    def _readonly_view(value: np.ndarray) -> np.ndarray:
        view = value.view()
        view.setflags(write=False)
        return view

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
    def is_dense(self) -> bool:
        return self._is_dense

    @property
    def point_count(self) -> int:
        return len(self._x)

    @property
    def has_intensity(self) -> bool:
        return bool(len(self._intensity))

    @property
    def has_rgb(self) -> bool:
        return bool(len(self._red))

    @property
    def x(self) -> np.ndarray:
        return self._readonly_view(self._x)

    @property
    def y(self) -> np.ndarray:
        return self._readonly_view(self._y)

    @property
    def z(self) -> np.ndarray:
        return self._readonly_view(self._z)

    @property
    def intensity(self) -> np.ndarray:
        return self._readonly_view(self._intensity)

    @property
    def red(self) -> np.ndarray:
        return self._readonly_view(self._red)

    @property
    def green(self) -> np.ndarray:
        return self._readonly_view(self._green)

    @property
    def blue(self) -> np.ndarray:
        return self._readonly_view(self._blue)

    def to_owned(self) -> PointCloud:
        return PointCloud(
            width=self.width,
            height=self.height,
            is_dense=self.is_dense,
            x=self._x.tolist(),
            y=self._y.tolist(),
            z=self._z.tolist(),
            intensity=self._intensity.tolist(),
            red=self._red.tolist(),
            green=self._green.tolist(),
            blue=self._blue.tolist(),
        )
