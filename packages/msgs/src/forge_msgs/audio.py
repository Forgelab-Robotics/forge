from __future__ import annotations

from typing import Literal, Self

import numpy as np
import pyarrow as pa
from pydantic import BaseModel, model_validator

from forge_msgs.arrow import ensure_record_batch

AudioSampleFormat = Literal["f32le", "s16le"]

_SAMPLE_FORMAT_INFO: dict[str, np.dtype] = {
    "f32le": np.dtype("<f4"),
    "s16le": np.dtype("<i2"),
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


class AudioChunk(BaseModel):
    """Uncompressed interleaved PCM audio payload for Dora/Arrow transport."""

    sample_rate: int
    channels: int
    sample_format: AudioSampleFormat
    frame_count: int
    data: bytes

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be greater than 0")
        if self.channels <= 0:
            raise ValueError("channels must be greater than 0")
        if self.frame_count < 0:
            raise ValueError("frame_count must be >= 0")
        dtype = _SAMPLE_FORMAT_INFO[self.sample_format]
        expected = self.frame_count * self.channels * dtype.itemsize
        if len(self.data) != expected:
            raise ValueError(
                "data length must equal frame_count * channels * bytes_per_sample "
                f"({len(self.data)} != {expected})"
            )
        return self

    @property
    def dtype(self) -> np.dtype:
        return _SAMPLE_FORMAT_INFO[self.sample_format]

    def to_numpy(self) -> np.ndarray:
        values = np.frombuffer(self.data, dtype=self.dtype)
        if self.channels == 1:
            return values.copy()
        return values.reshape((self.frame_count, self.channels)).copy()

    @classmethod
    def from_numpy(
        cls,
        audio: np.ndarray,
        *,
        sample_rate: int,
        sample_format: AudioSampleFormat = "f32le",
    ) -> "AudioChunk":
        if sample_format not in _SAMPLE_FORMAT_INFO:
            raise ValueError(f"unsupported audio sample format: {sample_format}")
        expected_dtype = _SAMPLE_FORMAT_INFO[sample_format]
        frame = np.asarray(audio)
        if frame.dtype != expected_dtype:
            frame = frame.astype(expected_dtype, copy=False)
        if frame.ndim == 1:
            frame_count = frame.shape[0]
            channels = 1
        elif frame.ndim == 2:
            frame_count, channels = frame.shape
        else:
            raise ValueError(f"audio expects shape (frames,) or (frames, channels), got {frame.shape}")
        contiguous = np.ascontiguousarray(frame, dtype=expected_dtype)
        return cls(
            sample_rate=sample_rate,
            channels=int(channels),
            sample_format=sample_format,
            frame_count=int(frame_count),
            data=contiguous.tobytes(),
        )

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_arrays(
            [
                pa.array([self.sample_rate], type=pa.uint32()),
                pa.array([self.channels], type=pa.uint32()),
                pa.array([self.sample_format], type=pa.string()),
                pa.array([self.frame_count], type=pa.uint32()),
                _data_array(self.data),
            ],
            names=["sample_rate", "channels", "sample_format", "frame_count", "data"],
        )

    @classmethod
    def from_arrow(cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes) -> "AudioChunk":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("AudioChunk RecordBatch must contain one row")
        return cls(
            sample_rate=int(batch["sample_rate"][0].as_py()),
            channels=int(batch["channels"][0].as_py()),
            sample_format=str(batch["sample_format"][0].as_py()),  # type: ignore[arg-type]
            frame_count=int(batch["frame_count"][0].as_py()),
            data=_bytes_from_cell(batch["data"][0]),
        )
