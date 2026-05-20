"""标准 Dora 机器人节点循环：tick/action/master_state 处理与 state 输出。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from dora import Node
from forge_msgs import RobotAction, RobotState

from .arrow_validation import RobotArrowSchemaError, validate_robot_control_arrow
from .robot_protocol import BaseRobotDriver, RobotDriver

logger = logging.getLogger(__name__)


def _robot_state_to_action(master_state: RobotState) -> RobotAction:
    """将 master 的 RobotState 映射为可下发的 actuator RobotAction。"""
    return RobotAction(actuators=master_state.actuators)


def _handle_control_input(
    input_id: str,
    value: Any,
    driver: RobotDriver,
    actuator_order: list[str],
    is_follower: bool,
    debug: bool,
    *,
    validate_control_arrow: bool,
    strict_extra_arrow_columns: bool,
) -> None:
    """标准控制输入处理：action / master_state → set_actuators。"""
    match input_id:
        case "action":
            if is_follower:
                if validate_control_arrow:
                    try:
                        validate_robot_control_arrow(
                            value,
                            actuator_order,
                            strict_extra_columns=strict_extra_arrow_columns,
                        )
                    except RobotArrowSchemaError as e:
                        logger.error("忽略无效 action（Arrow schema）: %s", e)
                        return
                action = RobotAction.from_arrow(value, actuator_order)
                if debug:
                    try:
                        sample = {
                            name: float(action.actuators[name].value)
                            for name in actuator_order[:3]
                            if name in action.actuators
                        }
                        logger.debug("收到 action，sample_actuators=%s", sample)
                    except Exception:
                        pass
                driver.set_actuators(action)
            return
        case "master_state":
            if is_follower:
                if validate_control_arrow:
                    try:
                        validate_robot_control_arrow(
                            value,
                            actuator_order,
                            strict_extra_columns=strict_extra_arrow_columns,
                        )
                    except RobotArrowSchemaError as e:
                        logger.error("忽略无效 master_state（Arrow schema）: %s", e)
                        return
                master_state = RobotState.from_arrow(value, actuator_order)
                mirror_action = _robot_state_to_action(master_state)
                if debug:
                    try:
                        sample = {
                            name: float(mirror_action.actuators[name].value)
                            for name in actuator_order[:3]
                            if name in mirror_action.actuators
                        }
                        logger.debug(
                            "收到 master_state 并转换为 action，sample_actuators=%s",
                            sample,
                        )
                    except Exception:
                        pass
                driver.set_actuators(mirror_action)
            return
        case _:
            return


def _handle_tick(
    *,
    node: Node,
    driver: RobotDriver,
    actuator_order: list[str],
    debug: bool,
    on_tick_after_state: Callable[[Node, RobotDriver], None] | None,
) -> None:
    """标准 tick 处理：读取并发送 state，再执行可选附加输出。"""
    state = driver.get_state()
    node.send_output("state", state.to_arrow(actuator_order))
    if debug:
        try:
            sample = {
                name: float(state.actuators[name].value)
                for name in actuator_order[:3]
                if name in state.actuators
            }
            logger.debug(
                "tick 输出当前 state，sample_actuators=%s",
                sample,
            )
        except Exception:
            pass
    if on_tick_after_state is not None:
        on_tick_after_state(node, driver)


def run_dora_robot_node(
    driver: RobotDriver,
    *,
    actuator_order: list[str] | None = None,
    is_follower: bool = True,
    debug: bool = False,
    on_tick_after_state: Callable[[Node, RobotDriver], None] | None = None,
    external_subscriptions: list[Any] | None = None,
    on_external_event: Callable[[Any], None] | None = None,
    validate_control_arrow: bool = True,
    strict_extra_arrow_columns: bool = False,
) -> int:
    """
    运行标准 Dora 机器人节点循环：tick 发 state，处理 action/master_state，支持可选每 tick 额外输出。

    Args:
        driver: 已连接并满足 RobotDriver 的驱动实例。
        actuator_order: 执行器顺序，用于 Arrow 序列化；若 None 且 driver 为 BaseRobotDriver 则用 driver.actuator_order。
        is_follower: 是否从站（仅从站才执行 set_actuators）。
        debug: 是否打 debug 日志（action/master_state 采样）。
        on_tick_after_state: 可选；每 tick 发送 state 后调用 (node, driver)，用于额外输出（如 image）。
        external_subscriptions: 可选 Dora external subscriptions；传入后会在 Node 上 merge_external_events。
        on_external_event: 可选 external payload handler；通常用于将 ROS2 payload 写入 driver 内部缓存。
        validate_control_arrow: 为 True 时，在解析 action / master_state 前校验 Arrow 是否包含所需执行器列。
        strict_extra_arrow_columns: 为 True 时，除上述列外不允许多余列（需 validate_control_arrow=True）。

    Returns:
        0 表示正常退出。
    """
    order = actuator_order
    if order is None:
        if isinstance(driver, BaseRobotDriver):
            order = driver.actuator_order
        else:
            raise ValueError(
                "actuator_order 必须传入，或 driver 需为 BaseRobotDriver 并实现 actuator_order"
            )
    if not order:
        raise ValueError("actuator_order 不能为空")

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
                            actuator_order=order,
                            debug=debug,
                            on_tick_after_state=on_tick_after_state,
                        )
                        continue
                    _handle_control_input(
                        input_id=input_id,
                        value=value,
                        driver=driver,
                        actuator_order=order,
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
