from typing import Literal
from dataclasses import dataclass


@dataclass
class JointValue:
    name: str
    value: float
    type: Literal["radians", "meters"]


@dataclass
class ActuatorValue:
    name: str
    value: float
    type: Literal["radians", "meters"]
