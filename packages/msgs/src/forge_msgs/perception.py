from __future__ import annotations

import math
from typing import Literal, Self

import pyarrow as pa
from pydantic import BaseModel, Field, model_validator

from forge_msgs.arrow import ensure_record_batch

DescriptorType = Literal["none", "uint8", "float32"]
_UINT32_MAX = 2**32 - 1


def _list_array(values: list, value_type: pa.DataType) -> pa.Array:
    return pa.array([values], type=pa.list_(value_type))


def _read_list(batch: pa.RecordBatch, name: str) -> list:
    return list(batch[name][0].as_py() or [])


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
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in score):
        raise ValueError("score values must be finite and in the range [0, 1]")


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
        return pa.RecordBatch.from_pydict(
            {
                "detection_id": _list_array(self.detection_id, pa.string()),
                "track_id": _list_array(self.track_id, pa.string()),
                "center_x": _list_array(self.center_x, pa.float32()),
                "center_y": _list_array(self.center_y, pa.float32()),
                "size_x": _list_array(self.size_x, pa.float32()),
                "size_y": _list_array(self.size_y, pa.float32()),
                "rotation": _list_array(self.rotation, pa.float32()),
                "hypothesis_offset": _list_array(self.hypothesis_offset, pa.uint32()),
                "class_id": _list_array(self.class_id, pa.string()),
                "score": _list_array(self.score, pa.float32()),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "Detection2DSet":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("Detection2DSet RecordBatch must contain one row")
        return cls(**{name: _read_list(batch, name) for name in cls.model_fields})


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
        if self.detection_id and not self.qx and not self.qy and not self.qz and not self.qw:
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
        arrays: dict[str, pa.Array] = {}
        string_fields = {"detection_id", "track_id", "class_id"}
        uint_fields = {"hypothesis_offset"}
        for name in type(self).model_fields:
            values = getattr(self, name)
            value_type = (
                pa.string()
                if name in string_fields
                else pa.uint32()
                if name in uint_fields
                else pa.float32()
            )
            arrays[name] = _list_array(values, value_type)
        return pa.RecordBatch.from_pydict(arrays)

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "Detection3DSet":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("Detection3DSet RecordBatch must contain one row")
        return cls(**{name: _read_list(batch, name) for name in cls.model_fields})


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

    @model_validator(mode="after")
    def _validate(self) -> Self:
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
        return pa.RecordBatch.from_pydict(
            {
                "mask_id": _list_array(self.mask_id, pa.string()),
                "detection_id": _list_array(self.detection_id, pa.string()),
                "track_id": _list_array(self.track_id, pa.string()),
                "x_offset": _list_array(self.x_offset, pa.uint32()),
                "y_offset": _list_array(self.y_offset, pa.uint32()),
                "width": _list_array(self.width, pa.uint32()),
                "height": _list_array(self.height, pa.uint32()),
                "encoding": pa.array([self.encoding], type=pa.string()),
                "data": _list_array(self.data, pa.large_binary()),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "SegmentationMaskSet":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("SegmentationMaskSet RecordBatch must contain one row")
        return cls(
            mask_id=_read_list(batch, "mask_id"),
            detection_id=_read_list(batch, "detection_id"),
            track_id=_read_list(batch, "track_id"),
            x_offset=_read_list(batch, "x_offset"),
            y_offset=_read_list(batch, "y_offset"),
            width=_read_list(batch, "width"),
            height=_read_list(batch, "height"),
            encoding=str(batch["encoding"][0].as_py()),
            data=_read_list(batch, "data"),
        )


class Keypoint2DSet(BaseModel):
    """Image keypoints with an optional fixed-width descriptor matrix."""

    keypoint_id: list[int] = Field(default_factory=list)
    x: list[float] = Field(default_factory=list)
    y: list[float] = Field(default_factory=list)
    size: list[float] = Field(default_factory=list)
    angle: list[float] = Field(default_factory=list)
    response: list[float] = Field(default_factory=list)
    octave: list[int] = Field(default_factory=list)
    descriptor_type: DescriptorType = "none"
    descriptor_size: int = 0
    descriptor_data: bytes = b""

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _validate_unique("keypoint_id", self.keypoint_id)
        _validate_uint32("keypoint_id", self.keypoint_id)
        _validate_lengths(
            "keypoint_id",
            self.keypoint_id,
            x=self.x,
            y=self.y,
            size=self.size,
            angle=self.angle,
            response=self.response,
            octave=self.octave,
        )
        _validate_finite_non_negative("size", self.size)
        for name in ("x", "y", "angle", "response"):
            _validate_finite(name, getattr(self, name))
        _validate_uint32("descriptor_size", [self.descriptor_size])
        if self.descriptor_type == "none":
            if self.descriptor_size != 0 or self.descriptor_data:
                raise ValueError("none descriptors require size 0 and empty data")
            return self
        scalar_size = 1 if self.descriptor_type == "uint8" else 4
        expected = len(self.keypoint_id) * self.descriptor_size * scalar_size
        if len(self.descriptor_data) != expected:
            raise ValueError(
                "descriptor_data length must equal keypoint count * descriptor_size "
                f"* scalar size ({len(self.descriptor_data)} != {expected})"
            )
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "keypoint_id": _list_array(self.keypoint_id, pa.uint32()),
                "x": _list_array(self.x, pa.float32()),
                "y": _list_array(self.y, pa.float32()),
                "size": _list_array(self.size, pa.float32()),
                "angle": _list_array(self.angle, pa.float32()),
                "response": _list_array(self.response, pa.float32()),
                "octave": _list_array(self.octave, pa.int32()),
                "descriptor_type": pa.array([self.descriptor_type], type=pa.string()),
                "descriptor_size": pa.array([self.descriptor_size], type=pa.uint32()),
                "descriptor_data": pa.array([self.descriptor_data], type=pa.large_binary()),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "Keypoint2DSet":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("Keypoint2DSet RecordBatch must contain one row")
        return cls(
            keypoint_id=_read_list(batch, "keypoint_id"),
            x=_read_list(batch, "x"),
            y=_read_list(batch, "y"),
            size=_read_list(batch, "size"),
            angle=_read_list(batch, "angle"),
            response=_read_list(batch, "response"),
            octave=_read_list(batch, "octave"),
            descriptor_type=str(batch["descriptor_type"][0].as_py()),
            descriptor_size=int(batch["descriptor_size"][0].as_py()),
            descriptor_data=bytes(batch["descriptor_data"][0].as_py()),
        )


class KeypointMatchSet(BaseModel):
    """Pairwise matches between two named Keypoint2DSet inputs."""

    query_source: str
    train_source: str
    query_id: list[int] = Field(default_factory=list)
    train_id: list[int] = Field(default_factory=list)
    distance: list[float] = Field(default_factory=list)
    inlier: list[bool] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not self.query_source or not self.train_source:
            raise ValueError("query_source and train_source must be non-empty")
        _validate_uint32("query_id", self.query_id)
        _validate_uint32("train_id", self.train_id)
        _validate_lengths(
            "query_id",
            self.query_id,
            train_id=self.train_id,
            distance=self.distance,
            inlier=self.inlier,
        )
        _validate_finite_non_negative("distance", self.distance)
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "query_source": pa.array([self.query_source], type=pa.string()),
                "train_source": pa.array([self.train_source], type=pa.string()),
                "query_id": _list_array(self.query_id, pa.uint32()),
                "train_id": _list_array(self.train_id, pa.uint32()),
                "distance": _list_array(self.distance, pa.float32()),
                "inlier": _list_array(self.inlier, pa.bool_()),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "KeypointMatchSet":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("KeypointMatchSet RecordBatch must contain one row")
        return cls(
            query_source=str(batch["query_source"][0].as_py()),
            train_source=str(batch["train_source"][0].as_py()),
            query_id=_read_list(batch, "query_id"),
            train_id=_read_list(batch, "train_id"),
            distance=_read_list(batch, "distance"),
            inlier=_read_list(batch, "inlier"),
        )
