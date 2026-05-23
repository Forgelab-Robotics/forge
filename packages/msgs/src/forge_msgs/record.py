"""录制控制相关消息：路径等，供 control_gateway ↔ mcap_recorder 使用。

目前仅定义 RecordingPath，内部是一个字符串字段 path，便于后续扩展更多字段。
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa

from forge_msgs.arrow import ensure_record_batch
from pydantic import BaseModel


class RecordingPath(BaseModel):
    """录制路径消息（固定格式）。

    - 语义：单条 UTF-8 路径字符串，用于 start_recording 的 value。
    - Arrow 格式：单行 RecordBatch，schema: { path: string }。
    - 发送端：`node.send_output("start_recording", RecordingPath.to_arrow(path))`
    - 接收端：`msg = RecordingPath.from_arrow(event["value"])` / `msg.path`
    """

    path: str

    def to_arrow(self) -> pa.RecordBatch:
        """将路径字符串编码为 Arrow RecordBatch，schema: { path: string }。"""
        path = (self.path or "").strip()
        return pa.RecordBatch.from_pydict({"path": pa.array([path])})

    @classmethod
    def from_arrow(cls, value: Any) -> "RecordingPath | None":
        """从 dora 传入的 value 解析出 RecordingPath；无法解析时返回 None。"""
        if value is None:
            return None  # type: ignore[return-value]
        # 统一转为 RecordBatch（支持 RecordBatch / Table / StructArray / bytes）
        try:
            batch = ensure_record_batch(value)
        except Exception:
            return None  # type: ignore[return-value]
        if batch.num_rows == 0:
            return None  # type: ignore[return-value]
        if "path" not in batch.schema.names:
            return None  # type: ignore[return-value]
        col = batch["path"]
        if len(col) == 0:
            return None  # type: ignore[return-value]
        cell = col[0]
        # Arrow 标量：优先 as_py()
        if hasattr(cell, "as_py"):
            cell = cell.as_py()
        if isinstance(cell, str):
            s = cell.strip()
            if not s:
                return None  # type: ignore[return-value]
            return cls(path=s)
        return None  # type: ignore[return-value]
