from forge_msgs.value import JointValue
from pydantic import BaseModel
from typing import Dict

class PolicyObservation(BaseModel):
    timestamp: float
    joints: Dict[str, JointValue]

class PolicyAction(BaseModel):
    ref_timestamp: float 
    joints: Dict[str, JointValue]