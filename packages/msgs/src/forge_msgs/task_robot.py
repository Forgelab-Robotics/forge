from __future__ import annotations

import math
import numpy as np
import pyarrow as pa

from forge_msgs.utils import parse_int_list_from_arrow
from forge_msgs.value import (
    JointValue,
    MODE_INT_TO_STR,
    MODE_STR_TO_INT,
    UNIT_INT_TO_STR,
    UNIT_STR_TO_INT,
    ensure_record_batch,
)
from pydantic import BaseModel
from typing import Dict, List, Literal


class ProprioState(BaseModel):
    """TaskRobot 产出，本体状态（joints，不含图像）。"""

    joints: Dict[str, JointValue]
    # 本状态对应的时间戳（建议 time.monotonic()），与 ActionSequence.ref_timestamp 对齐
    timestamp: float = 0.0

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
        """列式 Arrow 格式，便于跨节点传递；下游可用 to_np_from_arrow 零拷贝转 numpy。
        每个 joint 的 mode/unit 按 joint_order 顺序编码为 list 列；timestamp 作为正式列（float64）以在 dora/IPC 传递时保留。
        """
        mode_list = [
            MODE_STR_TO_INT.get(
                self.joints[name].mode if name in self.joints else "position",
                0,
            )
            for name in joint_order
        ]
        unit_list = [
            UNIT_STR_TO_INT.get(
                self.joints[name].unit if name in self.joints else "radians",
                0,
            )
            for name in joint_order
        ]
        columns = {
            "mode": pa.array([mode_list], type=pa.list_(pa.int8())),
            "unit": pa.array([unit_list], type=pa.list_(pa.int8())),
            "timestamp": pa.array([self.timestamp], type=pa.float64()),
        }
        for name in joint_order:
            v = self.joints[name].value if name in self.joints else 0.0
            columns[name] = pa.array([v], type=pa.float32())
        return pa.RecordBatch.from_pydict(columns)

    @classmethod
    def from_arrow(
        cls, batch: pa.RecordBatch | pa.Table | bytes, joint_order: list[str]
    ) -> "ProprioState":
        """从列式 Arrow 解析；batch 可为 RecordBatch、Table 或 IPC bytes。timestamp 从列 "timestamp"（float64）读取，若无该列则 0.0。"""
        batch = ensure_record_batch(batch)
        timestamp = 0.0
        if "timestamp" in batch.schema.names and batch.num_rows > 0:
            timestamp = float(batch["timestamp"][0].as_py())
        if batch.num_rows == 0:
            return cls(
                joints={
                    name: JointValue(value=0.0, mode="position", unit="radians")
                    for name in joint_order
                },
                timestamp=timestamp,
            )
        mode_raw = batch["mode"][0]
        unit_raw = batch["unit"][0]
        mode_vals = parse_int_list_from_arrow(mode_raw, len(joint_order), MODE_INT_TO_STR, "position")
        unit_vals = parse_int_list_from_arrow(unit_raw, len(joint_order), UNIT_INT_TO_STR, "radians")
        joints = {}
        for i, name in enumerate(joint_order):
            mode_str = mode_vals[i]
            unit_str = unit_vals[i]
            if name in batch.schema.names:
                v = float(batch[name][0].as_py())
                joints[name] = JointValue(value=v, mode=mode_str, unit=unit_str)
            else:
                joints[name] = JointValue(value=0.0, mode=mode_str, unit=unit_str)
        return cls(joints=joints, timestamp=timestamp)

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
        """列式 Arrow 格式，便于跨节点传递与 dora 序列化；下游 from_arrow 解析。
        每个 joint 的 mode/unit 按 joint_order 顺序编码为 list 列。
        """
        mode_list = [
            MODE_STR_TO_INT.get(
                self.joints[name].mode if name in self.joints else "position",
                0,
            )
            for name in joint_order
        ]
        unit_list = [
            UNIT_STR_TO_INT.get(
                self.joints[name].unit if name in self.joints else "radians",
                0,
            )
            for name in joint_order
        ]
        columns = {
            "mode": pa.array([mode_list], type=pa.list_(pa.int8())),
            "unit": pa.array([unit_list], type=pa.list_(pa.int8())),
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
            "radians", "millimeters", "meters", "radians/s", "millimeters/s", "meters/s", "Nm", "A"
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
        mode_raw = batch["mode"][0]
        unit_raw = batch["unit"][0]
        mode_vals = parse_int_list_from_arrow(mode_raw, len(joint_order), MODE_INT_TO_STR, "position")
        unit_vals = parse_int_list_from_arrow(unit_raw, len(joint_order), UNIT_INT_TO_STR, "radians")
        joints = {}
        for i, name in enumerate(joint_order):
            mode_str = mode_vals[i]
            unit_str = unit_vals[i]
            if name in batch.schema.names:
                v = float(batch[name][0].as_py())
                joints[name] = JointValue(value=v, mode=mode_str, unit=unit_str)
            else:
                joints[name] = JointValue(value=0.0, mode=mode_str, unit=unit_str)
        return cls(joints=joints)


class ActionSequence(BaseModel):
    """一组 Action，用于按 tick 逐帧发送；Arrow 为多行 RecordBatch，每行一帧。"""

    actions: List[Action]
    # 可选：该序列对应的观测/生成时间戳（由上游 policy 填写，task_robot 用其加 latency 得到序列起始时刻）
    ref_timestamp: float | None = None

    def to_arrow(self, joint_order: list[str]) -> pa.RecordBatch:
        """多行 RecordBatch，每行与 Action.to_arrow 列结构一致；ref_timestamp 作为列写入，不写 metadata。"""
        ref_ts_val = self.ref_timestamp if self.ref_timestamp is not None else float("nan")

        if not self.actions:
            empty = Action(
                joints={
                    name: JointValue(value=0.0, mode="position", unit="radians")
                    for name in joint_order
                }
            )
            batch = empty.to_arrow(joint_order)
        else:
            batches = [a.to_arrow(joint_order) for a in self.actions]
            batch = pa.concat_batches(batches)

        n = batch.num_rows
        new_columns = list(batch.columns) + [
            pa.array([ref_ts_val] * n, type=pa.float64()),
        ]
        new_names = list(batch.schema.names) + ["ref_timestamp"]
        return pa.RecordBatch.from_arrays(new_columns, names=new_names)

    @classmethod
    def from_arrow(
        cls, batch: pa.RecordBatch | pa.Table | bytes, joint_order: list[str]
    ) -> "ActionSequence":
        """从多行 Arrow 解析，每行一个 Action；ref_timestamp 只从列读取，不读 metadata。"""
        batch = ensure_record_batch(batch)
        if batch.num_rows == 0:
            return cls(actions=[], ref_timestamp=None)

        ref_timestamp: float | None = None
        if "ref_timestamp" in batch.schema.names and batch.num_rows > 0:
            val = batch["ref_timestamp"][0].as_py()
            if val is not None and not (isinstance(val, float) and math.isnan(val)):
                ref_timestamp = float(val)

        actions_list: List[Action] = []
        for r in range(batch.num_rows):
            row_batch = batch.slice(r, 1)
            actions_list.append(Action.from_arrow(row_batch, joint_order))
        return cls(actions=actions_list, ref_timestamp=ref_timestamp)
