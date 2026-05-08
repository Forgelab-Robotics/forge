from __future__ import annotations

from enum import IntEnum
from typing import Literal

from pydantic import BaseModel
import pyarrow as pa


def ensure_record_batch(
    data: "pa.RecordBatch | pa.Table | pa.Array | bytes",
) -> "pa.RecordBatch":
    """将 dora 可能传入的 bytes/Table/RecordBatch/StructArray 统一转为 RecordBatch。"""

    if isinstance(data, pa.RecordBatch):
        return data
    if isinstance(data, bytes):
        reader = pa.ipc.open_stream(data)
        return reader.read_next_batch()
    if isinstance(data, pa.Table):
        batches = data.to_batches()
        if not batches:
            return pa.RecordBatch.from_pydict({})
        return batches[0]
    if isinstance(data, pa.StructArray):
        # dora 有时把 RecordBatch 作为单列 struct 传递，每行一个 struct
        n = data.type.num_fields
        names = [data.type.field(i).name for i in range(n)]
        arrays = [data.field(i) for i in range(n)]
        return pa.RecordBatch.from_arrays(arrays, names=names)
    raise TypeError(
        f"from_arrow 需要 pa.RecordBatch、pa.Table、pa.StructArray 或 bytes，得到: {type(data)}"
    )


class JointMode(IntEnum):
    """关节模式，用于 Arrow 列式格式的零拷贝序列化。"""

    position = 0
    velocity = 1
    torque = 2
    prismatic = 3


class JointUnit(IntEnum):
    """关节单位，用于 Arrow 列式格式的零拷贝序列化。直线关节默认用 millimeters。"""

    radians = 0
    millimeters = 1
    radians_s = 2
    millimeters_s = 3
    Nm = 4
    A = 5
    meters = 6
    meters_s = 7
    unitless = 8


MODE_STR_TO_INT = {
    "position": JointMode.position,
    "velocity": JointMode.velocity,
    "torque": JointMode.torque,
    "prismatic": JointMode.prismatic,
}
MODE_INT_TO_STR = {v: k for k, v in MODE_STR_TO_INT.items()}

UNIT_STR_TO_INT = {
    "radians": JointUnit.radians,
    "millimeters": JointUnit.millimeters,
    "radians/s": JointUnit.radians_s,
    "millimeters/s": JointUnit.millimeters_s,
    "Nm": JointUnit.Nm,
    "A": JointUnit.A,
    "meters": JointUnit.meters,
    "meters/s": JointUnit.meters_s,
    "unitless": JointUnit.unitless,
}
UNIT_INT_TO_STR = {v: k for k, v in UNIT_STR_TO_INT.items()}

# 直线关节（prismatic）默认单位
UNIT_LITERAL = Literal[
    "radians", "millimeters", "meters", "radians/s", "millimeters/s", "meters/s", "Nm", "A", "unitless"
]


class JointValue(BaseModel):
    value: float
    mode: Literal["position", "velocity", "torque", "prismatic"]
    unit: UNIT_LITERAL


class ActuatorValue(BaseModel):
    value: float
    mode: Literal["position", "velocity", "torque", "prismatic"]
    unit: UNIT_LITERAL
