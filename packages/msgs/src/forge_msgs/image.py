from __future__ import annotations

from typing import Literal

import numpy as np
import pyarrow as pa
from pydantic import BaseModel

from forge_msgs.value import ensure_record_batch


class Image(BaseModel):
    """通用图像消息（RGB/BGR/Gray），用于 dora 节点之间传递。

字段说明：
    - width/height/channels: 图像维度
    - encoding: 像素格式（当前约定 uint8）
    - data: 原始 bytes，长度应为 height * width * channels
    """

    width: int
    height: int
    channels: int = 3
    encoding: Literal["rgb8", "bgr8", "gray8"] = "rgb8"
    data: bytes

    def to_numpy(self) -> np.ndarray:
        """将 data 解码为 numpy uint8 数组（HWC）。"""
        if self.width <= 0 or self.height <= 0 or self.channels <= 0:
            return np.zeros((0, 0, 0), dtype=np.uint8)
        arr = np.frombuffer(self.data, dtype=np.uint8)
        expected = self.width * self.height * self.channels
        if arr.size != expected:
            raise ValueError(f"data 大小不匹配：{arr.size} != {expected}")
        return arr.reshape((self.height, self.width, self.channels))

    @classmethod
    def from_numpy(
        cls,
        frame: np.ndarray,
        encoding: Literal["rgb8", "bgr8", "gray8"] = "rgb8",
    ) -> "Image":
        """从 numpy (HWC) 构建 Image（uint8）。"""
        if frame.dtype != np.uint8:
            raise ValueError(f"期望 uint8，但得到 {frame.dtype}")
        if frame.ndim != 3:
            raise ValueError(f"期望 3 维数组 (HWC)，但得到 ndim={frame.ndim}")
        height, width, channels = frame.shape
        return cls(
            width=int(width),
            height=int(height),
            channels=int(channels),
            encoding=encoding,
            data=frame.tobytes(),
        )

    def to_arrow(self) -> pa.RecordBatch:
        """列式 Arrow 格式（单行），便于跨语言传输。"""
        columns = {
            "width": pa.array([self.width], type=pa.int32()),
            "height": pa.array([self.height], type=pa.int32()),
            "channels": pa.array([self.channels], type=pa.int8()),
            "encoding": pa.array([self.encoding], type=pa.string()),
            "data": pa.array([self.data], type=pa.large_binary()),
        }
        return pa.RecordBatch.from_pydict(columns)

    @classmethod
    def from_arrow(cls, batch: pa.RecordBatch | pa.Table | bytes) -> "Image":
        """从 Arrow 解析；batch 可为 RecordBatch、Table 或 IPC bytes。"""
        batch = ensure_record_batch(batch)
        if batch.num_rows == 0:
            return cls(width=0, height=0, channels=0, encoding="rgb8", data=b"")

        width = int(batch["width"][0].as_py())
        height = int(batch["height"][0].as_py())
        channels = int(batch["channels"][0].as_py())
        encoding = str(batch["encoding"][0].as_py())
        data = batch["data"][0].as_py()
        if isinstance(data, memoryview):
            data = data.tobytes()
        if not isinstance(data, (bytes, bytearray)):
            data = bytes(data)
        return cls(
            width=width,
            height=height,
            channels=channels,
            encoding=encoding,  # type: ignore[arg-type]
            data=bytes(data),
        )


class CompressedImage(BaseModel):
    """压缩图像消息（如 jpeg/png），适合可视化或远程传输。

字段说明：
    - width/height: 原始图像尺寸（可用于下游校验）
    - format: 压缩格式（jpeg/png）
    - data: 压缩后的 bitstream bytes
    """

    width: int
    height: int
    format: Literal["jpeg", "png"] = "jpeg"
    data: bytes

    def to_arrow(self) -> pa.RecordBatch:
        """列式 Arrow 格式（单行）。"""
        columns = {
            "width": pa.array([self.width], type=pa.int32()),
            "height": pa.array([self.height], type=pa.int32()),
            "format": pa.array([self.format], type=pa.string()),
            "data": pa.array([self.data], type=pa.large_binary()),
        }
        return pa.RecordBatch.from_pydict(columns)

    @classmethod
    def from_arrow(
        cls, batch: pa.RecordBatch | pa.Table | bytes
    ) -> "CompressedImage":
        """从 Arrow 解析；batch 可为 RecordBatch、Table 或 IPC bytes。"""
        batch = ensure_record_batch(batch)
        if batch.num_rows == 0:
            return cls(width=0, height=0, format="jpeg", data=b"")

        width = int(batch["width"][0].as_py())
        height = int(batch["height"][0].as_py())
        fmt = str(batch["format"][0].as_py())
        data = batch["data"][0].as_py()
        if isinstance(data, memoryview):
            data = data.tobytes()
        if not isinstance(data, (bytes, bytearray)):
            data = bytes(data)

        return cls(
            width=width,
            height=height,
            format=fmt,  # type: ignore[arg-type]
            data=bytes(data),
        )

