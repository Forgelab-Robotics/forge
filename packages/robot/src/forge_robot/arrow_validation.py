"""JointCommand / JointState Arrow 输入的 schema 校验。"""

from __future__ import annotations

from typing import Any

import pyarrow as pa
from forge_msgs.arrow import ensure_record_batch

COMMAND_MODES = {"position", "velocity", "effort", "hybrid"}


class RobotArrowSchemaError(ValueError):
    """Arrow RecordBatch 不满足当前机器人 joint_order 约定时抛出。"""


def _read_name_list(batch: pa.RecordBatch) -> list[str]:
    try:
        names = batch["name"][0].as_py()
    except Exception as e:
        raise RobotArrowSchemaError("无法读取 name 列") from e
    if not names:
        raise RobotArrowSchemaError("name 不能为空")
    if len(set(names)) != len(names):
        raise RobotArrowSchemaError("name 不能重复")
    return [str(name) for name in names]


def _validate_vector_lengths(batch: pa.RecordBatch, names: list[str], fields: tuple[str, ...]) -> None:
    for field in fields:
        try:
            values = batch[field][0].as_py()
        except Exception as e:
            raise RobotArrowSchemaError(f"无法读取 {field} 列") from e
        if values and len(values) != len(names):
            raise RobotArrowSchemaError(
                f"{field} 必须为空或长度等于 name ({len(values)} != {len(names)})"
            )


def _validate_command_mode(batch: pa.RecordBatch) -> None:
    if "mode" not in batch.schema.names:
        return
    try:
        raw_mode = batch["mode"][0].as_py()
    except Exception as e:
        raise RobotArrowSchemaError("无法读取 mode 列") from e
    mode = "position" if raw_mode is None else str(raw_mode)
    if mode not in COMMAND_MODES:
        raise RobotArrowSchemaError(f"mode 必须是 {sorted(COMMAND_MODES)} 之一")


def validate_robot_control_arrow(
    value: Any,
    joint_order: list[str],
    *,
    strict_extra_columns: bool = False,
) -> pa.RecordBatch:
    """
    将 dora 传入的 JointCommand payload 规范为 RecordBatch，并校验列名和 name。

    JointCommand schema 固定为 name / position / velocity / effort / kp / kd，
    mode 为兼容新增列；缺失时按 position 处理。
    ``joint_order`` 描述本节点可控制的关节全集；JointCommand 允许只包含其子集。

    Args:
        value: ``RecordBatch`` / ``Table`` / ``StructArray`` / ``bytes``（与 ``from_arrow`` 一致）。
        joint_order: 本节点期望的关节顺序与名称。
        strict_extra_columns: 为 True 时，不允许出现 joint_order 之外的关节名。

    Returns:
        规范化后的 ``RecordBatch``（调用方可传给 ``from_arrow``，其内部会再次 ``ensure``）。

    Raises:
        RobotArrowSchemaError: 列不满足约定时。
    """
    if not joint_order:
        raise RobotArrowSchemaError("joint_order 不能为空")

    try:
        batch = ensure_record_batch(value)
    except TypeError as e:
        raise RobotArrowSchemaError(str(e)) from e

    available = frozenset(batch.schema.names)
    if batch.num_rows == 0:
        raise RobotArrowSchemaError("RecordBatch 不能为空")

    required = {"name", "position", "velocity", "effort", "kp", "kd"}
    missing_columns = required - available
    if missing_columns:
        raise RobotArrowSchemaError(f"缺少必需列 {sorted(missing_columns)}")

    names = _read_name_list(batch)
    _validate_vector_lengths(batch, names, ("position", "velocity", "effort", "kp", "kd"))
    _validate_command_mode(batch)

    if strict_extra_columns:
        extra = set(names) - set(joint_order)
        if extra:
            raise RobotArrowSchemaError(
                f"存在未声明的 joint {sorted(extra)}；"
                f"期望 joint 恰好为 {sorted(joint_order)!r}"
            )

    return batch


def validate_robot_state_arrow(
    value: Any,
    joint_order: list[str],
    *,
    strict_extra_columns: bool = False,
) -> pa.RecordBatch:
    """校验 JointState payload。"""
    try:
        batch = ensure_record_batch(value)
    except TypeError as e:
        raise RobotArrowSchemaError(str(e)) from e
    if batch.num_rows == 0:
        raise RobotArrowSchemaError("RecordBatch 不能为空")
    available = frozenset(batch.schema.names)
    required = {"name", "position", "velocity", "effort"}
    missing_columns = required - available
    if missing_columns:
        raise RobotArrowSchemaError(f"缺少必需列 {sorted(missing_columns)}")
    names = _read_name_list(batch)
    _validate_vector_lengths(batch, names, ("position", "velocity", "effort"))
    missing = set(joint_order) - set(names)
    if missing:
        raise RobotArrowSchemaError(
            f"缺少必需 joint {sorted(missing)}；joint_order={list(joint_order)!r}"
        )
    if strict_extra_columns:
        extra = set(names) - set(joint_order)
        if extra:
            raise RobotArrowSchemaError(
                f"存在未声明的 joint {sorted(extra)}；"
                f"期望 joint 恰好为 {sorted(joint_order)!r}"
            )
    return batch
