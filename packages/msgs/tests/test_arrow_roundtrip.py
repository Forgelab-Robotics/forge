"""forge_msgs 与 Arrow 互转的往返测试及 dora 场景（bytes/Table/空 batch）。"""

from __future__ import annotations

import numpy as np
import pyarrow as pa
import pytest

from forge_msgs.robot import RobotAction, RobotState
from forge_msgs.task_robot import Action, ProprioState
from forge_msgs.value import ActuatorValue, JointValue, ensure_record_batch


# ---------- 公共顺序 ----------
JOINT_ORDER = ["j1", "j2", "j3"]
ACTUATOR_ORDER = ["a1", "a2"]


# ---------- ensure_record_batch ----------
def test_ensure_record_batch_record_batch() -> None:
    batch = pa.RecordBatch.from_pydict({"x": [1, 2], "y": [3.0, 4.0]})
    out = ensure_record_batch(batch)
    assert out is batch
    assert out.num_rows == 2


def test_ensure_record_batch_table() -> None:
    batch = pa.RecordBatch.from_pydict({"x": [1, 2]})
    table = pa.Table.from_batches([batch])
    out = ensure_record_batch(table)
    assert isinstance(out, pa.RecordBatch)
    assert out.num_rows == 2
    assert out.column("x")[0].as_py() == 1


def test_ensure_record_batch_bytes_ipc() -> None:
    batch = pa.RecordBatch.from_pydict({"mode": [0], "unit": [0], "j1": [1.0]})
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    data = sink.getvalue().to_pybytes()
    out = ensure_record_batch(data)
    assert isinstance(out, pa.RecordBatch)
    assert out.num_rows == 1
    assert out.column("j1")[0].as_py() == 1.0


def test_ensure_record_batch_invalid_type() -> None:
    with pytest.raises(TypeError, match="from_arrow 需要"):
        ensure_record_batch([1, 2, 3])  # type: ignore[arg-type]


# ---------- RobotState ----------
def _robot_state() -> RobotState:
    return RobotState(
        actuators={
            "a1": ActuatorValue(value=1.0, mode="position", unit="radians"),
            "a2": ActuatorValue(value=2.0, mode="velocity", unit="radians/s"),
        }
    )


def test_robot_state_to_arrow_from_arrow_record_batch() -> None:
    state = _robot_state()
    batch = state.to_arrow(ACTUATOR_ORDER)
    assert isinstance(batch, pa.RecordBatch)
    back = RobotState.from_arrow(batch, ACTUATOR_ORDER)
    assert back.actuators["a1"].value == 1.0
    assert back.actuators["a2"].value == 2.0
    # to_arrow 只存一个 mode/unit（取第一个 actuator），故反序列化后均为同一 mode
    assert back.actuators["a1"].mode == "position"
    assert back.actuators["a2"].mode == "position"


def test_robot_state_to_arrow_from_arrow_bytes() -> None:
    """模拟 dora 收到 IPC 序列化后的 bytes。"""
    state = _robot_state()
    batch = state.to_arrow(ACTUATOR_ORDER)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    data = sink.getvalue().to_pybytes()
    back = RobotState.from_arrow(data, ACTUATOR_ORDER)
    assert back.actuators["a1"].value == 1.0
    assert back.actuators["a2"].value == 2.0


def test_robot_state_to_arrow_from_arrow_table() -> None:
    state = _robot_state()
    batch = state.to_arrow(ACTUATOR_ORDER)
    table = pa.Table.from_batches([batch])
    back = RobotState.from_arrow(table, ACTUATOR_ORDER)
    assert back.actuators["a1"].value == 1.0
    assert back.actuators["a2"].value == 2.0


def test_robot_state_from_arrow_empty_batch() -> None:
    batch = pa.RecordBatch.from_pydict({
        "mode": pa.array([], type=pa.int8()),
        "unit": pa.array([], type=pa.int8()),
        "a1": pa.array([], type=pa.float32()),
        "a2": pa.array([], type=pa.float32()),
    })
    back = RobotState.from_arrow(batch, ACTUATOR_ORDER)
    assert back.actuators["a1"].value == 0.0
    assert back.actuators["a2"].value == 0.0
    assert back.actuators["a1"].mode == "position"


def test_robot_state_to_np_from_arrow_record_batch() -> None:
    state = _robot_state()
    batch = state.to_arrow(ACTUATOR_ORDER)
    arr = RobotState.to_np_from_arrow(batch, ACTUATOR_ORDER)
    np.testing.assert_array_almost_equal(arr, np.array([1.0, 2.0], dtype=np.float32))


def test_robot_state_to_np_from_arrow_bytes() -> None:
    state = _robot_state()
    batch = state.to_arrow(ACTUATOR_ORDER)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    data = sink.getvalue().to_pybytes()
    arr = RobotState.to_np_from_arrow(data, ACTUATOR_ORDER)
    np.testing.assert_array_almost_equal(arr, np.array([1.0, 2.0], dtype=np.float32))


def test_robot_state_from_arrow_order_has_extra_column() -> None:
    """batch 中缺少某列时用 0.0 填充。"""
    batch = pa.RecordBatch.from_pydict({
        "mode": pa.array([0], type=pa.int8()),
        "unit": pa.array([0], type=pa.int8()),
        "a1": pa.array([10.0], type=pa.float32()),
        # 无 "a2"
    })
    back = RobotState.from_arrow(batch, ACTUATOR_ORDER)
    assert back.actuators["a1"].value == 10.0
    assert back.actuators["a2"].value == 0.0


# ---------- RobotAction ----------
def _robot_action() -> RobotAction:
    return RobotAction(
        actuators={
            "a1": ActuatorValue(value=-1.0, mode="torque", unit="Nm"),
            "a2": ActuatorValue(value=-2.0, mode="position", unit="radians"),
        }
    )


def test_robot_action_to_arrow_from_arrow_record_batch() -> None:
    action = _robot_action()
    batch = action.to_arrow(ACTUATOR_ORDER)
    back = RobotAction.from_arrow(batch, ACTUATOR_ORDER)
    assert back.actuators["a1"].value == -1.0
    assert back.actuators["a2"].value == -2.0
    assert back.actuators["a1"].unit == "Nm"


def test_robot_action_from_arrow_bytes_and_empty_batch() -> None:
    action = _robot_action()
    batch = action.to_arrow(ACTUATOR_ORDER)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    data = sink.getvalue().to_pybytes()
    back = RobotAction.from_arrow(data, ACTUATOR_ORDER)
    assert back.actuators["a1"].value == -1.0

    empty = pa.RecordBatch.from_pydict({
        "mode": pa.array([], type=pa.int8()),
        "unit": pa.array([], type=pa.int8()),
        "a1": pa.array([], type=pa.float32()),
        "a2": pa.array([], type=pa.float32()),
    })
    back_empty = RobotAction.from_arrow(empty, ACTUATOR_ORDER)
    assert back_empty.actuators["a1"].value == 0.0


# ---------- ProprioState ----------
def _proprio_state() -> ProprioState:
    return ProprioState(
        joints={
            "j1": JointValue(value=0.1, mode="position", unit="radians"),
            "j2": JointValue(value=0.2, mode="position", unit="radians"),
            "j3": JointValue(value=0.3, mode="position", unit="radians"),
        }
    )


def test_proprio_state_to_arrow_from_arrow_record_batch() -> None:
    state = _proprio_state()
    batch = state.to_arrow(JOINT_ORDER)
    back = ProprioState.from_arrow(batch, JOINT_ORDER)
    assert back.joints["j1"].value == pytest.approx(0.1)
    assert back.joints["j2"].value == pytest.approx(0.2)
    assert back.joints["j3"].value == pytest.approx(0.3)


def test_proprio_state_to_arrow_from_arrow_bytes() -> None:
    state = _proprio_state()
    batch = state.to_arrow(JOINT_ORDER)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    data = sink.getvalue().to_pybytes()
    back = ProprioState.from_arrow(data, JOINT_ORDER)
    assert back.joints["j1"].value == pytest.approx(0.1)


def test_proprio_state_to_np_from_arrow() -> None:
    state = _proprio_state()
    batch = state.to_arrow(JOINT_ORDER)
    arr = ProprioState.to_np_from_arrow(batch, JOINT_ORDER)
    np.testing.assert_array_almost_equal(
        arr, np.array([0.1, 0.2, 0.3], dtype=np.float32)
    )


def test_proprio_state_from_arrow_empty_batch() -> None:
    batch = pa.RecordBatch.from_pydict({
        "mode": pa.array([], type=pa.int8()),
        "unit": pa.array([], type=pa.int8()),
        **{name: pa.array([], type=pa.float32()) for name in JOINT_ORDER},
    })
    back = ProprioState.from_arrow(batch, JOINT_ORDER)
    for name in JOINT_ORDER:
        assert back.joints[name].value == 0.0
        assert back.joints[name].mode == "position"


# ---------- Action (task_robot) ----------
def _action() -> Action:
    return Action(
        joints={
            "j1": JointValue(value=1.0, mode="velocity", unit="radians/s"),
            "j2": JointValue(value=2.0, mode="velocity", unit="radians/s"),
            "j3": JointValue(value=3.0, mode="velocity", unit="radians/s"),
        }
    )


def test_action_to_arrow_from_arrow_record_batch() -> None:
    action = _action()
    batch = action.to_arrow(JOINT_ORDER)
    back = Action.from_arrow(batch, JOINT_ORDER)
    assert back.joints["j1"].value == 1.0
    assert back.joints["j2"].value == 2.0
    assert back.joints["j3"].unit == "radians/s"


def test_action_from_arrow_bytes_and_table() -> None:
    action = _action()
    batch = action.to_arrow(JOINT_ORDER)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    data = sink.getvalue().to_pybytes()
    back = Action.from_arrow(data, JOINT_ORDER)
    assert back.joints["j1"].value == 1.0

    table = pa.Table.from_batches([batch])
    back2 = Action.from_arrow(table, JOINT_ORDER)
    assert back2.joints["j1"].value == 1.0


def test_action_from_arrow_empty_batch() -> None:
    batch = pa.RecordBatch.from_pydict({
        "mode": pa.array([], type=pa.int8()),
        "unit": pa.array([], type=pa.int8()),
        **{name: pa.array([], type=pa.float32()) for name in JOINT_ORDER},
    })
    back = Action.from_arrow(batch, JOINT_ORDER)
    for name in JOINT_ORDER:
        assert back.joints[name].value == 0.0
