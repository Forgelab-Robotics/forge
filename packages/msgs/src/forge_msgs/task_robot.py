from __future__ import annotations

import numpy as np
import pyarrow as pa

from forge_msgs.value import (
    JointValue,
    MODE_INT_TO_STR,
    MODE_STR_TO_INT,
    UNIT_INT_TO_STR,
    UNIT_STR_TO_INT,
    ensure_record_batch,
)
from pydantic import BaseModel
from typing import Dict, Literal


class ProprioState(BaseModel):
    """TaskRobot 产出，本体状态（joints，不含图像）。"""

    joints: Dict[str, JointValue]

    def to_np(self, joint_order: list[str]) -> np.ndarray:
        """将本体状态编码为数组，供算法使用。"""
        return np.array(
            [
                self.joints[name].value if name in self.joints else 0.0
                for name in joint_order
            ],
            dtype=np.float32,
        )

    def to_arrow(self, joint_order: list[str]) -> pa.RecordBatch:
        """列式 Arrow 格式，便于跨节点传递；下游可用 to_np_from_arrow 零拷贝转 numpy。"""
        mode_int = MODE_STR_TO_INT.get(
            next((j.mode for j in self.joints.values()), "position"), 0
        )
        unit_int = UNIT_STR_TO_INT.get(
            next((j.unit for j in self.joints.values()), "radians"), 0
        )
        columns = {
            "mode": pa.array([mode_int], type=pa.int8()),
            "unit": pa.array([unit_int], type=pa.int8()),
        }
        for name in joint_order:
            v = self.joints[name].value if name in self.joints else 0.0
            columns[name] = pa.array([v], type=pa.float32())
        return pa.RecordBatch.from_pydict(columns)

    @classmethod
    def from_arrow(
        cls, batch: pa.RecordBatch | pa.Table | bytes, joint_order: list[str]
    ) -> "ProprioState":
        """从列式 Arrow 解析；batch 可为 RecordBatch、Table 或 IPC bytes。"""
        batch = ensure_record_batch(batch)
        if batch.num_rows == 0:
            return cls(
                joints={
                    name: JointValue(value=0.0, mode="position", unit="radians")
                    for name in joint_order
                }
            )
        mode_str = MODE_INT_TO_STR.get(int(batch["mode"][0].as_py()), "position")
        unit_str = UNIT_INT_TO_STR.get(int(batch["unit"][0].as_py()), "radians")
        joints = {}
        for name in joint_order:
            if name in batch.schema.names:
                v = float(batch[name][0].as_py())
                joints[name] = JointValue(value=v, mode=mode_str, unit=unit_str)
            else:
                joints[name] = JointValue(value=0.0, mode=mode_str, unit=unit_str)
        return cls(joints=joints)

    @classmethod
    def to_np_from_arrow(
        cls, batch: pa.RecordBatch | pa.Table | bytes, joint_order: list[str]
    ) -> np.ndarray:
        """从 Arrow 转 numpy；batch 可为 RecordBatch、Table 或 IPC bytes。"""
        batch = ensure_record_batch(batch)
        parts = []
        for name in joint_order:
            if name in batch.schema.names:
                col = batch.column(name)
                try:
                    arr = col.to_numpy(zero_copy_only=True)
                except Exception:
                    arr = col.to_numpy(zero_copy_only=False)
                parts.append(arr)
            else:
                parts.append(np.array([0.0], dtype=np.float32))
        if not parts:
            return np.array([], dtype=np.float32)
        return np.concatenate(parts).astype(np.float32)


class Action(BaseModel):
    """输入 TaskRobot 的动作。"""

    joints: Dict[str, JointValue]

    def to_arrow(self, joint_order: list[str]) -> pa.RecordBatch:
        """列式 Arrow 格式，便于跨节点传递与 dora 序列化；下游 from_arrow 解析。"""
        mode_int = MODE_STR_TO_INT.get(
            next((j.mode for j in self.joints.values()), "position"), 0
        )
        unit_int = UNIT_STR_TO_INT.get(
            next((j.unit for j in self.joints.values()), "radians"), 0
        )
        columns = {
            "mode": pa.array([mode_int], type=pa.int8()),
            "unit": pa.array([unit_int], type=pa.int8()),
        }
        for name in joint_order:
            v = self.joints[name].value if name in self.joints else 0.0
            columns[name] = pa.array([v], type=pa.float32())
        return pa.RecordBatch.from_pydict(columns)

    @classmethod
    def from_np(
        cls,
        action_np: np.ndarray,
        joint_order: list[str],
        mode: Literal["position", "velocity", "torque", "prismatic"] = "position",
        unit: Literal[
            "radians", "meters", "radians/s", "meters/s", "Nm", "A"
        ] = "radians",
    ) -> "Action":
        """从算法输出的动作数组解码为 Action。"""
        return cls(
            joints={
                name: JointValue(
                    value=float(action_np[i]) if i < len(action_np) else 0.0,
                    mode=mode,
                    unit=unit,
                )
                for i, name in enumerate(joint_order)
            },
        )

    @classmethod
    def from_arrow(
        cls, batch: pa.RecordBatch | pa.Table | bytes, joint_order: list[str]
    ) -> "Action":
        """从列式 Arrow 解析；batch 可为 RecordBatch、Table 或 IPC bytes。"""
        batch = ensure_record_batch(batch)
        if batch.num_rows == 0:
            return cls(
                joints={
                    name: JointValue(value=0.0, mode="position", unit="radians")
                    for name in joint_order
                }
            )
        mode_str = MODE_INT_TO_STR.get(int(batch["mode"][0].as_py()), "position")
        unit_str = UNIT_INT_TO_STR.get(int(batch["unit"][0].as_py()), "radians")
        joints = {}
        for name in joint_order:
            if name in batch.schema.names:
                v = float(batch[name][0].as_py())
                joints[name] = JointValue(value=v, mode=mode_str, unit=unit_str)
            else:
                joints[name] = JointValue(value=0.0, mode=mode_str, unit=unit_str)
        return cls(joints=joints)
