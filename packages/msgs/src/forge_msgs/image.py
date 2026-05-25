from __future__ import annotations

import io
from typing import Literal, Self

import numpy as np
import pyarrow as pa
from PIL import Image as PILImage
from pydantic import BaseModel, model_validator

from forge_msgs.arrow import ensure_record_batch

ImageEncoding = Literal["rgb8", "bgr8", "mono8", "16UC1", "32FC1"]
CompressedImageFormat = Literal["jpeg", "png", "webp"]

_ENCODING_INFO: dict[str, tuple[np.dtype, int]] = {
    "rgb8": (np.dtype("uint8"), 3),
    "bgr8": (np.dtype("uint8"), 3),
    "mono8": (np.dtype("uint8"), 1),
    "16UC1": (np.dtype("<u2"), 1),
    "32FC1": (np.dtype("<f4"), 1),
}


def _data_array(data: bytes) -> pa.Array:
    n = len(data)
    offsets = np.array([0, n], dtype=np.int64)
    return pa.Array.from_buffers(
        pa.large_binary(),
        1,
        [None, pa.py_buffer(offsets), pa.py_buffer(data)],
        null_count=0,
    )


def _bytes_from_cell(value: object) -> bytes:
    if hasattr(value, "as_py"):
        value = value.as_py()
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    return bytes(value)  # type: ignore[arg-type]


class Image(BaseModel):
    """Uncompressed image payload for Dora/Arrow transport."""

    height: int
    width: int
    encoding: str
    step: int
    data: bytes

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.height < 0:
            raise ValueError("height must be >= 0")
        if self.width < 0:
            raise ValueError("width must be >= 0")
        if self.step < 0:
            raise ValueError("step must be >= 0")
        if self.encoding not in _ENCODING_INFO:
            raise ValueError(f"unsupported image encoding: {self.encoding}")
        dtype, channels = _ENCODING_INFO[self.encoding]
        minimum_step = self.width * dtype.itemsize * channels
        if self.step < minimum_step:
            raise ValueError(
                f"step must be at least width * bytes_per_pixel ({self.step} < {minimum_step})"
            )
        expected = self.step * self.height
        if len(self.data) != expected:
            raise ValueError(f"data length must equal step * height ({len(self.data)} != {expected})")
        return self

    @property
    def channels(self) -> int:
        return _ENCODING_INFO[self.encoding][1]

    @property
    def dtype(self) -> np.dtype:
        return _ENCODING_INFO[self.encoding][0]

    def to_numpy(self) -> np.ndarray:
        if self.height == 0 or self.width == 0:
            if self.channels == 1:
                return np.zeros((self.height, self.width), dtype=self.dtype)
            return np.zeros((self.height, self.width, self.channels), dtype=self.dtype)

        tight_step = self.width * self.dtype.itemsize * self.channels
        if self.step == tight_step:
            arr = np.frombuffer(self.data, dtype=self.dtype)
            if self.channels == 1:
                return arr.reshape((self.height, self.width))
            return arr.reshape((self.height, self.width, self.channels))

        shape = (
            (self.height, self.width)
            if self.channels == 1
            else (self.height, self.width, self.channels)
        )
        strides = (
            (self.step, self.dtype.itemsize)
            if self.channels == 1
            else (self.step, self.dtype.itemsize * self.channels, self.dtype.itemsize)
        )
        return np.ndarray(shape=shape, dtype=self.dtype, buffer=self.data, strides=strides).copy()

    @classmethod
    def from_numpy(cls, frame: np.ndarray, encoding: ImageEncoding = "rgb8") -> "Image":
        if encoding not in _ENCODING_INFO:
            raise ValueError(f"unsupported image encoding: {encoding}")
        dtype, channels = _ENCODING_INFO[encoding]
        expected_dtype = np.dtype(dtype)
        if frame.dtype != expected_dtype:
            raise ValueError(f"{encoding} expects dtype {expected_dtype}, got {frame.dtype}")

        if channels == 1:
            if frame.ndim == 3 and frame.shape[2] == 1:
                frame = frame.reshape(frame.shape[0], frame.shape[1])
            if frame.ndim != 2:
                raise ValueError(f"{encoding} expects shape (H, W) or (H, W, 1), got {frame.shape}")
            height, width = frame.shape
        else:
            if frame.ndim != 3 or frame.shape[2] != channels:
                raise ValueError(f"{encoding} expects shape (H, W, {channels}), got {frame.shape}")
            height, width, _ = frame.shape

        contiguous = np.ascontiguousarray(frame)
        step = int(width * expected_dtype.itemsize * channels)
        return cls(
            height=int(height),
            width=int(width),
            encoding=encoding,
            step=step,
            data=contiguous.tobytes(),
        )

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_arrays(
            [
                pa.array([self.height], type=pa.uint32()),
                pa.array([self.width], type=pa.uint32()),
                pa.array([self.encoding], type=pa.string()),
                pa.array([self.step], type=pa.uint32()),
                _data_array(self.data),
            ],
            names=["height", "width", "encoding", "step", "data"],
        )

    @classmethod
    def from_arrow(cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes) -> "Image":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("Image RecordBatch must contain one row")
        return cls(
            height=int(batch["height"][0].as_py()),
            width=int(batch["width"][0].as_py()),
            encoding=str(batch["encoding"][0].as_py()),
            step=int(batch["step"][0].as_py()),
            data=_bytes_from_cell(batch["data"][0]),
        )


class CompressedImage(BaseModel):
    """Compressed image bitstream payload."""

    format: str
    data: bytes

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not self.format:
            raise ValueError("format must be non-empty")
        return self

    def to_numpy(self) -> np.ndarray:
        if not self.data:
            return np.zeros((0, 0, 0), dtype=np.uint8)
        image = PILImage.open(io.BytesIO(self.data))
        if image.mode == "L":
            arr = np.array(image, dtype=np.uint8)
            return arr[:, :, np.newaxis]
        if image.mode != "RGB":
            image = image.convert("RGB")
        return np.array(image, dtype=np.uint8)

    @classmethod
    def from_numpy(
        cls,
        frame: np.ndarray,
        format: CompressedImageFormat = "jpeg",
        quality: int = 85,
    ) -> "CompressedImage":
        if frame.dtype != np.uint8:
            raise ValueError(f"compressed image expects uint8 frame, got {frame.dtype}")
        if frame.ndim == 2:
            image = PILImage.fromarray(frame, mode="L")
        elif frame.ndim == 3 and frame.shape[2] == 1:
            image = PILImage.fromarray(frame.squeeze(-1), mode="L")
        elif frame.ndim == 3 and frame.shape[2] == 3:
            image = PILImage.fromarray(frame, mode="RGB")
        else:
            raise ValueError(f"compressed image expects HW, HW1, or HW3 frame, got {frame.shape}")

        buffer = io.BytesIO()
        save_format = format.upper()
        kwargs = {"quality": quality} if format == "jpeg" else {}
        image.save(buffer, format=save_format, **kwargs)
        return cls(format=format, data=buffer.getvalue())

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_arrays(
            [
                pa.array([self.format], type=pa.string()),
                _data_array(self.data),
            ],
            names=["format", "data"],
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "CompressedImage":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("CompressedImage RecordBatch must contain one row")
        return cls(
            format=str(batch["format"][0].as_py()),
            data=_bytes_from_cell(batch["data"][0]),
        )
