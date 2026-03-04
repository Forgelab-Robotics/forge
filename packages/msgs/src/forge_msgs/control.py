from __future__ import annotations

from typing import Any, Literal, Optional

import pyarrow as pa
from pydantic import BaseModel

from forge_msgs.value import ensure_record_batch


class SimControl(BaseModel):
    """仿真控制消息：通过 Dora 的 sim_control topic 传递。"""

    action: Literal["START", "PAUSE", "RESUME", "RESET", "STOP"]

    def to_arrow(self) -> pa.RecordBatch:
        """编码为单行 RecordBatch，schema: { action: string }。"""
        return pa.RecordBatch.from_pydict({"action": pa.array([self.action])})

    @classmethod
    def from_arrow(cls, value: Any) -> Optional["SimControl"]:
        """从 dora 传入的 value 解析出 SimControl；无法解析时返回 None。"""
        if value is None:
            return None
        try:
            batch = ensure_record_batch(value)
        except Exception:
            return None
        if batch.num_rows == 0 or "action" not in batch.schema.names:
            return None
        cell = batch["action"][0]
        if hasattr(cell, "as_py"):
            cell = cell.as_py()
        if not isinstance(cell, str):
            return None
        action = cell.strip()
        if not action:
            return None
        try:
            return cls(action=action)
        except Exception:
            return None


class RecordControl(BaseModel):
    """录制控制消息：开始/停止录制以及可选输出路径。"""

    action: Literal["START", "STOP"]
    output_path: Optional[str] = None

    def to_arrow(self) -> pa.RecordBatch:
        """编码为单行 RecordBatch，schema: { action: string, output_path: string? }。"""
        action = (self.action or "").strip()
        output = (self.output_path or "").strip()
        data: dict[str, pa.Array] = {
            "action": pa.array([action]),
        }
        if output:
            data["output_path"] = pa.array([output])
        else:
            # 使用可空列以便 from_arrow 能区分“未提供”与“空字符串”
            data["output_path"] = pa.array([None], type=pa.string())
        return pa.RecordBatch.from_pydict(data)

    @classmethod
    def from_arrow(cls, value: Any) -> Optional["RecordControl"]:
        """从 dora 传入的 value 解析出 RecordControl；无法解析时返回 None。"""
        if value is None:
            return None
        try:
            batch = ensure_record_batch(value)
        except Exception:
            return None
        if batch.num_rows == 0 or "action" not in batch.schema.names:
            return None

        # action
        cell_action = batch["action"][0]
        if hasattr(cell_action, "as_py"):
            cell_action = cell_action.as_py()
        if not isinstance(cell_action, str):
            return None
        action = cell_action.strip()
        if not action:
            return None

        # output_path（可选）
        output_path: Optional[str] = None
        if "output_path" in batch.schema.names:
            cell = batch["output_path"][0]
            if hasattr(cell, "as_py"):
                cell = cell.as_py()
            if isinstance(cell, str):
                s = cell.strip()
                if s:
                    output_path = s

        try:
            return cls(action=action, output_path=output_path)
        except Exception:
            return None


class PlaybackControl(BaseModel):
    """回放控制消息：START/PAUSE/RESUME/RESET 以及可选 MCAP 路径。"""

    action: Literal["START", "PAUSE", "RESUME", "RESET"]
    mcap_path: Optional[str] = None

    def to_arrow(self) -> pa.RecordBatch:
        """编码为单行 RecordBatch，schema: { action: string, mcap_path: string? }。"""
        action = (self.action or "").strip()
        mcap = (self.mcap_path or "").strip()
        data: dict[str, pa.Array] = {
            "action": pa.array([action]),
        }
        if mcap:
            data["mcap_path"] = pa.array([mcap])
        else:
            data["mcap_path"] = pa.array([None], type=pa.string())
        return pa.RecordBatch.from_pydict(data)

    @classmethod
    def from_arrow(cls, value: Any) -> Optional["PlaybackControl"]:
        """从 dora 传入的 value 解析出 PlaybackControl；无法解析时返回 None。"""
        if value is None:
            return None
        try:
            batch = ensure_record_batch(value)
        except Exception:
            return None
        if batch.num_rows == 0 or "action" not in batch.schema.names:
            return None

        # action
        cell_action = batch["action"][0]
        if hasattr(cell_action, "as_py"):
            cell_action = cell_action.as_py()
        if not isinstance(cell_action, str):
            return None
        action = cell_action.strip()
        if not action:
            return None

        # mcap_path（可选）
        mcap_path: Optional[str] = None
        if "mcap_path" in batch.schema.names:
            cell = batch["mcap_path"][0]
            if hasattr(cell, "as_py"):
                cell = cell.as_py()
            if isinstance(cell, str):
                s = cell.strip()
                if s:
                    mcap_path = s

        try:
            return cls(action=action, mcap_path=mcap_path)
        except Exception:
            return None

