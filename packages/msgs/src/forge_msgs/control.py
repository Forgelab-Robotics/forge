from __future__ import annotations

import json
import re
from typing import Literal, Self

import pyarrow as pa
from pydantic import BaseModel, model_validator

from forge_msgs.arrow import ensure_record_batch

PolicyCommandStatusValue = Literal["accepted", "rejected", "running", "done", "error"]
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _validate_json_object(value: str, field_name: str) -> None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"{field_name} must be valid JSON") from e
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object")


def _read_str(batch: pa.RecordBatch, field_name: str) -> str:
    value = batch[field_name][0]
    if hasattr(value, "as_py"):
        value = value.as_py()
    return str(value)


class PolicyCommand(BaseModel):
    """Command payload sent from gateway to policy through Dora."""

    policy_id: str
    command: str
    request_id: str = ""
    inputs_json: str = "{}"

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not self.policy_id:
            raise ValueError("policy_id must be non-empty")
        if not self.command:
            raise ValueError("command must be non-empty")
        if not _SNAKE_CASE_RE.match(self.command):
            raise ValueError("command must use snake_case")
        _validate_json_object(self.inputs_json, "inputs_json")
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "policy_id": pa.array([self.policy_id], type=pa.string()),
                "command": pa.array([self.command], type=pa.string()),
                "request_id": pa.array([self.request_id], type=pa.string()),
                "inputs_json": pa.array([self.inputs_json], type=pa.string()),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "PolicyCommand":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("PolicyCommand RecordBatch must contain one row")
        return cls(
            policy_id=_read_str(batch, "policy_id"),
            command=_read_str(batch, "command"),
            request_id=_read_str(batch, "request_id"),
            inputs_json=_read_str(batch, "inputs_json"),
        )

    @classmethod
    def from_inputs(
        cls,
        *,
        policy_id: str,
        command: str,
        inputs: dict | None = None,
        request_id: str = "",
    ) -> "PolicyCommand":
        return cls(
            policy_id=policy_id,
            command=command,
            request_id=request_id,
            inputs_json=json.dumps(inputs or {}, separators=(",", ":")),
        )

    def inputs(self) -> dict:
        parsed = json.loads(self.inputs_json)
        if not isinstance(parsed, dict):
            raise ValueError("inputs_json must be a JSON object")
        return parsed


class PolicyCommandStatus(BaseModel):
    """Optional command status payload sent from policy to gateway through Dora."""

    policy_id: str
    command: str
    request_id: str = ""
    status: PolicyCommandStatusValue
    message: str = ""
    outputs_json: str = "{}"

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not self.policy_id:
            raise ValueError("policy_id must be non-empty")
        if not self.command:
            raise ValueError("command must be non-empty")
        if not _SNAKE_CASE_RE.match(self.command):
            raise ValueError("command must use snake_case")
        _validate_json_object(self.outputs_json, "outputs_json")
        return self

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "policy_id": pa.array([self.policy_id], type=pa.string()),
                "command": pa.array([self.command], type=pa.string()),
                "request_id": pa.array([self.request_id], type=pa.string()),
                "status": pa.array([self.status], type=pa.string()),
                "message": pa.array([self.message], type=pa.string()),
                "outputs_json": pa.array([self.outputs_json], type=pa.string()),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "PolicyCommandStatus":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("PolicyCommandStatus RecordBatch must contain one row")
        return cls(
            policy_id=_read_str(batch, "policy_id"),
            command=_read_str(batch, "command"),
            request_id=_read_str(batch, "request_id"),
            status=_read_str(batch, "status"),  # type: ignore[arg-type]
            message=_read_str(batch, "message"),
            outputs_json=_read_str(batch, "outputs_json"),
        )

    @classmethod
    def from_outputs(
        cls,
        *,
        policy_id: str,
        command: str,
        status: PolicyCommandStatusValue,
        outputs: dict | None = None,
        request_id: str = "",
        message: str = "",
    ) -> "PolicyCommandStatus":
        return cls(
            policy_id=policy_id,
            command=command,
            request_id=request_id,
            status=status,
            message=message,
            outputs_json=json.dumps(outputs or {}, separators=(",", ":")),
        )

    def outputs(self) -> dict:
        parsed = json.loads(self.outputs_json)
        if not isinstance(parsed, dict):
            raise ValueError("outputs_json must be a JSON object")
        return parsed
