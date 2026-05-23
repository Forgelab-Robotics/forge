from __future__ import annotations

from typing import Dict

import pyarrow as pa
from pydantic import BaseModel, Field

from forge_msgs.arrow import ensure_record_batch


class Pose2D(BaseModel):
    """二维位姿 (x, y, theta)，世界系位置 + 朝向（yaw，弧度）；单条记录。"""

    x: float
    y: float
    theta: float = 0.0


class Pose2DList(BaseModel):
    """二维位姿集合（按 id keyed）；独立 topic。

    Arrow 负载为多行 RecordBatch，包含列：id/x/y/theta，每行一条 pose。
    """

    poses: Dict[str, Pose2D] = Field(default_factory=dict)

    def to_arrow(self) -> pa.RecordBatch:
        """列式 Arrow 格式（多行），每行一个 Pose2D。"""
        if not self.poses:
            return pa.RecordBatch.from_pydict(
                {
                    "id": pa.array([], type=pa.string()),
                    "x": pa.array([], type=pa.float64()),
                    "y": pa.array([], type=pa.float64()),
                    "theta": pa.array([], type=pa.float64()),
                }
            )

        # 为可复现与跨进程一致性，按 id 排序输出
        ids = sorted(self.poses.keys())
        return pa.RecordBatch.from_pydict(
            {
                "id": pa.array(ids, type=pa.string()),
                "x": pa.array([self.poses[i].x for i in ids], type=pa.float64()),
                "y": pa.array([self.poses[i].y for i in ids], type=pa.float64()),
                "theta": pa.array(
                    [self.poses[i].theta for i in ids], type=pa.float64()
                ),
            }
        )

    @classmethod
    def from_arrow(cls, batch: "pa.RecordBatch | pa.Table | bytes") -> "Pose2DList":
        """从 Arrow 解析；batch 可为 RecordBatch、Table 或 IPC bytes。"""
        batch = ensure_record_batch(batch)
        if batch.num_rows == 0:
            return cls(poses={})

        # 兼容旧格式：无 id 列时，用行号作为 key
        has_id = "id" in batch.schema.names

        poses: Dict[str, Pose2D] = {}
        for i in range(batch.num_rows):
            pid = str(batch["id"][i].as_py()) if has_id else str(i)
            x = float(batch["x"][i].as_py())
            y = float(batch["y"][i].as_py())
            theta = float(batch["theta"][i].as_py())
            if pid in poses:
                raise ValueError(f"Pose2DList.from_arrow: duplicate id '{pid}'")
            poses[pid] = Pose2D(x=x, y=y, theta=theta)
        return cls(poses=poses)

