"""forge_msgs 与 Arrow 互转的往返测试及 dora 场景（bytes/Table/空 batch）。"""

from __future__ import annotations

import io

import numpy as np
import pyarrow as pa
import pytest
from PIL import Image as PILImage

from forge_msgs.robot import RobotAction, RobotState
from forge_msgs.task_robot import Action, ProprioState
from forge_msgs.image import Image
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


def test_ensure_record_batch_struct_array() -> None:
    """dora 有时传 StructArray（RecordBatch 被当作单列 struct）。"""
    batch = pa.RecordBatch.from_pydict(
        {
            "mode": pa.array([[0, 0, 0]], type=pa.list_(pa.int8())),
            "unit": pa.array([[0, 0, 0]], type=pa.list_(pa.int8())),
            "j1": pa.array([1.0], type=pa.float32()),
            "j2": pa.array([2.0], type=pa.float32()),
        }
    )
    # 单行 RecordBatch 转成 StructArray：每列变成 struct 的一个字段
    struct_array = pa.StructArray.from_arrays(
        [batch.column(i) for i in range(batch.num_columns)],
        names=list(batch.schema.names),
    )
    out = ensure_record_batch(struct_array)
    assert isinstance(out, pa.RecordBatch)
    assert out.num_rows == 1
    assert out.column("j1")[0].as_py() == 1.0
    assert out.column("j2")[0].as_py() == 2.0


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
    # 每个 actuator 各自保留 mode/unit
    assert back.actuators["a1"].mode == "position"
    assert back.actuators["a1"].unit == "radians"
    assert back.actuators["a2"].mode == "velocity"
    assert back.actuators["a2"].unit == "radians/s"


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
    batch = pa.RecordBatch.from_pydict(
        {
            "mode": pa.array([], type=pa.list_(pa.int8())),
            "unit": pa.array([], type=pa.list_(pa.int8())),
            "a1": pa.array([], type=pa.float32()),
            "a2": pa.array([], type=pa.float32()),
        }
    )
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
    batch = pa.RecordBatch.from_pydict(
        {
            "mode": pa.array([[0, 0]], type=pa.list_(pa.int8())),
            "unit": pa.array([[0, 0]], type=pa.list_(pa.int8())),
            "a1": pa.array([10.0], type=pa.float32()),
            # 无 "a2"
        }
    )
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

    empty = pa.RecordBatch.from_pydict(
        {
            "mode": pa.array([], type=pa.list_(pa.int8())),
            "unit": pa.array([], type=pa.list_(pa.int8())),
            "a1": pa.array([], type=pa.float32()),
            "a2": pa.array([], type=pa.float32()),
        }
    )
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
    batch = pa.RecordBatch.from_pydict(
        {
            "mode": pa.array([], type=pa.list_(pa.int8())),
            "unit": pa.array([], type=pa.list_(pa.int8())),
            **{name: pa.array([], type=pa.float32()) for name in JOINT_ORDER},
        }
    )
    back = ProprioState.from_arrow(batch, JOINT_ORDER)
    for name in JOINT_ORDER:
        assert back.joints[name].value == 0.0
        assert back.joints[name].mode == "position"


# ---------- Image ----------
def test_image_to_arrow_from_arrow_record_batch_and_bytes() -> None:
    img = Image(
        width=2,
        height=1,
        channels=3,
        encoding="rgb8",
        data=bytes([255, 0, 0, 0, 255, 0]),
    )
    batch = img.to_arrow()
    back = Image.from_arrow(batch)
    assert back.width == 2
    assert back.height == 1
    assert back.channels == 3
    assert back.encoding == "rgb8"
    assert back.data == img.data

    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    data = sink.getvalue().to_pybytes()
    back2 = Image.from_arrow(data)
    assert back2.data == img.data


def test_compressed_image_to_arrow_from_arrow_record_batch_and_bytes() -> None:
    img = Image(
        width=640,
        height=480,
        channels=0,
        encoding="jpeg",
        data=bytes([0xFF, 0xD8, 0xFF, 0xD9]),  # minimal jpeg-like bytes for roundtrip
    )
    batch = img.to_arrow()
    back = Image.from_arrow(batch)
    assert back.width == 640
    assert back.height == 480
    assert back.channels == 0
    assert back.encoding == "jpeg"
    assert back.data == img.data

    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    data = sink.getvalue().to_pybytes()
    back2 = Image.from_arrow(data)
    assert back2.data == img.data


def test_image_to_numpy_decodes_jpeg() -> None:
    """to_numpy() 对 encoding=jpeg 能解码为 HWC uint8。"""
    # 用 Pillow 生成一小块真实 JPEG
    rgb = np.zeros((4, 6, 3), dtype=np.uint8)
    rgb[0, 0] = [255, 0, 0]
    rgb[2, 3] = [0, 255, 0]
    pil = PILImage.fromarray(rgb)
    buf = io.BytesIO()
    pil.save(buf, format="JPEG")
    jpeg_bytes = buf.getvalue()

    img = Image(
        width=6,
        height=4,
        channels=0,
        encoding="jpeg",
        data=jpeg_bytes,
    )
    arr = img.to_numpy()
    assert arr.dtype == np.uint8
    assert arr.ndim == 3
    assert arr.shape[0] == 4 and arr.shape[1] == 6 and arr.shape[2] == 3
    # 解码后大致为 RGB（JPEG 有损，只做形状与类型检查）
    assert arr.min() >= 0 and arr.max() <= 255


def test_image_to_numpy_decodes_png() -> None:
    """to_numpy() 对 encoding=png 能解码为 HWC uint8。"""
    rgb = np.ones((2, 3, 3), dtype=np.uint8) * 128
    pil = PILImage.fromarray(rgb)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    img = Image(
        width=3,
        height=2,
        channels=0,
        encoding="png",
        data=png_bytes,
    )
    arr = img.to_numpy()
    assert arr.dtype == np.uint8
    assert arr.shape == (2, 3, 3)
    np.testing.assert_array_equal(arr, 128)


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
    batch = pa.RecordBatch.from_pydict(
        {
            "mode": pa.array([], type=pa.list_(pa.int8())),
            "unit": pa.array([], type=pa.list_(pa.int8())),
            **{name: pa.array([], type=pa.float32()) for name in JOINT_ORDER},
        }
    )
    back = Action.from_arrow(batch, JOINT_ORDER)
    for name in JOINT_ORDER:
        assert back.joints[name].value == 0.0


def test_action_from_arrow_struct_array() -> None:
    """模拟 dora 传入 StructArray 的场景（task_robot / mujoco 节点）。"""
    action = _action()
    batch = action.to_arrow(JOINT_ORDER)
    struct_array = pa.StructArray.from_arrays(
        [batch.column(i) for i in range(batch.num_columns)],
        names=list(batch.schema.names),
    )
    back = Action.from_arrow(struct_array, JOINT_ORDER)
    assert back.joints["j1"].value == 1.0
    assert back.joints["j2"].value == 2.0
    assert back.joints["j3"].value == 3.0
