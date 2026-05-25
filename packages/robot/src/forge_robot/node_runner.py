"""标准 Dora 机器人节点循环：tick/command/master_joint_state 处理与 joint_state 输出。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from dora import Node
from forge_msgs import JointCommand, JointState

from .arrow_validation import RobotArrowSchemaError, validate_robot_control_arrow
from .robot_protocol import BaseRobotDriver, RobotDriver

logger = logging.getLogger(__name__)


def _joint_state_to_command(master_state: JointState) -> JointCommand:
    """将 master 的 JointState 映射为可下发的 JointCommand。"""
    return JointCommand(
        name=master_state.name,
        position=master_state.position,
        velocity=[],
        effort=[],
        kp=[],
        kd=[],
    )


def _handle_control_input(
    input_id: str,
    value: Any,
    driver: RobotDriver,
    joint_order: list[str],
    is_follower: bool,
    debug: bool,
    *,
    validate_control_arrow: bool,
    strict_extra_arrow_columns: bool,
) -> None:
    """标准控制输入处理：command / master_joint_state → set_command。"""
    match input_id:
        case "command":
            if is_follower:
                if validate_control_arrow:
                    try:
                        validate_robot_control_arrow(
                            value,
                            joint_order,
                            strict_extra_columns=strict_extra_arrow_columns,
                        )
                    except RobotArrowSchemaError as e:
                        logger.error("忽略无效 command（Arrow schema）: %s", e)
                        return
                command = JointCommand.from_arrow(value)
                if debug:
                    try:
                        sample = {
                            name: float(command.to_np([name], "position")[0])
                            for name in joint_order[:3]
                        }
                        logger.debug("收到 command，sample_joints=%s", sample)
                    except Exception:
                        pass
                driver.set_command(command)
            return
        case "master_joint_state":
            if is_follower:
                master_state = JointState.from_arrow(value)
                mirror_command = _joint_state_to_command(master_state)
                if debug:
                    try:
                        sample = {
                            name: float(mirror_command.to_np([name], "position")[0])
                            for name in joint_order[:3]
                        }
                        logger.debug(
                            "收到 master_joint_state 并转换为 command，sample_joints=%s",
                            sample,
                        )
                    except Exception:
                        pass
                driver.set_command(mirror_command)
            return
        case _:
            return


def _handle_tick(
    *,
    node: Node,
    driver: RobotDriver,
    joint_order: list[str],
    debug: bool,
    on_tick_after_state: Callable[[Node, RobotDriver], None] | None,
) -> None:
    """标准 tick 处理：读取并发送 joint_state，再执行可选附加输出。"""
    state = driver.get_state()
    node.send_output("joint_state", state.to_arrow())
    if debug:
        try:
            sample = {
                name: float(state.to_np([name], "position")[0])
                for name in joint_order[:3]
            }
            logger.debug(
                "tick 输出当前 joint_state，sample_joints=%s",
                sample,
            )
        except Exception:
            pass
    if on_tick_after_state is not None:
        on_tick_after_state(node, driver)


def run_dora_robot_node(
    driver: RobotDriver,
    *,
    joint_order: list[str] | None = None,
    is_follower: bool = True,
    debug: bool = False,
    on_tick_after_state: Callable[[Node, RobotDriver], None] | None = None,
    external_subscriptions: list[Any] | None = None,
    on_external_event: Callable[[Any], None] | None = None,
    validate_control_arrow: bool = True,
    strict_extra_arrow_columns: bool = False,
) -> int:
    """
    运行标准 Dora 机器人节点循环：tick 发 joint_state，处理 command/master_joint_state，支持可选每 tick 额外输出。

    Args:
        driver: 已连接并满足 RobotDriver 的驱动实例。
        joint_order: 关节顺序，用于命令校验和 debug 采样；若 None 且 driver 为 BaseRobotDriver 则用 driver.joint_order。
        is_follower: 是否从站（仅从站才执行 set_command）。
        debug: 是否打 debug 日志（command/master_joint_state 采样）。
        on_tick_after_state: 可选；每 tick 发送 state 后调用 (node, driver)，用于额外输出（如 image）。
        external_subscriptions: 可选 Dora external subscriptions；传入后会在 Node 上 merge_external_events。
        on_external_event: 可选 external payload handler；通常用于将 ROS2 payload 写入 driver 内部缓存。
        validate_control_arrow: 为 True 时，在解析 command 前校验 Arrow 是否包含所需关节名。
        strict_extra_arrow_columns: 为 True 时，除上述列外不允许多余列（需 validate_control_arrow=True）。

    Returns:
        0 表示正常退出。
    """
    order = joint_order
    if order is None:
        if isinstance(driver, BaseRobotDriver):
            order = driver.joint_order
        else:
            raise ValueError(
                "joint_order 必须传入，或 driver 需为 BaseRobotDriver 并实现 joint_order"
            )
    if not order:
        raise ValueError("joint_order 不能为空")

    if external_subscriptions and on_external_event is None:
        raise ValueError("external_subscriptions 需要同时传入 on_external_event")

    node = Node()
    for subscription in external_subscriptions or []:
        node.merge_external_events(subscription)

    try:
        for event in node:
            kind = event.get("kind")
            if kind == "external":
                if on_external_event is not None:
                    on_external_event(event.get("value"))
                continue
            if kind not in (None, "dora"):
                continue

            match event.get("type"):
                case "INPUT":
                    input_id = event["id"]
                    value = event.get("value")
                    if input_id == "tick":
                        _handle_tick(
                            node=node,
                            driver=driver,
                            joint_order=order,
                            debug=debug,
                            on_tick_after_state=on_tick_after_state,
                        )
                        continue
                    _handle_control_input(
                        input_id=input_id,
                        value=value,
                        driver=driver,
                        joint_order=order,
                        is_follower=is_follower,
                        debug=debug,
                        validate_control_arrow=validate_control_arrow,
                        strict_extra_arrow_columns=strict_extra_arrow_columns,
                    )
                case "STOP":
                    break
                case "ERROR":
                    logger.error(
                        "节点收到 ERROR: %s",
                        event.get("error", "unknown"),
                    )
                    break
                case _:
                    pass
    finally:
        driver.disconnect()
    return 0
