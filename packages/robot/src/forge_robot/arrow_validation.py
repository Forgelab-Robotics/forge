"""RobotAction / RobotState 控制类 Arrow 输入的 schema 校验。"""

from __future__ import annotations

from typing import Any

import pyarrow as pa
from forge_msgs.value import ensure_record_batch


class RobotArrowSchemaError(ValueError):
    """Arrow RecordBatch 不满足当前机器人 actuator_order 约定时抛出。"""


def validate_robot_control_arrow(
    value: Any,
    actuator_order: list[str],
    *,
    strict_extra_columns: bool = False,
) -> pa.RecordBatch:
    """
    将 dora 传入的 payload 规范为 RecordBatch，并校验列名。

    要求存在 ``mode`` / ``unit`` 列，且包含 actuator_order 中每个执行器名，
    避免缺失执行器导致难排查的接线错误。

    Args:
        value: ``RecordBatch`` / ``Table`` / ``StructArray`` / ``bytes``（与 ``from_arrow`` 一致）。
        actuator_order: 本节点期望的执行器顺序与列名。
        strict_extra_columns: 为 True 时，不允许出现 actuator_order 之外的执行器列。

    Returns:
        规范化后的 ``RecordBatch``（调用方可传给 ``from_arrow``，其内部会再次 ``ensure``）。

    Raises:
        RobotArrowSchemaError: 列不满足约定时。
    """
    if not actuator_order:
        raise RobotArrowSchemaError("actuator_order 不能为空")

    try:
        batch = ensure_record_batch(value)
    except TypeError as e:
        raise RobotArrowSchemaError(str(e)) from e

    available = frozenset(batch.schema.names)
    missing_meta = {"mode", "unit"} - available
    if missing_meta:
        raise RobotArrowSchemaError(f"缺少必需列 {sorted(missing_meta)}")
    if batch.num_rows == 0:
        raise RobotArrowSchemaError("RecordBatch 不能为空")

    missing = set(actuator_order) - available
    if missing:
        raise RobotArrowSchemaError(
            f"缺少必需 actuator {sorted(missing)}；actuator_order={list(actuator_order)!r}"
        )

    if strict_extra_columns:
        extra = available - set(actuator_order) - {"mode", "unit"}
        if extra:
            raise RobotArrowSchemaError(
                f"存在未声明的 actuator {sorted(extra)}；"
                f"期望 actuator 恰好为 {sorted(actuator_order)!r}"
            )

    return batch
