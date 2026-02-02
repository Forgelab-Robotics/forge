from typing import Literal
from dataclasses import dataclass


@dataclass
class JointValue:
    name: str
    value: float
    type: Literal["radians", "millimeters"]


@dataclass
class ActuatorValue:
    name: str
    value: float
    type: Literal["radians", "millimeters"]
