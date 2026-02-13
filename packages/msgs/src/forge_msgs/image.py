from __future__ import annotations

import io
from enum import IntEnum
from typing import Literal

import numpy as np
import pyarrow as pa
from PIL import Image as PILImage
from pydantic import BaseModel

from forge_msgs.value import ensure_record_batch


class ImageEncoding(IntEnum):
    """图像编码/格式，用于 Arrow 列式格式的序列化。"""

    rgb8 = 0
    bgr8 = 1
    gray8 = 2
    jpeg = 3
    png = 4


ENCODING_STR_TO_INT = {
    "rgb8": ImageEncoding.rgb8,
    "bgr8": ImageEncoding.bgr8,
    "gray8": ImageEncoding.gray8,
    "jpeg": ImageEncoding.jpeg,
    "png": ImageEncoding.png,
}
ENCODING_INT_TO_STR = {v: k for k, v in ENCODING_STR_TO_INT.items()}


class Image(BaseModel):
    """统一图像消息（原始像素或压缩），用于 dora 节点之间传递。

    字段说明：
    - width/height: 图像尺寸（压缩时为原始尺寸，供下游校验）
    - channels: 原始像素时有效（1=灰度, 3=RGB/BGR）；压缩格式时为 0
    - encoding: 像素或压缩格式（rgb8/bgr8/gray8 为原始，jpeg/png 为压缩）
    - data: 原始像素 bytes（H*W*channels）或压缩 bitstream
    """

    width: int
    height: int
    channels: int = 3
    encoding: Literal["rgb8", "bgr8", "gray8", "jpeg", "png"] = "rgb8"
    data: bytes

    @property
    def is_compressed(self) -> bool:
        """是否为压缩格式（jpeg/png）。"""
        return self.encoding in ("jpeg", "png")

    def to_numpy(self) -> np.ndarray:
        """将 data 解码为 numpy uint8 数组（HWC）。支持原始像素 (rgb8/bgr8/gray8) 与压缩格式 (jpeg/png)。"""
        if self.is_compressed:
            return self._decode_compressed_to_numpy()
        if self.width <= 0 or self.height <= 0 or self.channels <= 0:
            return np.zeros((0, 0, 0), dtype=np.uint8)
        arr = np.frombuffer(self.data, dtype=np.uint8)
        expected = self.width * self.height * self.channels
        if arr.size != expected:
            raise ValueError(f"data 大小不匹配：{arr.size} != {expected}")
        return arr.reshape((self.height, self.width, self.channels))

    def _decode_compressed_to_numpy(self) -> np.ndarray:
        """用 Pillow 解码 jpeg/png，返回 HWC uint8 rgb8。"""
        if not self.data:
            return np.zeros((0, 0, 0), dtype=np.uint8)
        img = PILImage.open(io.BytesIO(self.data))
        if img.mode == "RGBA":
            img = img.convert("RGB")  # 统一为 3 通道
        elif img.mode != "RGB" and img.mode != "L":
            img = img.convert("RGB")
        arr = np.array(img, dtype=np.uint8)
        if arr.ndim == 2:
            arr = arr[:, :, np.newaxis]  # HWC, channels=1
        return arr

    def to_jpeg_bytes(self, quality: int = 85) -> bytes:
        """将当前图像转为 JPEG 字节流。已为 jpeg 时直接返回 data；raw（rgb8/bgr8/gray8）时先解码再编码；png 等压缩格式会先解码再按 jpeg 编码。"""
        if self.encoding == "jpeg" and self.data:
            return self.data
        arr = self.to_numpy()
        if arr.size == 0:
            return b""
        if self.encoding == "bgr8" and arr.shape[-1] == 3:
            arr = arr[:, :, ::-1].copy()
        if arr.ndim == 3 and arr.shape[-1] == 1:
            pil_img = PILImage.fromarray(arr.squeeze(-1), mode="L")
        else:
            pil_img = PILImage.fromarray(arr, mode="RGB")
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()

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
        """列式 Arrow 格式（单行），便于跨节点传递；data 列通过 py_buffer 复用原始 buffer，下游解析可零拷贝读取。"""
        # data 列：from_buffers + py_buffer 复用 self.data，避免大块拷贝
        n = len(self.data)
        data_offsets = np.array([0, n], dtype=np.int64)
        data_arr = pa.Array.from_buffers(
            pa.large_binary(),
            1,
            [None, pa.py_buffer(data_offsets), pa.py_buffer(self.data)],
            null_count=0,
        )
        # encoding 列：与 JointMode 一致，用 IntEnum 存 int8
        encoding_arr = pa.array([ENCODING_STR_TO_INT[self.encoding]], type=pa.int8())
        columns = {
            "width": pa.array([self.width], type=pa.int32()),
            "height": pa.array([self.height], type=pa.int32()),
            "channels": pa.array([self.channels], type=pa.int8()),
            "encoding": encoding_arr,
            "data": data_arr,
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
        enc_val = batch["encoding"][0].as_py()
        encoding = (
            ENCODING_INT_TO_STR[enc_val] if isinstance(enc_val, int) else str(enc_val)
        )
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
