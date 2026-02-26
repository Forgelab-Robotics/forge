from __future__ import annotations

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
    # 本状态对应的逻辑 step，与 ActionSequence.start_step 对齐；policy 可据此设置返回序列的 start_step
    step: int = 0

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
        每个 joint 的 mode/unit 按 joint_order 顺序编码为 list 列；step 放在 schema metadata 中。
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
        batch = pa.RecordBatch.from_pydict(columns)
        schema = batch.schema
        metadata = dict(schema.metadata or {})
        metadata[b"step"] = str(self.step).encode("utf-8")
        new_schema = schema.with_metadata(metadata)
        return pa.RecordBatch.from_arrays(list(batch.columns), schema=new_schema)

    @classmethod
    def from_arrow(
        cls, batch: pa.RecordBatch | pa.Table | bytes, joint_order: list[str]
    ) -> "ProprioState":
        """从列式 Arrow 解析；batch 可为 RecordBatch、Table 或 IPC bytes。step 从 schema metadata 读取，缺省为 0。"""
        batch = ensure_record_batch(batch)
        step = 0
        metadata = batch.schema.metadata or {}
        raw_step = metadata.get(b"step")
        if raw_step is not None:
            try:
                step = int(raw_step.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                step = 0
        if batch.num_rows == 0:
            return cls(
                joints={
                    name: JointValue(value=0.0, mode="position", unit="radians")
                    for name in joint_order
                },
                step=step,
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
        return cls(joints=joints, step=step)

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
    # 可选：该序列对应的观测/生成时间戳（由上游 policy 填写）
    ref_timestamp: float | None = None
    # 可选：本序列第一帧对应的逻辑 step（50 Hz 等对齐场景下由上游填写，task_robot 优先使用）
    start_step: int | None = None

    def to_arrow(self, joint_order: list[str]) -> pa.RecordBatch:
        """多行 RecordBatch，每行与 Action.to_arrow 列结构一致。"""
        if not self.actions:
            empty = Action(
                joints={
                    name: JointValue(value=0.0, mode="position", unit="radians")
                    for name in joint_order
                }
            )
            return empty.to_arrow(joint_order)
        batches = [a.to_arrow(joint_order) for a in self.actions]
        batch = pa.concat_batches(batches)

        # 在 Arrow schema metadata 中附带 ref_timestamp / start_step（若存在），不改变列结构
        if self.ref_timestamp is not None or self.start_step is not None:
            schema = batch.schema
            metadata = dict(schema.metadata or {})
            if self.ref_timestamp is not None:
                metadata[b"ref_timestamp"] = str(self.ref_timestamp).encode("utf-8")
            if self.start_step is not None:
                metadata[b"start_step"] = str(self.start_step).encode("utf-8")
            new_schema = schema.with_metadata(metadata)
            batch = pa.RecordBatch.from_arrays(list(batch.columns), schema=new_schema)

        return batch

    @classmethod
    def from_arrow(
        cls, batch: pa.RecordBatch | pa.Table | bytes, joint_order: list[str]
    ) -> "ActionSequence":
        """从多行 Arrow 解析，每行一个 Action。单行时返回长度为 1 的序列。"""
        batch = ensure_record_batch(batch)
        if batch.num_rows == 0:
            return cls(actions=[], ref_timestamp=None, start_step=None)

        metadata = batch.schema.metadata or {}
        ref_timestamp: float | None = None
        raw_ts = metadata.get(b"ref_timestamp")
        if raw_ts is not None:
            try:
                ref_timestamp = float(raw_ts.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                ref_timestamp = None

        start_step: int | None = None
        raw_step = metadata.get(b"start_step")
        if raw_step is not None:
            try:
                start_step = int(raw_step.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                start_step = None

        actions_list: List[Action] = []
        for r in range(batch.num_rows):
            row_batch = batch.slice(r, 1)
            actions_list.append(Action.from_arrow(row_batch, joint_order))
        return cls(actions=actions_list, ref_timestamp=ref_timestamp, start_step=start_step)
