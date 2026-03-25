from __future__ import annotations

import numpy as np
import pyarrow as pa

from forge_msgs.utils import parse_int_list_from_arrow
from forge_msgs.value import (
    ActuatorValue,
    MODE_INT_TO_STR,
    MODE_STR_TO_INT,
    UNIT_INT_TO_STR,
    UNIT_STR_TO_INT,
    ensure_record_batch,
)
from pydantic import BaseModel
from typing import Dict, Literal


class RobotState(BaseModel):
    """Robot 产出，机器人状态。"""

    actuators: Dict[str, ActuatorValue]

    def to_np(self, actuator_order: list[str]) -> np.ndarray:
        """将状态数据编码为数组。"""
        return np.array(
            [
                self.actuators[name].value if name in self.actuators else 0.0
                for name in actuator_order
            ],
            dtype=np.float32,
        )

    def to_arrow(self, actuator_order: list[str]) -> pa.RecordBatch:
        """列式 Arrow 格式，便于跨节点传递；下游可用 to_np_from_arrow 零拷贝转 numpy。
        每个 actuator 的 mode/unit 按 actuator_order 顺序编码为 list 列。
        """
        mode_list = [
            MODE_STR_TO_INT.get(
                self.actuators[name].mode if name in self.actuators else "position",
                0,
            )
            for name in actuator_order
        ]
        unit_list = [
            UNIT_STR_TO_INT.get(
                self.actuators[name].unit if name in self.actuators else "radians",
                0,
            )
            for name in actuator_order
        ]
        columns = {
            "mode": pa.array([mode_list], type=pa.list_(pa.int8())),
            "unit": pa.array([unit_list], type=pa.list_(pa.int8())),
        }
        for name in actuator_order:
            v = self.actuators[name].value if name in self.actuators else 0.0
            columns[name] = pa.array([v], type=pa.float32())
        return pa.RecordBatch.from_pydict(columns)

    @classmethod
    def from_arrow(
        cls, batch: pa.RecordBatch | pa.Table | bytes, actuator_order: list[str]
    ) -> "RobotState":
        """从列式 Arrow 解析；batch 可为 RecordBatch、Table 或 IPC bytes。"""
        batch = ensure_record_batch(batch)
        if batch.num_rows == 0:
            return cls(
                actuators={
                    name: ActuatorValue(value=0.0, mode="position", unit="radians")
                    for name in actuator_order
                }
            )
        mode_raw = batch["mode"][0]
        unit_raw = batch["unit"][0]
        mode_vals = parse_int_list_from_arrow(mode_raw, len(actuator_order), MODE_INT_TO_STR, "position")
        unit_vals = parse_int_list_from_arrow(unit_raw, len(actuator_order), UNIT_INT_TO_STR, "radians")
        actuators = {}
        for i, name in enumerate(actuator_order):
            mode_str = mode_vals[i]
            unit_str = unit_vals[i]
            if name in batch.schema.names:
                v = float(batch[name][0].as_py())
                actuators[name] = ActuatorValue(value=v, mode=mode_str, unit=unit_str)
            else:
                actuators[name] = ActuatorValue(value=0.0, mode=mode_str, unit=unit_str)
        return cls(actuators=actuators)

    @classmethod
    def to_np_from_arrow(
        cls, batch: pa.RecordBatch | pa.Table | bytes, actuator_order: list[str]
    ) -> np.ndarray:
        """从 Arrow 转 numpy；batch 可为 RecordBatch、Table 或 IPC bytes。"""
        batch = ensure_record_batch(batch)
        parts = []
        for name in actuator_order:
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


class RobotAction(BaseModel):
    """输入 Robot 的动作。"""

    actuators: Dict[str, ActuatorValue]

    def to_np(self, actuator_order: list[str]) -> np.ndarray:
        """将动作数据编码为数组。"""
        return np.array(
            [
                self.actuators[name].value if name in self.actuators else 0.0
                for name in actuator_order
            ],
            dtype=np.float32,
        )

    def to_arrow(self, actuator_order: list[str]) -> pa.RecordBatch:
        """列式 Arrow 格式，便于跨节点传递与 dora 序列化；下游 from_arrow 解析。
        每个 actuator 的 mode/unit 按 actuator_order 顺序编码为 list 列。
        """
        mode_list = [
            MODE_STR_TO_INT.get(
                self.actuators[name].mode if name in self.actuators else "position",
                0,
            )
            for name in actuator_order
        ]
        unit_list = [
            UNIT_STR_TO_INT.get(
                self.actuators[name].unit if name in self.actuators else "radians",
                0,
            )
            for name in actuator_order
        ]
        columns = {
            "mode": pa.array([mode_list], type=pa.list_(pa.int8())),
            "unit": pa.array([unit_list], type=pa.list_(pa.int8())),
        }
        for name in actuator_order:
            v = self.actuators[name].value if name in self.actuators else 0.0
            columns[name] = pa.array([v], type=pa.float32())
        return pa.RecordBatch.from_pydict(columns)

    @classmethod
    def from_np(
        cls,
        action_np: np.ndarray,
        actuator_order: list[str],
        mode: Literal["position", "velocity", "torque", "prismatic"] = "position",
        unit: Literal[
            "radians", "millimeters", "meters", "radians/s", "millimeters/s", "meters/s", "Nm", "A"
        ] = "radians",
    ) -> "RobotAction":
        """从数组解码为 RobotAction。"""
        return cls(
            actuators={
                name: ActuatorValue(
                    value=float(action_np[i]) if i < len(action_np) else 0.0,
                    mode=mode,
                    unit=unit,
                )
                for i, name in enumerate(actuator_order)
            },
        )

    @classmethod
    def from_arrow(
        cls, batch: pa.RecordBatch | pa.Table | bytes, actuator_order: list[str]
    ) -> "RobotAction":
        """从列式 Arrow 解析；batch 可为 RecordBatch、Table 或 IPC bytes。"""
        batch = ensure_record_batch(batch)
        if batch.num_rows == 0:
            return cls(
                actuators={
                    name: ActuatorValue(value=0.0, mode="position", unit="radians")
                    for name in actuator_order
                }
            )
        mode_raw = batch["mode"][0]
        unit_raw = batch["unit"][0]
        mode_vals = parse_int_list_from_arrow(mode_raw, len(actuator_order), MODE_INT_TO_STR, "position")
        unit_vals = parse_int_list_from_arrow(unit_raw, len(actuator_order), UNIT_INT_TO_STR, "radians")
        actuators = {}
        for i, name in enumerate(actuator_order):
            mode_str = mode_vals[i]
            unit_str = unit_vals[i]
            if name in batch.schema.names:
                v = float(batch[name][0].as_py())
                actuators[name] = ActuatorValue(value=v, mode=mode_str, unit=unit_str)
            else:
                actuators[name] = ActuatorValue(value=0.0, mode=mode_str, unit=unit_str)
        return cls(actuators=actuators)
