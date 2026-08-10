from __future__ import annotations

import json

import pyarrow as pa
import pytest
from pydantic import ValidationError

from forge_msgs import ToolMessage, ToolMessageSizeError
from forge_msgs.tool import MAX_SAFE_JSON_INTEGER, TOOL_MESSAGE_SCHEMA


def _ipc_bytes(batch: pa.RecordBatch, *additional: pa.RecordBatch) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
        for additional_batch in additional:
            writer.write_batch(additional_batch)
    return sink.getvalue().to_pybytes()


def _invoke_message(**overrides: object) -> ToolMessage:
    values: dict[str, object] = {
        "message_type": "tool.invoke.request",
        "request_id": "request-1",
        "invocation_id": "invocation-1",
        "attempt_id": "attempt-1",
        "endpoint_id": "vision.yolo",
        "endpoint_instance_id": "instance-1",
        "operation": "detect",
        "payload_json": '{"arguments":{},"context":{}}',
    }
    values.update(overrides)
    return ToolMessage(**values)  # type: ignore[arg-type]


def test_tool_message_round_trips_record_batch_table_and_ipc() -> None:
    message = _invoke_message()

    batch = message.to_arrow()

    assert batch.schema == TOOL_MESSAGE_SCHEMA
    assert batch.num_rows == 1
    assert ToolMessage.from_arrow(batch) == message
    assert ToolMessage.from_arrow(pa.Table.from_batches([batch])) == message
    assert ToolMessage.from_arrow(_ipc_bytes(batch)) == message


def test_tool_message_round_trips_dora_struct_array() -> None:
    message = _invoke_message()
    batch = message.to_arrow()
    struct = pa.StructArray.from_arrays(
        [batch.column(index) for index in range(batch.num_columns)],
        fields=list(batch.schema),
    )

    assert ToolMessage.from_arrow(struct) == message


def test_tool_message_from_payload_uses_deterministic_strict_json() -> None:
    message = ToolMessage.from_payload(
        message_type="tool.invoke.request",
        request_id="request-1",
        invocation_id="invocation-1",
        attempt_id="attempt-1",
        endpoint_id="vision.yolo",
        endpoint_instance_id="instance-1",
        operation="detect",
        payload={"z": 1, "text": "方块", "a": []},
    )

    assert message.payload_json == '{"a":[],"text":"方块","z":1}'
    assert message.payload() == {"a": [], "text": "方块", "z": 1}


def test_management_and_event_correlation_rules() -> None:
    heartbeat = ToolMessage(
        message_type="endpoint.heartbeat",
        endpoint_id="vision.yolo",
        endpoint_instance_id="instance-1",
    )
    event = ToolMessage(
        message_type="tool.event",
        invocation_id="invocation-1",
        attempt_id="attempt-1",
        endpoint_id="vision.yolo",
        endpoint_instance_id="instance-1",
        operation="detect",
        sequence=0,
        payload_json='{"data":{},"type":"progress"}',
    )

    assert heartbeat.request_id is None
    assert event.request_id is None
    assert event.sequence == 0

    with pytest.raises(ValidationError, match="must be null"):
        ToolMessage(
            message_type="endpoint.heartbeat",
            invocation_id="invocation-1",
            endpoint_id="vision.yolo",
            endpoint_instance_id="instance-1",
        )
    with pytest.raises(ValidationError, match="sequence must be non-null"):
        _invoke_message(message_type="tool.event", request_id=None)
    with pytest.raises(ValidationError, match="request_id must be null"):
        _invoke_message(message_type="tool.event", sequence=0)


def test_tool_message_rejects_invalid_identity_and_sequence() -> None:
    for endpoint_id in ("", "\u00a0"):
        with pytest.raises(ValidationError, match="endpoint_id"):
            _invoke_message(endpoint_id=endpoint_id)
    with pytest.raises(ValidationError, match="invocation_id must be non-null"):
        _invoke_message(invocation_id=None)
    with pytest.raises(ValidationError, match="sequence must be null"):
        _invoke_message(sequence=0)
    with pytest.raises(ValidationError, match="sequence must be in"):
        _invoke_message(
            message_type="tool.event",
            request_id=None,
            sequence=MAX_SAFE_JSON_INTEGER + 1,
        )


def test_payload_json_is_strict_bounded_object() -> None:
    invalid_values = (
        "[]",
        "not-json",
        '{"value":NaN}',
        '{"value":1e999}',
        f'{{"value":{MAX_SAFE_JSON_INTEGER + 1}}}',
        '{"duplicate":1,"duplicate":2}',
        '{"\\ud800":1}',
    )
    for payload_json in invalid_values:
        with pytest.raises(ValidationError, match="payload_json"):
            _invoke_message(payload_json=payload_json)

    with pytest.raises(ValueError, match="strict JSON"):
        ToolMessage.from_payload(
            message_type="tool.invoke.request",
            request_id="request-1",
            invocation_id="invocation-1",
            attempt_id="attempt-1",
            endpoint_id="vision.yolo",
            endpoint_instance_id="instance-1",
            operation="detect",
            payload={"value": float("nan")},
        )

    with pytest.raises(ValueError, match="keys must be strings"):
        ToolMessage.from_payload(
            message_type="tool.invoke.request",
            request_id="request-1",
            invocation_id="invocation-1",
            attempt_id="attempt-1",
            endpoint_id="vision.yolo",
            endpoint_instance_id="instance-1",
            operation="detect",
            payload={"nested": {1: "value"}},  # type: ignore[dict-item]
        )


def test_assignment_revalidates_carrier_invariants() -> None:
    message = _invoke_message()

    with pytest.raises(ValidationError, match="frozen"):
        message.request_id = None
    with pytest.raises(ValidationError, match="frozen"):
        message.payload_json = '{"value":}'

    assert message.request_id == "request-1"
    assert message.payload_json == '{"arguments":{},"context":{}}'


def test_from_arrow_requires_exact_schema_and_one_row() -> None:
    message = _invoke_message()
    batch = message.to_arrow()

    empty = pa.RecordBatch.from_arrays(
        [pa.array([], type=field.type) for field in TOOL_MESSAGE_SCHEMA],
        schema=TOOL_MESSAGE_SCHEMA,
    )
    with pytest.raises(ValueError, match="exactly one row"):
        ToolMessage.from_arrow(empty)

    reordered = batch.select(list(reversed(batch.schema.names)))
    with pytest.raises(ValueError, match="exactly match"):
        ToolMessage.from_arrow(reordered)


def test_from_arrow_can_bound_raw_payload_json_before_model_validation() -> None:
    message = _invoke_message(payload_json='{"arguments":{},"context":{}}' + " " * 128)

    with pytest.raises(ToolMessageSizeError) as captured:
        ToolMessage.from_arrow(
            message.to_arrow(),
            max_payload_json_bytes=64,
        )

    assert captured.value.size > 64
    assert captured.value.maximum == 64

    with pytest.raises(ValueError, match="max_payload_json_bytes"):
        ToolMessage.from_arrow(
            message.to_arrow(),
            max_payload_json_bytes=True,
        )


def test_from_arrow_requires_exactly_one_record_batch() -> None:
    batch = _invoke_message().to_arrow()

    with pytest.raises(ValueError, match="exactly one RecordBatch"):
        ToolMessage.from_arrow(_ipc_bytes(batch, batch))
    with pytest.raises(ValueError, match="exactly one RecordBatch"):
        ToolMessage.from_arrow(pa.Table.from_batches([batch, batch]))


def test_payload_returns_fresh_object() -> None:
    message = _invoke_message(payload_json=json.dumps({"nested": {"value": 1}}))

    first = message.payload()
    nested = first["nested"]
    assert isinstance(nested, dict)
    nested["value"] = 2

    assert message.payload() == {"nested": {"value": 1}}
