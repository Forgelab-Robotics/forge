"""XR teleop observation message for Dora dataflow."""

from __future__ import annotations

import json
import math
from typing import Self

import pyarrow as pa
from pydantic import BaseModel, model_validator

from forge_msgs.arrow import ensure_record_batch


def _validate_json_object(value: str, field_name: str) -> None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"{field_name} must be valid JSON") from e
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object")


def _float_list(values: list[float]) -> pa.Array:
    return pa.array([values], type=pa.list_(pa.float64()))


def _str_list(values: list[str]) -> pa.Array:
    return pa.array([values], type=pa.list_(pa.string()))


def _read_float_list(batch: pa.RecordBatch, field: str) -> list[float]:
    values = batch[field][0].as_py()
    return [float(value) for value in (values or [])]


class TeleopObservation(BaseModel):
    """XR device raw teleop observation payload.

    ``device`` names XR sources (recommended: ``left``, ``right``, ``headset``);
    consumers must match poses by id rather than list position. Positions are in
    meters and quaternions use ``qx, qy, qz, qw`` order in the producer's
    configured XR tracking frame. ``confidence`` is a producer-defined value in
    ``[0, 1]``; a pose with zero confidence must not be used for control.

    Button and axis payloads are JSON objects for extensibility. Timing and the
    tracking-frame convention are not carried in the payload and should live in
    Dora event context, node configuration, or an adapter layer.
    """

    device: list[str]
    x: list[float]
    y: list[float]
    z: list[float]
    qx: list[float]
    qy: list[float]
    qz: list[float]
    qw: list[float]
    confidence: list[float]
    buttons_json: str = "{}"
    axes_json: str = "{}"

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not self.device:
            raise ValueError("device must contain at least one item")
        if len(set(self.device)) != len(self.device):
            raise ValueError("device items must be unique")
        length = len(self.device)
        for field in ("x", "y", "z", "qx", "qy", "qz", "qw", "confidence"):
            values = getattr(self, field)
            if len(values) != length:
                raise ValueError(f"{field} must have the same length as device")
            if not all(math.isfinite(value) for value in values):
                raise ValueError(f"{field} values must be finite")
        if not all(0.0 <= value <= 1.0 for value in self.confidence):
            raise ValueError("confidence values must be in the inclusive range [0, 1]")
        for qx, qy, qz, qw in zip(self.qx, self.qy, self.qz, self.qw, strict=True):
            if qx == 0.0 and qy == 0.0 and qz == 0.0 and qw == 0.0:
                raise ValueError("quaternion must not be all zero")
        _validate_json_object(self.buttons_json, "buttons_json")
        _validate_json_object(self.axes_json, "axes_json")
        return self

    @classmethod
    def from_device_poses(
        cls,
        poses: dict[str, tuple[float, float, float, float, float, float, float]],
        *,
        confidence: dict[str, float] | None = None,
        buttons: dict[str, bool | float] | None = None,
        axes: dict[str, float | list[float]] | None = None,
    ) -> "TeleopObservation":
        """Build from device -> (x,y,z,qx,qy,qz,qw) mappings.

        Device ids are sorted only to make serialization deterministic; readers
        must still resolve entries by id. Missing confidence values default to
        1.0.
        """
        names = sorted(poses)
        conf = confidence or {}
        return cls(
            device=names,
            x=[poses[name][0] for name in names],
            y=[poses[name][1] for name in names],
            z=[poses[name][2] for name in names],
            qx=[poses[name][3] for name in names],
            qy=[poses[name][4] for name in names],
            qz=[poses[name][5] for name in names],
            qw=[poses[name][6] for name in names],
            confidence=[float(conf.get(name, 1.0)) for name in names],
            buttons_json=json.dumps(buttons or {}, separators=(",", ":")),
            axes_json=json.dumps(axes or {}, separators=(",", ":")),
        )

    def buttons(self) -> dict:
        parsed = json.loads(self.buttons_json)
        if not isinstance(parsed, dict):
            raise ValueError("buttons_json must be a JSON object")
        return parsed

    def axes(self) -> dict:
        parsed = json.loads(self.axes_json)
        if not isinstance(parsed, dict):
            raise ValueError("axes_json must be a JSON object")
        return parsed

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "device": _str_list(self.device),
                "x": _float_list(self.x),
                "y": _float_list(self.y),
                "z": _float_list(self.z),
                "qx": _float_list(self.qx),
                "qy": _float_list(self.qy),
                "qz": _float_list(self.qz),
                "qw": _float_list(self.qw),
                "confidence": _float_list(self.confidence),
                "buttons_json": pa.array([self.buttons_json], type=pa.string()),
                "axes_json": pa.array([self.axes_json], type=pa.string()),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "TeleopObservation":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("TeleopObservation RecordBatch must contain one row")
        return cls(
            device=list(batch["device"][0].as_py() or []),
            x=_read_float_list(batch, "x"),
            y=_read_float_list(batch, "y"),
            z=_read_float_list(batch, "z"),
            qx=_read_float_list(batch, "qx"),
            qy=_read_float_list(batch, "qy"),
            qz=_read_float_list(batch, "qz"),
            qw=_read_float_list(batch, "qw"),
            confidence=_read_float_list(batch, "confidence"),
            buttons_json=str(batch["buttons_json"][0].as_py() or "{}"),
            axes_json=str(batch["axes_json"][0].as_py() or "{}"),
        )
