from __future__ import annotations

import math
from typing import Self

import pyarrow as pa
from pydantic import BaseModel, model_validator

from forge_msgs.arrow import ensure_record_batch


def _validate_finite(field_name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")


class LocomotionCommand(BaseModel):
    """Planar body-frame locomotion velocity command.

    ``vx`` is forward-positive linear velocity in m/s, ``vy`` is left-positive
    lateral velocity in m/s, and ``wz`` is counter-clockwise-positive angular
    velocity around the body Z axis in rad/s.
    """

    vx: float
    vy: float
    wz: float

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _validate_finite("vx", self.vx)
        _validate_finite("vy", self.vy)
        _validate_finite("wz", self.wz)
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "vx": pa.array([self.vx], type=pa.float64()),
                "vy": pa.array([self.vy], type=pa.float64()),
                "wz": pa.array([self.wz], type=pa.float64()),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "LocomotionCommand":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("LocomotionCommand RecordBatch must contain one row")
        return cls(
            vx=float(batch["vx"][0].as_py()),
            vy=float(batch["vy"][0].as_py()),
            wz=float(batch["wz"][0].as_py()),
        )
