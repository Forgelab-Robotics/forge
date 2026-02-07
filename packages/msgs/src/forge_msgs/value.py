from pydantic import BaseModel
from typing import Literal

class JointValue(BaseModel):
    value: float
    mode: Literal["position", "velocity", "torque", "prismatic"]
    unit: Literal["radians", "meters", "radians/s", "meters/s", "Nm", "A"]

class ActuatorValue(BaseModel):
    value: float
    mode: Literal["position", "velocity", "torque", "prismatic"]
    unit: Literal["radians", "meters", "radians/s", "meters/s", "Nm", "A"]