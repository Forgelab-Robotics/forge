from __future__ import annotations

import json
import math
from typing import Any, Literal, Self

import pyarrow as pa
from pydantic import BaseModel, Field, model_validator

from forge_msgs.arrow import ensure_record_batch

StepKind = Literal["joint", "pose", "gripper", "wait", "call"]
ManipulationOperation = Literal["pick", "place"]


def _list_array(values: list, value_type: pa.DataType) -> pa.Array:
    return pa.array([values], type=pa.list_(value_type))


def _read_list(batch: pa.RecordBatch, name: str) -> list:
    return list(batch[name][0].as_py() or [])


def _read_optional_float(batch: pa.RecordBatch, name: str) -> float | None:
    value = batch[name][0].as_py()
    return None if value is None else float(value)


def _read_optional_str(batch: pa.RecordBatch, name: str) -> str | None:
    value = batch[name][0].as_py()
    return None if value is None else str(value)


def _validate_finite(name: str, value: float | None) -> None:
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def _validate_finite_list(name: str, values: list[float]) -> None:
    if any(not math.isfinite(value) for value in values):
        raise ValueError(f"{name} values must be finite")


def _validate_non_negative(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")


def _json_dumps_object(value: dict[str, Any], field_name: str) -> str:
    try:
        return json.dumps(value, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be JSON serializable") from exc


def _json_loads_object(value: str, field_name: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return parsed


class ManipulationTargetResult(BaseModel):
    """Target localization result consumed by manipulation planners."""

    request_id: str = ""
    success: bool
    target_name: str = ""
    prompt: str = ""
    frame_id: str = "camera"
    target_point_cam: list[float] = Field(default_factory=list)
    target_contact_radius_m: float | None = None
    bbox_xyxy: list[float] = Field(default_factory=list)
    score: float | None = None
    yaw_hint_cam_rad: float | None = None
    error: str | None = None
    schema_version: str = "manipulation_target_result.v1"

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.target_point_cam and len(self.target_point_cam) != 3:
            raise ValueError("target_point_cam must be empty or contain exactly 3 values")
        if self.bbox_xyxy and len(self.bbox_xyxy) != 4:
            raise ValueError("bbox_xyxy must be empty or contain exactly 4 values")
        _validate_finite_list("target_point_cam", self.target_point_cam)
        _validate_finite_list("bbox_xyxy", self.bbox_xyxy)
        _validate_finite("target_contact_radius_m", self.target_contact_radius_m)
        _validate_finite("score", self.score)
        _validate_finite("yaw_hint_cam_rad", self.yaw_hint_cam_rad)
        if self.target_contact_radius_m is not None and self.target_contact_radius_m < 0.0:
            raise ValueError("target_contact_radius_m must be non-negative")
        if self.score is not None and not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be in the range [0, 1]")
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "request_id": pa.array([self.request_id], type=pa.string()),
                "success": pa.array([self.success], type=pa.bool_()),
                "target_name": pa.array([self.target_name], type=pa.string()),
                "prompt": pa.array([self.prompt], type=pa.string()),
                "frame_id": pa.array([self.frame_id], type=pa.string()),
                "target_point_cam": _list_array(self.target_point_cam, pa.float64()),
                "target_contact_radius_m": pa.array([self.target_contact_radius_m], type=pa.float64()),
                "bbox_xyxy": _list_array(self.bbox_xyxy, pa.float64()),
                "score": pa.array([self.score], type=pa.float64()),
                "yaw_hint_cam_rad": pa.array([self.yaw_hint_cam_rad], type=pa.float64()),
                "error": pa.array([self.error], type=pa.string()),
                "schema_version": pa.array([self.schema_version], type=pa.string()),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "ManipulationTargetResult":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("ManipulationTargetResult RecordBatch must contain one row")
        return cls(
            request_id=str(batch["request_id"][0].as_py()),
            success=bool(batch["success"][0].as_py()),
            target_name=str(batch["target_name"][0].as_py()),
            prompt=str(batch["prompt"][0].as_py()),
            frame_id=str(batch["frame_id"][0].as_py()),
            target_point_cam=_read_list(batch, "target_point_cam"),
            target_contact_radius_m=_read_optional_float(batch, "target_contact_radius_m"),
            bbox_xyxy=_read_list(batch, "bbox_xyxy"),
            score=_read_optional_float(batch, "score"),
            yaw_hint_cam_rad=_read_optional_float(batch, "yaw_hint_cam_rad"),
            error=_read_optional_str(batch, "error"),
            schema_version=str(batch["schema_version"][0].as_py()),
        )


class ManipulationPlanStep(BaseModel):
    """One executable step inside a manipulation plan."""

    kind: StepKind
    payload: dict[str, Any] = Field(default_factory=dict)
    duration_s: float = 1.0
    name: str = ""
    require_duration: bool = False

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _json_dumps_object(self.payload, "payload")
        _validate_non_negative("duration_s", self.duration_s)
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "kind": pa.array([self.kind], type=pa.string()),
                "payload_json": pa.array([_json_dumps_object(self.payload, "payload")], type=pa.string()),
                "duration_s": pa.array([self.duration_s], type=pa.float64()),
                "name": pa.array([self.name], type=pa.string()),
                "require_duration": pa.array([self.require_duration], type=pa.bool_()),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "ManipulationPlanStep":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("ManipulationPlanStep RecordBatch must contain one row")
        return cls(
            kind=str(batch["kind"][0].as_py()),  # type: ignore[arg-type]
            payload=_json_loads_object(str(batch["payload_json"][0].as_py()), "payload_json"),
            duration_s=float(batch["duration_s"][0].as_py()),
            name=str(batch["name"][0].as_py()),
            require_duration=bool(batch["require_duration"][0].as_py()),
        )


class ManipulationPlan(BaseModel):
    """Pick or place plan produced by a manipulation planner."""

    request_id: str = ""
    success: bool
    target_name: str = ""
    steps: list[ManipulationPlanStep] = Field(default_factory=list)
    operation: ManipulationOperation = "pick"
    target_position_base: list[float] = Field(default_factory=list)
    yaw_base_rad: float | None = None
    target_distance_m: float | None = None
    planner_type: str = "heuristic_manipulation"
    error: str | None = None
    schema_version: str = "manipulation_plan.v1"

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.target_position_base and len(self.target_position_base) != 3:
            raise ValueError("target_position_base must be empty or contain exactly 3 values")
        _validate_finite_list("target_position_base", self.target_position_base)
        _validate_finite("yaw_base_rad", self.yaw_base_rad)
        _validate_finite("target_distance_m", self.target_distance_m)
        if self.target_distance_m is not None and self.target_distance_m < 0.0:
            raise ValueError("target_distance_m must be non-negative")
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "request_id": pa.array([self.request_id], type=pa.string()),
                "success": pa.array([self.success], type=pa.bool_()),
                "target_name": pa.array([self.target_name], type=pa.string()),
                "operation": pa.array([self.operation], type=pa.string()),
                "target_position_base": _list_array(self.target_position_base, pa.float64()),
                "yaw_base_rad": pa.array([self.yaw_base_rad], type=pa.float64()),
                "target_distance_m": pa.array([self.target_distance_m], type=pa.float64()),
                "planner_type": pa.array([self.planner_type], type=pa.string()),
                "error": pa.array([self.error], type=pa.string()),
                "schema_version": pa.array([self.schema_version], type=pa.string()),
                "step_kind": _list_array([step.kind for step in self.steps], pa.string()),
                "step_payload_json": _list_array(
                    [_json_dumps_object(step.payload, "step.payload") for step in self.steps],
                    pa.string(),
                ),
                "step_duration_s": _list_array([step.duration_s for step in self.steps], pa.float64()),
                "step_name": _list_array([step.name for step in self.steps], pa.string()),
                "step_require_duration": _list_array(
                    [step.require_duration for step in self.steps],
                    pa.bool_(),
                ),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "ManipulationPlan":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("ManipulationPlan RecordBatch must contain one row")
        step_kind = _read_list(batch, "step_kind")
        step_payload_json = _read_list(batch, "step_payload_json")
        step_duration_s = _read_list(batch, "step_duration_s")
        step_name = _read_list(batch, "step_name")
        step_require_duration = _read_list(batch, "step_require_duration")
        if len({len(step_kind), len(step_payload_json), len(step_duration_s), len(step_name), len(step_require_duration)}) != 1:
            raise ValueError("all step_* columns must have the same length")
        return cls(
            request_id=str(batch["request_id"][0].as_py()),
            success=bool(batch["success"][0].as_py()),
            target_name=str(batch["target_name"][0].as_py()),
            operation=str(batch["operation"][0].as_py()),  # type: ignore[arg-type]
            target_position_base=_read_list(batch, "target_position_base"),
            yaw_base_rad=_read_optional_float(batch, "yaw_base_rad"),
            target_distance_m=_read_optional_float(batch, "target_distance_m"),
            planner_type=str(batch["planner_type"][0].as_py()),
            error=_read_optional_str(batch, "error"),
            schema_version=str(batch["schema_version"][0].as_py()),
            steps=[
                ManipulationPlanStep(
                    kind=str(kind),  # type: ignore[arg-type]
                    payload=_json_loads_object(str(payload_json), "step_payload_json"),
                    duration_s=float(duration_s),
                    name=str(name),
                    require_duration=bool(require_duration),
                )
                for kind, payload_json, duration_s, name, require_duration in zip(
                    step_kind,
                    step_payload_json,
                    step_duration_s,
                    step_name,
                    step_require_duration,
                    strict=True,
                )
            ],
        )


class ManipulationPlannerConfig(BaseModel):
    """Planner tuning parameters for grasp and place manipulation."""

    approach_angle_rad: float = 0.785398
    tcp_tool_len_m: float = 0.075
    grasp_penetration_m: float = 0.035
    grasp_extra_retract_m: float = 0.05
    grasp_lateral_offset_m: float = 0.025
    pre_grasp_offset_m: float = 0.10
    max_target_radius_m: float = 0.66
    gripper_close_mm: float = 0.0
    gripper_open_mm: float = 85.0
    auto_home: bool = True
    place_max_radius_m: float = 0.46
    place_height_offset_m: float = 0.15
    place_min_flange_z_m: float = 0.30
    place_pitch_rad: float = 2.35619

    @model_validator(mode="after")
    def _validate(self) -> Self:
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, bool):
                continue
            _validate_finite(name, float(value))
        for name in (
            "tcp_tool_len_m",
            "grasp_penetration_m",
            "grasp_extra_retract_m",
            "grasp_lateral_offset_m",
            "pre_grasp_offset_m",
            "max_target_radius_m",
            "gripper_close_mm",
            "gripper_open_mm",
            "place_max_radius_m",
            "place_height_offset_m",
            "place_min_flange_z_m",
        ):
            if float(getattr(self, name)) < 0.0:
                raise ValueError(f"{name} must be non-negative")
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "approach_angle_rad": pa.array([self.approach_angle_rad], type=pa.float64()),
                "tcp_tool_len_m": pa.array([self.tcp_tool_len_m], type=pa.float64()),
                "grasp_penetration_m": pa.array([self.grasp_penetration_m], type=pa.float64()),
                "grasp_extra_retract_m": pa.array([self.grasp_extra_retract_m], type=pa.float64()),
                "grasp_lateral_offset_m": pa.array([self.grasp_lateral_offset_m], type=pa.float64()),
                "pre_grasp_offset_m": pa.array([self.pre_grasp_offset_m], type=pa.float64()),
                "max_target_radius_m": pa.array([self.max_target_radius_m], type=pa.float64()),
                "gripper_close_mm": pa.array([self.gripper_close_mm], type=pa.float64()),
                "gripper_open_mm": pa.array([self.gripper_open_mm], type=pa.float64()),
                "auto_home": pa.array([self.auto_home], type=pa.bool_()),
                "place_max_radius_m": pa.array([self.place_max_radius_m], type=pa.float64()),
                "place_height_offset_m": pa.array([self.place_height_offset_m], type=pa.float64()),
                "place_min_flange_z_m": pa.array([self.place_min_flange_z_m], type=pa.float64()),
                "place_pitch_rad": pa.array([self.place_pitch_rad], type=pa.float64()),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "ManipulationPlannerConfig":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("ManipulationPlannerConfig RecordBatch must contain one row")
        return cls(
            approach_angle_rad=float(batch["approach_angle_rad"][0].as_py()),
            tcp_tool_len_m=float(batch["tcp_tool_len_m"][0].as_py()),
            grasp_penetration_m=float(batch["grasp_penetration_m"][0].as_py()),
            grasp_extra_retract_m=float(batch["grasp_extra_retract_m"][0].as_py()),
            grasp_lateral_offset_m=float(batch["grasp_lateral_offset_m"][0].as_py()),
            pre_grasp_offset_m=float(batch["pre_grasp_offset_m"][0].as_py()),
            max_target_radius_m=float(batch["max_target_radius_m"][0].as_py()),
            gripper_close_mm=float(batch["gripper_close_mm"][0].as_py()),
            gripper_open_mm=float(batch["gripper_open_mm"][0].as_py()),
            auto_home=bool(batch["auto_home"][0].as_py()),
            place_max_radius_m=float(batch["place_max_radius_m"][0].as_py()),
            place_height_offset_m=float(batch["place_height_offset_m"][0].as_py()),
            place_min_flange_z_m=float(batch["place_min_flange_z_m"][0].as_py()),
            place_pitch_rad=float(batch["place_pitch_rad"][0].as_py()),
        )
