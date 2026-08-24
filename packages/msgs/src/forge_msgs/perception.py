from __future__ import annotations

import math
from typing import Literal, Self

import pyarrow as pa
from pydantic import BaseModel, Field, model_validator

from forge_msgs.arrow import ensure_record_batch

_UINT32_MAX = 2**32 - 1


def _list_type(value_type: pa.DataType) -> pa.ListType:
    return pa.list_(pa.field("item", value_type, nullable=True))


def _schema(*fields: tuple[str, pa.DataType]) -> pa.Schema:
    return pa.schema(
        [pa.field(name, data_type, nullable=False) for name, data_type in fields]
    )


def _to_record_batch(values: dict[str, object], schema: pa.Schema) -> pa.RecordBatch:
    arrays = [pa.array([values[field.name]], type=field.type) for field in schema]
    return pa.RecordBatch.from_arrays(arrays, schema=schema)


def _ensure_single_row(
    data: pa.RecordBatch | pa.Table | pa.StructArray | bytes, model_name: str
) -> pa.RecordBatch:
    if isinstance(data, bytes):
        data = pa.ipc.open_stream(data).read_all()
    if isinstance(data, pa.Table):
        if data.num_rows != 1:
            raise ValueError(f"{model_name} RecordBatch must contain exactly one row")
        return data.combine_chunks().to_batches()[0]
    batch = ensure_record_batch(data)
    if batch.num_rows != 1:
        raise ValueError(f"{model_name} RecordBatch must contain exactly one row")
    return batch


def _read_field(batch: pa.RecordBatch, name: str, expected_type: pa.DataType) -> object:
    index = batch.schema.get_field_index(name)
    if index < 0:
        raise ValueError(f"missing required Arrow field: {name}")
    array = batch.column(index)
    actual_type = array.type
    types_match = actual_type == expected_type
    if pa.types.is_list(expected_type) and pa.types.is_list(actual_type):
        types_match = actual_type.value_type == expected_type.value_type
    if not types_match:
        raise TypeError(
            f"Arrow field {name} must have type {expected_type}, got {actual_type}"
        )
    if not array[0].is_valid:
        raise ValueError(f"Arrow field {name} must not be null")
    if pa.types.is_list(actual_type):
        values = array[0].values
        if values.null_count:
            raise ValueError(f"Arrow field {name} list items must not be null")
        return list(values.to_pylist())
    return array[0].as_py()


def _read_canonical(
    data: pa.RecordBatch | pa.Table | pa.StructArray | bytes,
    model_name: str,
    schema: pa.Schema,
) -> tuple[pa.RecordBatch, dict[str, object]]:
    batch = _ensure_single_row(data, model_name)
    return batch, {
        field.name: _read_field(batch, field.name, field.type) for field in schema
    }


_CLASSIFICATION_SCHEMA = _schema(
    ("class_id", _list_type(pa.string())),
    ("score", _list_type(pa.float32())),
)
_DETECTION_2D_SCHEMA = _schema(
    ("detection_id", _list_type(pa.string())),
    ("track_id", _list_type(pa.string())),
    ("center_x", _list_type(pa.float32())),
    ("center_y", _list_type(pa.float32())),
    ("size_x", _list_type(pa.float32())),
    ("size_y", _list_type(pa.float32())),
    ("rotation", _list_type(pa.float32())),
    ("hypothesis_offset", _list_type(pa.uint32())),
    ("class_id", _list_type(pa.string())),
    ("score", _list_type(pa.float32())),
)
_DETECTION_3D_SCHEMA = _schema(
    ("detection_id", _list_type(pa.string())),
    ("track_id", _list_type(pa.string())),
    ("center_x", _list_type(pa.float32())),
    ("center_y", _list_type(pa.float32())),
    ("center_z", _list_type(pa.float32())),
    ("qx", _list_type(pa.float32())),
    ("qy", _list_type(pa.float32())),
    ("qz", _list_type(pa.float32())),
    ("qw", _list_type(pa.float32())),
    ("size_x", _list_type(pa.float32())),
    ("size_y", _list_type(pa.float32())),
    ("size_z", _list_type(pa.float32())),
    ("hypothesis_offset", _list_type(pa.uint32())),
    ("class_id", _list_type(pa.string())),
    ("score", _list_type(pa.float32())),
)
_KEYPOINT_2D_SCHEMA = _schema(
    ("instance_id", _list_type(pa.string())),
    ("detection_id", _list_type(pa.string())),
    ("track_id", _list_type(pa.string())),
    ("keypoint_offset", _list_type(pa.uint32())),
    ("keypoint_id", _list_type(pa.string())),
    ("x", _list_type(pa.float32())),
    ("y", _list_type(pa.float32())),
    ("score", _list_type(pa.float32())),
)
_KEYPOINT_3D_SCHEMA = _schema(
    ("instance_id", _list_type(pa.string())),
    ("detection_id", _list_type(pa.string())),
    ("track_id", _list_type(pa.string())),
    ("keypoint_offset", _list_type(pa.uint32())),
    ("keypoint_id", _list_type(pa.string())),
    ("x", _list_type(pa.float32())),
    ("y", _list_type(pa.float32())),
    ("z", _list_type(pa.float32())),
    ("score", _list_type(pa.float32())),
)
_SEGMENTATION_REQUIRED_SCHEMA = _schema(
    ("mask_id", _list_type(pa.string())),
    ("detection_id", _list_type(pa.string())),
    ("track_id", _list_type(pa.string())),
    ("x_offset", _list_type(pa.uint32())),
    ("y_offset", _list_type(pa.uint32())),
    ("width", _list_type(pa.uint32())),
    ("height", _list_type(pa.uint32())),
    ("encoding", pa.string()),
    ("data", _list_type(pa.large_binary())),
)
_SEGMENTATION_SCHEMA = _schema(
    *((field.name, field.type) for field in _SEGMENTATION_REQUIRED_SCHEMA),
    ("score", _list_type(pa.float32())),
)


def _validate_unique(name: str, values: list) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{name} items must be unique")


def _validate_lengths(reference_name: str, reference: list, **fields: list) -> None:
    for name, values in fields.items():
        if len(values) != len(reference):
            raise ValueError(
                f"{name} must have the same length as {reference_name} "
                f"({len(values)} != {len(reference)})"
            )


def _validate_finite_non_negative(name: str, values: list[float]) -> None:
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ValueError(f"{name} values must be finite and non-negative")


def _validate_finite(name: str, values: list[float]) -> None:
    if any(not math.isfinite(value) for value in values):
        raise ValueError(f"{name} values must be finite")


def _validate_scores(name: str, values: list[float]) -> None:
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values):
        raise ValueError(f"{name} values must be finite and in the range [0, 1]")


def _validate_uint32(name: str, values: list[int]) -> None:
    if any(value < 0 or value > _UINT32_MAX for value in values):
        raise ValueError(f"{name} values must be in the uint32 range")


def _validate_hypotheses(
    detection_count: int,
    offsets: list[int],
    class_id: list[str],
    score: list[float],
) -> None:
    _validate_uint32("hypothesis_offset", offsets)
    if len(offsets) != detection_count + 1:
        raise ValueError("hypothesis_offset length must equal detection count + 1")
    if not offsets or offsets[0] != 0:
        raise ValueError("hypothesis_offset must start at 0")
    if any(left > right for left, right in zip(offsets, offsets[1:], strict=False)):
        raise ValueError("hypothesis_offset must be monotonically non-decreasing")
    if offsets[-1] != len(class_id):
        raise ValueError("hypothesis_offset must end at len(class_id)")
    if len(score) != len(class_id):
        raise ValueError("score must have the same length as class_id")
    _validate_scores("score", score)


class Classification(BaseModel):
    """Classification hypotheses and confidence scores."""

    class_id: list[str] = Field(default_factory=list)
    score: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _validate_unique("class_id", self.class_id)
        _validate_lengths("class_id", self.class_id, score=self.score)
        _validate_scores("score", self.score)
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return _to_record_batch(self.model_dump(), _CLASSIFICATION_SCHEMA)

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "Classification":
        _, values = _read_canonical(data, cls.__name__, _CLASSIFICATION_SCHEMA)
        return cls(**values)


class Detection2DSet(BaseModel):
    """Oriented 2D detections with flattened classification hypotheses."""

    detection_id: list[str] = Field(default_factory=list)
    track_id: list[str] = Field(default_factory=list)
    center_x: list[float] = Field(default_factory=list)
    center_y: list[float] = Field(default_factory=list)
    size_x: list[float] = Field(default_factory=list)
    size_y: list[float] = Field(default_factory=list)
    rotation: list[float] = Field(default_factory=list)
    hypothesis_offset: list[int] = Field(default_factory=lambda: [0])
    class_id: list[str] = Field(default_factory=list)
    score: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.detection_id and not self.rotation:
            self.rotation = [0.0] * len(self.detection_id)
        _validate_unique("detection_id", self.detection_id)
        _validate_lengths(
            "detection_id",
            self.detection_id,
            track_id=self.track_id,
            center_x=self.center_x,
            center_y=self.center_y,
            size_x=self.size_x,
            size_y=self.size_y,
            rotation=self.rotation,
        )
        _validate_finite_non_negative("size_x", self.size_x)
        _validate_finite_non_negative("size_y", self.size_y)
        _validate_finite("center_x", self.center_x)
        _validate_finite("center_y", self.center_y)
        _validate_finite("rotation", self.rotation)
        _validate_hypotheses(
            len(self.detection_id),
            self.hypothesis_offset,
            self.class_id,
            self.score,
        )
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return _to_record_batch(self.model_dump(), _DETECTION_2D_SCHEMA)

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "Detection2DSet":
        _, values = _read_canonical(data, cls.__name__, _DETECTION_2D_SCHEMA)
        return cls(**values)


class Detection3DSet(BaseModel):
    """Oriented 3D detections with flattened classification hypotheses."""

    detection_id: list[str] = Field(default_factory=list)
    track_id: list[str] = Field(default_factory=list)
    center_x: list[float] = Field(default_factory=list)
    center_y: list[float] = Field(default_factory=list)
    center_z: list[float] = Field(default_factory=list)
    qx: list[float] = Field(default_factory=list)
    qy: list[float] = Field(default_factory=list)
    qz: list[float] = Field(default_factory=list)
    qw: list[float] = Field(default_factory=list)
    size_x: list[float] = Field(default_factory=list)
    size_y: list[float] = Field(default_factory=list)
    size_z: list[float] = Field(default_factory=list)
    hypothesis_offset: list[int] = Field(default_factory=lambda: [0])
    class_id: list[str] = Field(default_factory=list)
    score: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if (
            self.detection_id
            and not self.qx
            and not self.qy
            and not self.qz
            and not self.qw
        ):
            count = len(self.detection_id)
            self.qx = [0.0] * count
            self.qy = [0.0] * count
            self.qz = [0.0] * count
            self.qw = [1.0] * count
        _validate_unique("detection_id", self.detection_id)
        _validate_lengths(
            "detection_id",
            self.detection_id,
            track_id=self.track_id,
            center_x=self.center_x,
            center_y=self.center_y,
            center_z=self.center_z,
            qx=self.qx,
            qy=self.qy,
            qz=self.qz,
            qw=self.qw,
            size_x=self.size_x,
            size_y=self.size_y,
            size_z=self.size_z,
        )
        for values in zip(self.qx, self.qy, self.qz, self.qw, strict=True):
            if values == (0.0, 0.0, 0.0, 0.0):
                raise ValueError("quaternion must not be all zero")
        for name in ("center_x", "center_y", "center_z", "qx", "qy", "qz", "qw"):
            _validate_finite(name, getattr(self, name))
        _validate_finite_non_negative("size_x", self.size_x)
        _validate_finite_non_negative("size_y", self.size_y)
        _validate_finite_non_negative("size_z", self.size_z)
        _validate_hypotheses(
            len(self.detection_id),
            self.hypothesis_offset,
            self.class_id,
            self.score,
        )
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return _to_record_batch(self.model_dump(), _DETECTION_3D_SCHEMA)

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "Detection3DSet":
        _, values = _read_canonical(data, cls.__name__, _DETECTION_3D_SCHEMA)
        return cls(**values)


class Keypoint2DSet(BaseModel):
    """2D keypoints flattened across object instances."""

    instance_id: list[str] = Field(default_factory=list)
    detection_id: list[str] = Field(default_factory=list)
    track_id: list[str] = Field(default_factory=list)
    keypoint_offset: list[int] = Field(default_factory=lambda: [0])
    keypoint_id: list[str] = Field(default_factory=list)
    x: list[float] = Field(default_factory=list)
    y: list[float] = Field(default_factory=list)
    score: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        instance_count = len(self.instance_id)
        if self.instance_id:
            if not self.detection_id:
                self.detection_id = [""] * instance_count
            if not self.track_id:
                self.track_id = [""] * instance_count
        _validate_unique("instance_id", self.instance_id)
        _validate_lengths(
            "instance_id",
            self.instance_id,
            detection_id=self.detection_id,
            track_id=self.track_id,
        )
        self._validate_keypoints(instance_count)
        return self

    def _validate_keypoints(self, instance_count: int) -> None:
        _validate_uint32("keypoint_offset", self.keypoint_offset)
        if len(self.keypoint_offset) != instance_count + 1:
            raise ValueError("keypoint_offset length must equal instance count + 1")
        if not self.keypoint_offset or self.keypoint_offset[0] != 0:
            raise ValueError("keypoint_offset must start at 0")
        if any(
            left > right
            for left, right in zip(
                self.keypoint_offset, self.keypoint_offset[1:], strict=False
            )
        ):
            raise ValueError("keypoint_offset must be monotonically non-decreasing")
        if self.keypoint_offset[-1] != len(self.keypoint_id):
            raise ValueError("keypoint_offset must end at len(keypoint_id)")
        _validate_lengths(
            "keypoint_id",
            self.keypoint_id,
            x=self.x,
            y=self.y,
            score=self.score,
        )
        for start, end in zip(
            self.keypoint_offset, self.keypoint_offset[1:], strict=False
        ):
            _validate_unique(
                "keypoint_id within each instance", self.keypoint_id[start:end]
            )
        _validate_finite("x", self.x)
        _validate_finite("y", self.y)
        _validate_scores("score", self.score)

    def to_arrow(self) -> pa.RecordBatch:
        return _to_record_batch(self.model_dump(), _KEYPOINT_2D_SCHEMA)

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "Keypoint2DSet":
        _, values = _read_canonical(data, cls.__name__, _KEYPOINT_2D_SCHEMA)
        return cls(**values)


class Keypoint3DSet(BaseModel):
    """3D keypoints flattened across object instances."""

    instance_id: list[str] = Field(default_factory=list)
    detection_id: list[str] = Field(default_factory=list)
    track_id: list[str] = Field(default_factory=list)
    keypoint_offset: list[int] = Field(default_factory=lambda: [0])
    keypoint_id: list[str] = Field(default_factory=list)
    x: list[float] = Field(default_factory=list)
    y: list[float] = Field(default_factory=list)
    z: list[float] = Field(default_factory=list)
    score: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        instance_count = len(self.instance_id)
        if self.instance_id:
            if not self.detection_id:
                self.detection_id = [""] * instance_count
            if not self.track_id:
                self.track_id = [""] * instance_count
        _validate_unique("instance_id", self.instance_id)
        _validate_lengths(
            "instance_id",
            self.instance_id,
            detection_id=self.detection_id,
            track_id=self.track_id,
        )
        _validate_uint32("keypoint_offset", self.keypoint_offset)
        if len(self.keypoint_offset) != instance_count + 1:
            raise ValueError("keypoint_offset length must equal instance count + 1")
        if not self.keypoint_offset or self.keypoint_offset[0] != 0:
            raise ValueError("keypoint_offset must start at 0")
        if any(
            left > right
            for left, right in zip(
                self.keypoint_offset, self.keypoint_offset[1:], strict=False
            )
        ):
            raise ValueError("keypoint_offset must be monotonically non-decreasing")
        if self.keypoint_offset[-1] != len(self.keypoint_id):
            raise ValueError("keypoint_offset must end at len(keypoint_id)")
        _validate_lengths(
            "keypoint_id",
            self.keypoint_id,
            x=self.x,
            y=self.y,
            z=self.z,
            score=self.score,
        )
        for start, end in zip(
            self.keypoint_offset, self.keypoint_offset[1:], strict=False
        ):
            _validate_unique(
                "keypoint_id within each instance", self.keypoint_id[start:end]
            )
        _validate_finite("x", self.x)
        _validate_finite("y", self.y)
        _validate_finite("z", self.z)
        _validate_scores("score", self.score)
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return _to_record_batch(self.model_dump(), _KEYPOINT_3D_SCHEMA)

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "Keypoint3DSet":
        _, values = _read_canonical(data, cls.__name__, _KEYPOINT_3D_SCHEMA)
        return cls(**values)


class SegmentationMaskSet(BaseModel):
    """Cropped binary instance masks positioned in a source image."""

    mask_id: list[str] = Field(default_factory=list)
    detection_id: list[str] = Field(default_factory=list)
    track_id: list[str] = Field(default_factory=list)
    x_offset: list[int] = Field(default_factory=list)
    y_offset: list[int] = Field(default_factory=list)
    width: list[int] = Field(default_factory=list)
    height: list[int] = Field(default_factory=list)
    encoding: Literal["mono8"] = "mono8"
    data: list[bytes] = Field(default_factory=list)
    score: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.mask_id:
            count = len(self.mask_id)
            if not self.detection_id:
                self.detection_id = [""] * count
            if not self.track_id:
                self.track_id = [""] * count
            if not self.x_offset:
                self.x_offset = [0] * count
            if not self.y_offset:
                self.y_offset = [0] * count
        _validate_unique("mask_id", self.mask_id)
        _validate_lengths(
            "mask_id",
            self.mask_id,
            detection_id=self.detection_id,
            track_id=self.track_id,
            x_offset=self.x_offset,
            y_offset=self.y_offset,
            width=self.width,
            height=self.height,
            data=self.data,
        )
        if self.score and len(self.score) != len(self.mask_id):
            raise ValueError("score must be empty or have the same length as mask_id")
        _validate_scores("score", self.score)
        for name in ("x_offset", "y_offset", "width", "height"):
            _validate_uint32(name, getattr(self, name))
        for index, payload in enumerate(self.data):
            expected = self.width[index] * self.height[index]
            if len(payload) != expected:
                raise ValueError(
                    f"data[{index}] length must equal width * height "
                    f"({len(payload)} != {expected})"
                )
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return _to_record_batch(self.model_dump(), _SEGMENTATION_SCHEMA)

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "SegmentationMaskSet":
        batch, values = _read_canonical(
            data, cls.__name__, _SEGMENTATION_REQUIRED_SCHEMA
        )
        score_name = "score" if batch.schema.get_field_index("score") >= 0 else None
        values["score"] = (
            _read_field(batch, score_name, _list_type(pa.float32()))
            if score_name is not None
            else []
        )
        return cls(**values)
