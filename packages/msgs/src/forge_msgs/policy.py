from __future__ import annotations

from forge_msgs.value import JointValue
from pydantic import BaseModel
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    import pyarrow as pa

class PolicyObservation(BaseModel):
    timestamp: float
    joints: Dict[str, JointValue]

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
    def from_arrow(cls, array: "pa.Array") -> "PolicyAction":
        """从 dora-rs 接收的 Arrow 数组解析为 PolicyAction。"""
        return cls.model_validate(array[0].as_py())