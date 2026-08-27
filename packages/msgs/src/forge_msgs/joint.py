from __future__ import annotations

from typing import Literal, Self

import numpy as np
import pyarrow as pa
from pydantic import BaseModel, model_validator

from forge_msgs.arrow import ensure_record_batch

JointField = Literal["position", "velocity", "effort"]
CommandField = Literal["position", "velocity", "effort", "kp", "kd"]
CommandMode = Literal["position", "velocity", "effort", "hybrid"]


def _validate_names(name: list[str]) -> None:
    if not name:
        raise ValueError("name must contain at least one joint")
    if len(set(name)) != len(name):
        raise ValueError("name items must be unique")


def _validate_vector_length(
    field_name: str, values: list[float], names: list[str]
) -> None:
    if values and len(values) != len(names):
        raise ValueError(
            f"{field_name} must be empty or have the same length as name "
            f"({len(values)} != {len(names)})"
        )


def _field_values(batch: pa.RecordBatch, field_name: str) -> list[float]:
    values = batch[field_name][0].as_py()
    return [float(v) for v in (values or [])]


def _to_ordered_np(
    names: list[str], values: list[float], order: list[str]
) -> np.ndarray:
    by_name = dict(zip(names, values, strict=False))
    return np.array([by_name.get(name, 0.0) for name in order], dtype=np.float64)


def _name_array(names: list[str]) -> pa.Array:
    return pa.array([names], type=pa.list_(pa.string()))


def _float_list_array(values: list[float]) -> pa.Array:
    return pa.array([values], type=pa.list_(pa.float64()))


def _command_mode(batch: pa.RecordBatch) -> str:
    if "mode" not in batch.schema.names:
        return "position"
    mode = batch["mode"][0].as_py()
    if mode is None:
        return "position"
    return str(mode)


class JointState(BaseModel):
    """Robot or simulator joint observation payload."""

    name: list[str]
    position: list[float] = []
    velocity: list[float] = []
    effort: list[float] = []

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _validate_names(self.name)
        _validate_vector_length("position", self.position, self.name)
        _validate_vector_length("velocity", self.velocity, self.name)
        _validate_vector_length("effort", self.effort, self.name)
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "name": _name_array(self.name),
                "position": _float_list_array(self.position),
                "velocity": _float_list_array(self.velocity),
                "effort": _float_list_array(self.effort),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "JointState":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("JointState RecordBatch must contain one row")
        return cls(
            name=list(batch["name"][0].as_py() or []),
            position=_field_values(batch, "position"),
            velocity=_field_values(batch, "velocity"),
            effort=_field_values(batch, "effort"),
        )

    def to_np(
        self,
        order: list[str],
        field: JointField = "position",
    ) -> np.ndarray:
        return _to_ordered_np(self.name, getattr(self, field), order)

    @classmethod
    def from_np(
        cls,
        values: np.ndarray,
        order: list[str],
        field: JointField = "position",
    ) -> "JointState":
        payload: dict[str, list[float] | list[str]] = {
            "name": list(order),
            "position": [],
            "velocity": [],
            "effort": [],
        }
        payload[field] = [float(v) for v in values[: len(order)]]
        return cls(**payload)


class JointCommand(BaseModel):
    """Sparse joint command payload for robot drivers and controllers.

    ``name`` is the update set for this message. Actuators omitted from ``name``
    must retain their previous command target and must not be reset implicitly.
    """

    name: list[str]
    mode: CommandMode = "position"
    position: list[float] = []
    velocity: list[float] = []
    effort: list[float] = []
    kp: list[float] = []
    kd: list[float] = []

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _validate_names(self.name)
        _validate_vector_length("position", self.position, self.name)
        _validate_vector_length("velocity", self.velocity, self.name)
        _validate_vector_length("effort", self.effort, self.name)
        _validate_vector_length("kp", self.kp, self.name)
        _validate_vector_length("kd", self.kd, self.name)
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "name": _name_array(self.name),
                "mode": pa.array([self.mode], type=pa.string()),
                "position": _float_list_array(self.position),
                "velocity": _float_list_array(self.velocity),
                "effort": _float_list_array(self.effort),
                "kp": _float_list_array(self.kp),
                "kd": _float_list_array(self.kd),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "JointCommand":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("JointCommand RecordBatch must contain one row")
        return cls(
            name=list(batch["name"][0].as_py() or []),
            mode=_command_mode(batch),
            position=_field_values(batch, "position"),
            velocity=_field_values(batch, "velocity"),
            effort=_field_values(batch, "effort"),
            kp=_field_values(batch, "kp"),
            kd=_field_values(batch, "kd"),
        )

    def to_np(
        self,
        order: list[str],
        field: CommandField = "position",
    ) -> np.ndarray:
        return _to_ordered_np(self.name, getattr(self, field), order)

    @classmethod
    def from_np(
        cls,
        values: np.ndarray,
        order: list[str],
        field: CommandField = "position",
    ) -> "JointCommand":
        payload: dict[str, list[float] | list[str]] = {
            "name": list(order),
            "position": [],
            "velocity": [],
            "effort": [],
            "kp": [],
            "kd": [],
        }
        payload[field] = [float(v) for v in values[: len(order)]]
        return cls(**payload)
