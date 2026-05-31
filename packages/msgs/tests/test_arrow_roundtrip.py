from __future__ import annotations

import io
import math

import numpy as np
import pyarrow as pa
import pytest
from PIL import Image as PILImage

from forge_msgs.arrow import ensure_record_batch
from forge_msgs.control import PolicyCommand, PolicyCommandStatus
from forge_msgs.image import CompressedImage, Image
from forge_msgs.joint import JointCommand, JointState
from forge_msgs.locomotion import LocomotionCommand
from forge_msgs.pose import Pose, PoseSet


def _to_ipc_bytes(batch: pa.RecordBatch) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    return sink.getvalue().to_pybytes()


def test_ensure_record_batch_record_batch() -> None:
    batch = pa.RecordBatch.from_pydict({"x": [1, 2], "y": [3.0, 4.0]})
    assert ensure_record_batch(batch) is batch


def test_ensure_record_batch_table() -> None:
    batch = pa.RecordBatch.from_pydict({"x": [1, 2]})
    out = ensure_record_batch(pa.Table.from_batches([batch]))
    assert isinstance(out, pa.RecordBatch)
    assert out.num_rows == 2
    assert out["x"][0].as_py() == 1


def test_ensure_record_batch_ipc_bytes() -> None:
    batch = pa.RecordBatch.from_pydict({"x": [1]})
    out = ensure_record_batch(_to_ipc_bytes(batch))
    assert out["x"][0].as_py() == 1


def test_ensure_record_batch_struct_array() -> None:
    batch = pa.RecordBatch.from_pydict({"x": [1], "y": [2]})
    struct = pa.StructArray.from_arrays(
        [batch.column(i) for i in range(batch.num_columns)],
        names=list(batch.schema.names),
    )
    out = ensure_record_batch(struct)
    assert out["x"][0].as_py() == 1
    assert out["y"][0].as_py() == 2


def test_ensure_record_batch_invalid_type() -> None:
    with pytest.raises(TypeError, match="from_arrow expects"):
        ensure_record_batch([1, 2, 3])  # type: ignore[arg-type]


def test_joint_state_roundtrip_record_batch_table_and_bytes() -> None:
    state = JointState(
        name=["j1", "j2"],
        position=[1.0, 2.0],
        velocity=[0.1, 0.2],
        effort=[],
    )
    batch = state.to_arrow()

    back = JointState.from_arrow(batch)
    assert back == state

    from_table = JointState.from_arrow(pa.Table.from_batches([batch]))
    assert from_table == state

    from_bytes = JointState.from_arrow(_to_ipc_bytes(batch))
    assert from_bytes == state


def test_joint_state_validation() -> None:
    with pytest.raises(ValueError, match="name must contain"):
        JointState(name=[], position=[])

    with pytest.raises(ValueError, match="unique"):
        JointState(name=["j1", "j1"], position=[1.0, 2.0])

    with pytest.raises(ValueError, match="same length"):
        JointState(name=["j1", "j2"], position=[1.0])


def test_joint_state_np_helpers() -> None:
    state = JointState(name=["j2", "j1"], position=[2.0, 1.0])
    arr = state.to_np(["j1", "j2", "missing"])
    np.testing.assert_array_equal(arr, np.array([1.0, 2.0, 0.0], dtype=np.float64))

    from_np = JointState.from_np(np.array([3.0, 4.0]), ["j1", "j2"])
    assert from_np.name == ["j1", "j2"]
    assert from_np.position == [3.0, 4.0]
    assert from_np.velocity == []


def test_joint_command_roundtrip_and_unitree_fields() -> None:
    command = JointCommand(
        name=["j1", "j2"],
        mode="hybrid",
        position=[1.0, 2.0],
        velocity=[0.0, 0.0],
        effort=[0.5, 0.6],
        kp=[20.0, 30.0],
        kd=[1.0, 1.2],
    )
    batch = command.to_arrow()
    assert batch["mode"][0].as_py() == "hybrid"
    back = JointCommand.from_arrow(_to_ipc_bytes(batch))
    assert back == command
    np.testing.assert_array_equal(back.to_np(["j2", "j1"], "kp"), np.array([30.0, 20.0]))


def test_joint_command_reads_legacy_arrow_without_mode() -> None:
    batch = pa.RecordBatch.from_pydict(
        {
            "name": pa.array([["j1"]], type=pa.list_(pa.string())),
            "position": pa.array([[1.0]], type=pa.list_(pa.float64())),
            "velocity": pa.array([[]], type=pa.list_(pa.float64())),
            "effort": pa.array([[]], type=pa.list_(pa.float64())),
            "kp": pa.array([[]], type=pa.list_(pa.float64())),
            "kd": pa.array([[]], type=pa.list_(pa.float64())),
        }
    )

    command = JointCommand.from_arrow(batch)

    assert command.mode == "position"
    assert command.position == [1.0]


def test_joint_command_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError):
        JointCommand(name=["j1"], mode="invalid")  # type: ignore[arg-type]


def test_joint_command_from_np() -> None:
    command = JointCommand.from_np(
        np.array([1.0, 2.0]),
        ["j1", "j2"],
        field="effort",
    )
    assert command.name == ["j1", "j2"]
    assert command.effort == [1.0, 2.0]
    assert command.position == []


def test_image_rgb_roundtrip() -> None:
    frame = np.array(
        [
            [[255, 0, 0], [0, 255, 0]],
            [[0, 0, 255], [255, 255, 255]],
        ],
        dtype=np.uint8,
    )
    image = Image.from_numpy(frame, encoding="rgb8")
    assert image.step == 6

    back = Image.from_arrow(_to_ipc_bytes(image.to_arrow()))
    assert back.height == 2
    assert back.width == 2
    assert back.encoding == "rgb8"
    np.testing.assert_array_equal(back.to_numpy(), frame)


def test_image_mono_and_depth_roundtrip() -> None:
    mono = np.array([[0, 1], [2, 3]], dtype=np.uint8)
    mono_image = Image.from_numpy(mono, encoding="mono8")
    np.testing.assert_array_equal(Image.from_arrow(mono_image.to_arrow()).to_numpy(), mono)

    depth = np.array([[100, 200], [300, 400]], dtype=np.uint16)
    depth_image = Image.from_numpy(depth, encoding="16UC1")
    assert depth_image.step == 4
    np.testing.assert_array_equal(Image.from_arrow(depth_image.to_arrow()).to_numpy(), depth)


def test_image_rejects_invalid_data_length() -> None:
    with pytest.raises(ValueError, match="data length"):
        Image(height=2, width=2, encoding="rgb8", step=6, data=b"too-short")


def test_image_with_row_padding() -> None:
    data = bytes([1, 2, 3, 4, 0, 0, 5, 6, 7, 8, 0, 0])
    image = Image(height=2, width=2, encoding="mono8", step=6, data=data)
    np.testing.assert_array_equal(
        image.to_numpy(),
        np.array([[1, 2], [5, 6]], dtype=np.uint8),
    )


def test_compressed_image_roundtrip_record_batch_and_bytes() -> None:
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    frame[0, 0] = [255, 0, 0]
    compressed = CompressedImage.from_numpy(frame, format="jpeg")
    assert compressed.format == "jpeg"
    assert compressed.data

    back = CompressedImage.from_arrow(compressed.to_arrow())
    assert back.format == "jpeg"
    assert back.data == compressed.data

    from_bytes = CompressedImage.from_arrow(_to_ipc_bytes(compressed.to_arrow()))
    arr = from_bytes.to_numpy()
    assert arr.dtype == np.uint8
    assert arr.shape == frame.shape


def test_compressed_image_decodes_png() -> None:
    frame = np.ones((2, 3, 3), dtype=np.uint8) * 128
    pil = PILImage.fromarray(frame)
    buffer = io.BytesIO()
    pil.save(buffer, format="PNG")

    compressed = CompressedImage(format="png", data=buffer.getvalue())
    arr = compressed.to_numpy()
    assert arr.shape == frame.shape
    np.testing.assert_array_equal(arr, 128)


def test_policy_command_roundtrip_record_batch_table_and_bytes() -> None:
    command = PolicyCommand.from_inputs(
        policy_id="default",
        command="start_recording",
        request_id="rec-001",
        inputs={"output_path": "runs/demo.mcap"},
    )
    assert command.inputs() == {"output_path": "runs/demo.mcap"}

    batch = command.to_arrow()
    assert PolicyCommand.from_arrow(batch) == command
    assert PolicyCommand.from_arrow(pa.Table.from_batches([batch])) == command
    assert PolicyCommand.from_arrow(_to_ipc_bytes(batch)) == command


def test_policy_command_validation() -> None:
    with pytest.raises(ValueError, match="policy_id"):
        PolicyCommand(policy_id="", command="start")

    with pytest.raises(ValueError, match="snake_case"):
        PolicyCommand(policy_id="default", command="StartRecording")

    with pytest.raises(ValueError, match="JSON"):
        PolicyCommand(policy_id="default", command="start", inputs_json="not-json")

    with pytest.raises(ValueError, match="JSON object"):
        PolicyCommand(policy_id="default", command="start", inputs_json="[]")


def test_policy_command_status_roundtrip_and_outputs() -> None:
    status = PolicyCommandStatus.from_outputs(
        policy_id="default",
        command="start_recording",
        request_id="rec-001",
        status="done",
        message="recording started",
        outputs={"path": "runs/demo.mcap"},
    )
    assert status.outputs() == {"path": "runs/demo.mcap"}

    batch = status.to_arrow()
    assert PolicyCommandStatus.from_arrow(batch) == status
    assert PolicyCommandStatus.from_arrow(_to_ipc_bytes(batch)) == status


def test_policy_command_status_validation() -> None:
    with pytest.raises(ValueError, match="Input should be"):
        PolicyCommandStatus(
            policy_id="default",
            command="start",
            status="unknown",  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="JSON object"):
        PolicyCommandStatus(
            policy_id="default",
            command="start",
            status="error",
            outputs_json="[]",
        )


def test_locomotion_command_roundtrip_record_batch_table_and_bytes() -> None:
    command = LocomotionCommand(vx=0.5, vy=0.1, wz=0.2)
    batch = command.to_arrow()

    assert LocomotionCommand.from_arrow(batch) == command
    assert LocomotionCommand.from_arrow(pa.Table.from_batches([batch])) == command
    assert LocomotionCommand.from_arrow(_to_ipc_bytes(batch)) == command


@pytest.mark.parametrize("field", ["vx", "vy", "wz"])
def test_locomotion_command_rejects_non_finite(field: str) -> None:
    payload = {"vx": 0.0, "vy": 0.0, "wz": 0.0}
    payload[field] = math.inf

    with pytest.raises(ValueError, match="finite"):
        LocomotionCommand(**payload)


def test_pose_roundtrip_record_batch_table_and_bytes() -> None:
    pose = Pose(x=1.0, y=2.0, z=3.0, qx=0.0, qy=0.0, qz=0.0, qw=1.0)
    batch = pose.to_arrow()
    assert Pose.from_arrow(batch) == pose
    assert Pose.from_arrow(pa.Table.from_batches([batch])) == pose
    assert Pose.from_arrow(_to_ipc_bytes(batch)) == pose


def test_pose_xy_yaw_helpers() -> None:
    pose = Pose.from_xy_yaw(1.0, 2.0, np.pi / 2.0)
    x, y, yaw = pose.to_xy_yaw()
    assert x == pytest.approx(1.0)
    assert y == pytest.approx(2.0)
    assert yaw == pytest.approx(np.pi / 2.0)


def test_pose_rejects_zero_quaternion() -> None:
    with pytest.raises(ValueError, match="quaternion"):
        Pose(x=0.0, y=0.0, qx=0.0, qy=0.0, qz=0.0, qw=0.0)


def test_pose_set_roundtrip_and_helpers() -> None:
    poses = {
        "b": Pose.from_xy_yaw(2.0, 3.0, 0.5),
        "a": Pose(x=1.0, y=2.0),
    }
    pose_set = PoseSet.from_poses(poses)
    assert pose_set.name == ["a", "b"]

    back = PoseSet.from_arrow(_to_ipc_bytes(pose_set.to_arrow()))
    assert back == pose_set
    assert back.to_poses()["a"] == poses["a"]


def test_pose_set_validation() -> None:
    with pytest.raises(ValueError, match="name"):
        PoseSet(name=[], x=[], y=[], z=[], qx=[], qy=[], qz=[], qw=[])

    with pytest.raises(ValueError, match="unique"):
        PoseSet(
            name=["a", "a"],
            x=[0.0, 1.0],
            y=[0.0, 1.0],
            z=[0.0, 0.0],
            qx=[0.0, 0.0],
            qy=[0.0, 0.0],
            qz=[0.0, 0.0],
            qw=[1.0, 1.0],
        )

    with pytest.raises(ValueError, match="same length"):
        PoseSet(
            name=["a", "b"],
            x=[0.0],
            y=[0.0, 1.0],
            z=[0.0, 0.0],
            qx=[0.0, 0.0],
            qy=[0.0, 0.0],
            qz=[0.0, 0.0],
            qw=[1.0, 1.0],
        )
