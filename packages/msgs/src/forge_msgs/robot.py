from __future__ import annotations

import numpy as np
import pyarrow as pa

from forge_msgs.value import (
    ActuatorValue,
    MODE_INT_TO_STR,
    MODE_STR_TO_INT,
    UNIT_INT_TO_STR,
    UNIT_STR_TO_INT,
)
from pydantic import BaseModel
from typing import Dict, Literal


class RobotState(BaseModel):
    """Robot 产出，机器人状态。"""

    timestamp: float
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
        """列式 Arrow 格式，支持零拷贝接收。"""
        mode_int = MODE_STR_TO_INT.get(
            next((a.mode for a in self.actuators.values()), "position"), 0
        )
        unit_int = UNIT_STR_TO_INT.get(
            next((a.unit for a in self.actuators.values()), "radians"), 0
        )
        columns = {
            "timestamp": pa.array([self.timestamp], type=pa.float64()),
            "mode": pa.array([mode_int], type=pa.int8()),
            "unit": pa.array([unit_int], type=pa.int8()),
        }
        for name in actuator_order:
            v = self.actuators[name].value if name in self.actuators else 0.0
            columns[name] = pa.array([v], type=pa.float32())
        return pa.RecordBatch.from_pydict(columns)

    @classmethod
    def from_arrow(
        cls, batch: pa.RecordBatch, actuator_order: list[str]
    ) -> "RobotState":
        """从列式 Arrow 解析。"""
        timestamp = float(batch["timestamp"][0].as_py())
        mode_str = MODE_INT_TO_STR.get(int(batch["mode"][0].as_py()), "position")
        unit_str = UNIT_INT_TO_STR.get(int(batch["unit"][0].as_py()), "radians")
        actuators = {}
        for name in actuator_order:
            if name in batch.schema.names:
                v = float(batch[name][0].as_py())
                actuators[name] = ActuatorValue(value=v, mode=mode_str, unit=unit_str)
        return cls(timestamp=timestamp, actuators=actuators)

    @classmethod
    def to_np_from_arrow(
        cls, batch: pa.RecordBatch, actuator_order: list[str]
    ) -> np.ndarray:
        """从 Arrow 零拷贝转 numpy。"""
        return np.concatenate(
            [
                batch.column(name).to_numpy(zero_copy_only=True)
                for name in actuator_order
                if name in batch.schema.names
            ]
        ).astype(np.float32)


class RobotAction(BaseModel):
    """输入 Robot 的动作。"""

    timestamp: float
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
        """列式 Arrow 格式。"""
        mode_int = MODE_STR_TO_INT.get(
            next((a.mode for a in self.actuators.values()), "position"), 0
        )
        unit_int = UNIT_STR_TO_INT.get(
            next((a.unit for a in self.actuators.values()), "radians"), 0
        )
        columns = {
            "timestamp": pa.array([self.timestamp], type=pa.float64()),
            "mode": pa.array([mode_int], type=pa.int8()),
            "unit": pa.array([unit_int], type=pa.int8()),
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
        timestamp: float = 0.0,
        mode: Literal["position", "velocity", "torque", "prismatic"] = "position",
        unit: Literal["radians", "meters", "radians/s", "meters/s", "Nm", "A"] = "radians",
    ) -> "RobotAction":
        """从数组解码为 RobotAction。"""
        return cls(
            timestamp=timestamp,
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
        cls, batch: pa.RecordBatch, actuator_order: list[str]
    ) -> "RobotAction":
        """从列式 Arrow 解析。"""
        timestamp = float(batch["timestamp"][0].as_py())
        mode_str = MODE_INT_TO_STR.get(int(batch["mode"][0].as_py()), "position")
        unit_str = UNIT_INT_TO_STR.get(int(batch["unit"][0].as_py()), "radians")
        actuators = {}
        for name in actuator_order:
            if name in batch.schema.names:
                v = float(batch[name][0].as_py())
                actuators[name] = ActuatorValue(value=v, mode=mode_str, unit=unit_str)
        return cls(timestamp=timestamp, actuators=actuators)
