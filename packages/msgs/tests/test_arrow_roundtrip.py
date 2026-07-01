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
from forge_msgs.manipulation import (
    ManipulationPlan,
    ManipulationPlannerConfig,
    ManipulationPlanStep,
    ManipulationTargetResult,
)
from forge_msgs.perception import (
    Detection2DSet,
    Detection3DSet,
    SegmentationMaskSet,
)
from forge_msgs.point_cloud import PointCloud
from forge_msgs.pose import Pose, PoseSet
from forge_msgs.teleop import TeleopObservation


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

    labels = np.array([[1, 2], [3, 4]], dtype=np.int32)
    label_image = Image.from_numpy(labels, encoding="32SC1")
    np.testing.assert_array_equal(Image.from_arrow(label_image.to_arrow()).to_numpy(), labels)


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


def test_manipulation_target_result_roundtrip_and_validation() -> None:
    result = ManipulationTargetResult(
        request_id="wf-001:perceive",
        success=True,
        target_name="apple",
        prompt="red apple",
        target_point_cam=[0.12, -0.05, 0.68],
        target_contact_radius_m=0.042,
        bbox_xyxy=[100.0, 80.0, 260.0, 300.0],
        score=0.91,
        yaw_hint_cam_rad=None,
    )
    assert ManipulationTargetResult.from_arrow(result.to_arrow()) == result
    assert ManipulationTargetResult.from_arrow(pa.Table.from_batches([result.to_arrow()])) == result
    assert ManipulationTargetResult.from_arrow(_to_ipc_bytes(result.to_arrow())) == result

    with pytest.raises(ValueError, match="target_point_cam"):
        ManipulationTargetResult(success=True, target_point_cam=[0.1, 0.2])
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        ManipulationTargetResult(success=True, score=1.5)


def test_manipulation_plan_step_roundtrip_and_validation() -> None:
    step = ManipulationPlanStep(
        kind="pose",
        name="pre_grasp",
        duration_s=2.5,
        payload={"x": 0.4, "y": 0.1, "z": 0.25, "yaw": 0.5},
    )
    assert ManipulationPlanStep.from_arrow(step.to_arrow()) == step
    assert ManipulationPlanStep.from_arrow(_to_ipc_bytes(step.to_arrow())) == step

    with pytest.raises(ValueError, match="duration_s"):
        ManipulationPlanStep(kind="wait", duration_s=-1.0)
    with pytest.raises(ValueError, match="JSON serializable"):
        ManipulationPlanStep(kind="call", payload={"bad": object()})


def test_manipulation_plan_roundtrip_and_validation() -> None:
    plan = ManipulationPlan(
        request_id="wf-001:plan",
        success=True,
        target_name="apple",
        operation="pick",
        target_position_base=[0.4, 0.1, 0.25],
        yaw_base_rad=0.5,
        target_distance_m=0.42,
        steps=[
            ManipulationPlanStep(
                kind="pose",
                name="pre_grasp",
                duration_s=2.5,
                payload={"x": 0.4, "y": 0.1, "z": 0.25},
            ),
            ManipulationPlanStep(kind="gripper", name="close", payload={"position_mm": 0.0}),
        ],
    )
    assert ManipulationPlan.from_arrow(plan.to_arrow()) == plan
    assert ManipulationPlan.from_arrow(pa.Table.from_batches([plan.to_arrow()])) == plan
    assert ManipulationPlan.from_arrow(_to_ipc_bytes(plan.to_arrow())) == plan
    assert plan.model_dump()["steps"][0]["payload"]["x"] == 0.4

    with pytest.raises(ValueError, match="target_position_base"):
        ManipulationPlan(success=True, target_position_base=[0.1, 0.2])
    with pytest.raises(ValueError, match="target_distance_m"):
        ManipulationPlan(success=True, target_distance_m=-0.1)


def test_manipulation_planner_config_roundtrip_and_validation() -> None:
    config = ManipulationPlannerConfig(
        tcp_tool_len_m=0.075,
        gripper_open_mm=85.0,
        auto_home=False,
        place_pitch_rad=2.35619,
    )
    assert ManipulationPlannerConfig.from_arrow(config.to_arrow()) == config
    assert ManipulationPlannerConfig.from_arrow(_to_ipc_bytes(config.to_arrow())) == config

    with pytest.raises(ValueError, match="tcp_tool_len_m"):
        ManipulationPlannerConfig(tcp_tool_len_m=-0.1)


def test_teleop_observation_roundtrip_record_batch_table_and_bytes() -> None:
    observation = TeleopObservation.from_device_poses(
        {
            "headset": (0.0, 1.6, 0.0, 0.0, 0.0, 0.0, 1.0),
            "left": (0.2, 1.2, 0.1, 0.0, 0.0, 0.0, 1.0),
            "right": (-0.2, 1.2, 0.1, 0.0, 0.0, 0.0, 1.0),
        },
        confidence={"headset": 0.95, "left": 0.8, "right": 0.85},
        buttons={"left_X": True, "right_A": False},
        axes={"left_trigger": 0.3, "right_axis": [0.1, -0.2]},
    )
    batch = observation.to_arrow()
    assert TeleopObservation.from_arrow(batch) == observation
    assert TeleopObservation.from_arrow(pa.Table.from_batches([batch])) == observation
    assert TeleopObservation.from_arrow(_to_ipc_bytes(batch)) == observation
    assert observation.buttons() == {"left_X": True, "right_A": False}
    assert observation.axes()["left_trigger"] == 0.3


def test_teleop_observation_validation() -> None:
    with pytest.raises(ValueError, match="device"):
        TeleopObservation(
            device=[],
            x=[],
            y=[],
            z=[],
            qx=[],
            qy=[],
            qz=[],
            qw=[],
            confidence=[],
        )

    with pytest.raises(ValueError, match="JSON"):
        TeleopObservation(
            device=["left"],
            x=[0.0],
            y=[0.0],
            z=[0.0],
            qx=[0.0],
            qy=[0.0],
            qz=[0.0],
            qw=[1.0],
            confidence=[1.0],
            buttons_json="not-json",
        )


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


def test_detection_2d_roundtrip_and_empty_result() -> None:
    detections = Detection2DSet(
        detection_id=["d0", "d1"],
        track_id=["track-7", ""],
        center_x=[10.5, 20.0],
        center_y=[11.0, 21.0],
        size_x=[4.0, 8.0],
        size_y=[5.0, 9.0],
        rotation=[0.0, 0.25],
        hypothesis_offset=[0, 2, 3],
        class_id=["person", "worker", "cup"],
        score=[0.9, 0.1, 0.8],
    )
    back = Detection2DSet.from_arrow(_to_ipc_bytes(detections.to_arrow()))
    assert back.detection_id == detections.detection_id
    assert back.track_id == detections.track_id
    assert back.hypothesis_offset == detections.hypothesis_offset
    assert back.class_id == detections.class_id
    assert back.center_x == pytest.approx(detections.center_x)
    assert back.center_y == pytest.approx(detections.center_y)
    assert back.size_x == pytest.approx(detections.size_x)
    assert back.size_y == pytest.approx(detections.size_y)
    assert back.rotation == pytest.approx(detections.rotation)
    assert back.score == pytest.approx(detections.score)
    assert Detection2DSet.from_arrow(Detection2DSet().to_arrow()) == Detection2DSet()

    axis_aligned = Detection2DSet(
        detection_id=["d0"],
        track_id=[""],
        center_x=[10.5],
        center_y=[11.0],
        size_x=[4.0],
        size_y=[5.0],
        hypothesis_offset=[0, 1],
        class_id=["person"],
        score=[0.9],
    )
    assert axis_aligned.rotation == [0.0]


def test_detection_2d_rejects_invalid_hypothesis_offsets() -> None:
    with pytest.raises(ValueError, match="end at"):
        Detection2DSet(
            detection_id=["d0"],
            track_id=[""],
            center_x=[0.0],
            center_y=[0.0],
            size_x=[1.0],
            size_y=[1.0],
            rotation=[0.0],
            hypothesis_offset=[0, 0],
            class_id=["person"],
            score=[0.9],
        )


def test_detection_3d_roundtrip_and_quaternion_validation() -> None:
    detection = Detection3DSet(
        detection_id=["d0"],
        track_id=[""],
        center_x=[1.0],
        center_y=[2.0],
        center_z=[3.0],
        qx=[0.0],
        qy=[0.0],
        qz=[0.0],
        qw=[1.0],
        size_x=[0.5],
        size_y=[0.6],
        size_z=[0.7],
        hypothesis_offset=[0, 1],
        class_id=["box"],
        score=[0.95],
    )
    back = Detection3DSet.from_arrow(_to_ipc_bytes(detection.to_arrow()))
    assert back.detection_id == detection.detection_id
    assert back.class_id == detection.class_id
    assert back.hypothesis_offset == detection.hypothesis_offset
    for field in (
        "center_x",
        "center_y",
        "center_z",
        "qx",
        "qy",
        "qz",
        "qw",
        "size_x",
        "size_y",
        "size_z",
        "score",
    ):
        assert getattr(back, field) == pytest.approx(getattr(detection, field))

    axis_aligned = Detection3DSet(
        detection_id=["d0"],
        track_id=[""],
        center_x=[1.0],
        center_y=[2.0],
        center_z=[3.0],
        size_x=[0.5],
        size_y=[0.6],
        size_z=[0.7],
        hypothesis_offset=[0, 1],
        class_id=["box"],
        score=[0.95],
    )
    assert axis_aligned.qx == [0.0]
    assert axis_aligned.qy == [0.0]
    assert axis_aligned.qz == [0.0]
    assert axis_aligned.qw == [1.0]

    with pytest.raises(ValueError, match="quaternion"):
        Detection3DSet(**(detection.model_dump() | {"qw": [0.0]}))


def test_segmentation_mask_roundtrip_and_length_validation() -> None:
    masks = SegmentationMaskSet(
        mask_id=["m0"],
        detection_id=["d0"],
        track_id=[""],
        x_offset=[4],
        y_offset=[5],
        width=[2],
        height=[2],
        data=[bytes([0, 255, 255, 0])],
    )
    assert SegmentationMaskSet.from_arrow(_to_ipc_bytes(masks.to_arrow())) == masks

    standalone = SegmentationMaskSet(
        mask_id=["m0"],
        width=[2],
        height=[2],
        data=[bytes([0, 255, 255, 0])],
    )
    assert standalone.detection_id == [""]
    assert standalone.track_id == [""]
    assert standalone.x_offset == [0]
    assert standalone.y_offset == [0]

    with pytest.raises(ValueError, match=r"data\[0\] length"):
        SegmentationMaskSet(
            mask_id=["m0"],
            detection_id=[""],
            track_id=[""],
            x_offset=[0],
            y_offset=[0],
            width=[2],
            height=[2],
            data=[b"\x00"],
        )


def test_point_cloud_roundtrip_and_dense_validation() -> None:
    cloud = PointCloud(
        width=2,
        height=1,
        is_dense=True,
        x=[1.0, 2.0],
        y=[3.0, 4.0],
        z=[5.0, 6.0],
        red=[255, 0],
        green=[0, 255],
        blue=[0, 0],
    )
    assert PointCloud.from_arrow(_to_ipc_bytes(cloud.to_arrow())) == cloud

    unorganized = PointCloud(x=[1.0, 2.0], y=[3.0, 4.0], z=[5.0, 6.0])
    assert unorganized.width == 2
    assert unorganized.height == 1
    assert unorganized.is_dense is True

    sparse = PointCloud(x=[math.nan], y=[0.0], z=[0.0])
    assert sparse.width == 1
    assert sparse.height == 1
    assert sparse.is_dense is False

    with pytest.raises(ValueError, match="width \\* height"):
        PointCloud(**(cloud.model_dump() | {"width": 3}))
    with pytest.raises(ValueError, match="finite"):
        PointCloud(
            width=1,
            height=1,
            is_dense=True,
            x=[math.nan],
            y=[0.0],
            z=[0.0],
        )
    with pytest.raises(ValueError, match="all be empty or all be populated"):
        PointCloud(
            width=1,
            height=1,
            is_dense=True,
            x=[0.0],
            y=[0.0],
            z=[0.0],
            red=[255],
        )
