"""Robot-related message definitions for Dora dataflow."""

from typing import Literal

from pydantic import BaseModel, Field


class ActuatorControlValue(BaseModel):
    """Single actuator control value."""

    name: str = Field(..., description="Actuator name")
    value: float = Field(..., description="Control value in unified units")
    type: Literal["radians", "meters"] = Field(
        default="radians",
        description="Unit type: radians for revolute, meters for prismatic",
    )


class ActuatorControl(BaseModel):
    """Control command sent from driver operator to simulator node."""

    values: list[ActuatorControlValue] = Field(
        default_factory=list,
        description="List of actuator control values",
    )


class JointStateValue(BaseModel):
    """Single joint state value."""

    name: str = Field(..., description="Joint name")
    value: float = Field(..., description="Position value in unified units")
    type: Literal["radians", "meters"] = Field(
        default="radians",
        description="Unit type: radians for revolute, meters for prismatic",
    )


class JointState(BaseModel):
    """Joint state published by simulator node, consumed by driver operator."""

    values: list[JointStateValue] = Field(
        default_factory=list,
        description="List of joint position values",
    )
