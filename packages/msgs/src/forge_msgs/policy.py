from __future__ import annotations

import numpy as np

from forge_msgs.value import JointValue
from pydantic import BaseModel
from typing import Dict, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    import pyarrow as pa


class PolicyObservation(BaseModel):
    timestamp: float
    joints: Dict[str, JointValue]

    def to_np(self, joint_order: list[str]) -> np.ndarray:
        """将观测数据编码为数组，供算法使用。"""
        return np.array(
            [
                self.joints[name].value if name in self.joints else 0.0
                for name in joint_order
            ],
            dtype=np.float32,
        )

    def to_arrow(self) -> "pa.Array":
        """转换为 dora-rs 使用的 Apache Arrow 格式，可直接用于 node.send_output()."""
        import pyarrow as pa
        return pa.array([self.model_dump()])

    @classmethod
    def from_arrow(cls, array: "pa.Array") -> "PolicyObservation":
        """从 dora-rs 接收的 Arrow 数组解析为 PolicyObservation。"""
        return cls.model_validate(array[0].as_py())


class PolicyAction(BaseModel):
    ref_timestamp: float
    joints: Dict[str, JointValue]

    def to_arrow(self) -> "pa.Array":
        """转换为 dora-rs 使用的 Apache Arrow 格式，可直接用于 node.send_output()."""
        import pyarrow as pa
        return pa.array([self.model_dump()])

    @classmethod
    def from_np(
        cls,
        action_np: np.ndarray,
        joint_order: list[str],
        ref_timestamp: float = 0.0,
        mode: Literal["position", "velocity", "torque", "prismatic"] = "position",
        unit: Literal["radians", "meters", "radians/s", "meters/s", "Nm", "A"] = "radians",
    ) -> "PolicyAction":
        """从算法输出的动作数组解码为 PolicyAction。"""
        return cls(
            ref_timestamp=ref_timestamp,
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
    def from_arrow(cls, array: "pa.Array") -> "PolicyAction":
        """从 dora-rs 接收的 Arrow 数组解析为 PolicyAction。"""
        return cls.model_validate(array[0].as_py())