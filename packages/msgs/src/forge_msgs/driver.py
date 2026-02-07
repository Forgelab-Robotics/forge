from forge.packages.msgs.src.forge_msgs.value import ActuatorValue
from pydantic import BaseModel
from typing import Dict

class DriverFeedback(BaseModel):
    timestamp: float
    actuators: Dict[str, ActuatorValue]

class DriverCommand(BaseModel):
    timestamp: float
    actuators: Dict[str, ActuatorValue]