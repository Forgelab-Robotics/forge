from __future__ import annotations

import pytest

from forge_tool import (
    TOOL_ENDPOINT_PROTOCOL,
    ToolEndpointDescriptor,
    ToolEnvelope,
    ToolOperationDescriptor,
    ToolProtocolError,
    decode_envelope,
    encode_envelope,
    endpoint_descriptor_from_payload,
    endpoint_descriptor_to_payload,
    validate_registration_envelope,
)


def _descriptor() -> ToolEndpointDescriptor:
    return ToolEndpointDescriptor(
        protocol_version=TOOL_ENDPOINT_PROTOCOL,
        endpoint_id="policy.lerobot",
        operations=(
            ToolOperationDescriptor(
                name="execute",
                semantics="session",
                stoppable=True,
                status_supported=True,
                max_concurrency=1,
            ),
        ),
    )


def test_endpoint_descriptor_registration_payload_round_trip() -> None:
    descriptor = _descriptor()

    payload = endpoint_descriptor_to_payload(descriptor)

    assert payload == {
        "descriptor": {
            "protocol_version": TOOL_ENDPOINT_PROTOCOL,
            "endpoint_id": "policy.lerobot",
            "operations": [
                {
                    "name": "execute",
                    "semantics": "session",
                    "cancellable": False,
                    "stoppable": True,
                    "status_supported": True,
                    "max_concurrency": 1,
                }
            ],
        }
    }
    assert endpoint_descriptor_from_payload(payload) == descriptor


def test_complete_registration_envelope_is_validated_at_codec_boundary() -> None:
    envelope = ToolEnvelope(
        protocol=TOOL_ENDPOINT_PROTOCOL,
        message_type="endpoint.register",
        request_id="register-1",
        endpoint_id="policy.lerobot",
        endpoint_instance_id="endpoint-instance-1",
        payload=endpoint_descriptor_to_payload(_descriptor()),
    )

    decoded = decode_envelope(encode_envelope(envelope))

    assert validate_registration_envelope(decoded) == _descriptor()


def test_registration_rejects_invalid_payload_and_endpoint_identity() -> None:
    invalid_payload = (
        '{"protocol":"forge.tool.endpoint/v1alpha1",'
        '"message_type":"endpoint.register",'
        '"request_id":"register-1",'
        '"endpoint_id":"policy.lerobot",'
        '"endpoint_instance_id":"instance-1",'
        '"payload":{"tool_spec":{}}}'
    )
    with pytest.raises(ToolProtocolError, match="descriptor"):
        decode_envelope(invalid_payload)

    mismatched = ToolEnvelope(
        protocol=TOOL_ENDPOINT_PROTOCOL,
        message_type="endpoint.register",
        request_id="register-1",
        endpoint_id="policy.other",
        endpoint_instance_id="endpoint-instance-1",
        payload=endpoint_descriptor_to_payload(_descriptor()),
    )
    with pytest.raises(ToolProtocolError, match="must match"):
        encode_envelope(mismatched)


def test_descriptor_payload_rejects_unknown_or_missing_fields() -> None:
    payload = endpoint_descriptor_to_payload(_descriptor())
    descriptor = payload["descriptor"]
    assert isinstance(descriptor, dict)
    descriptor["unknown"] = True

    with pytest.raises(ToolProtocolError, match="unknown fields"):
        endpoint_descriptor_from_payload(payload)

    with pytest.raises(ToolProtocolError, match="missing fields"):
        endpoint_descriptor_from_payload(
            {
                "descriptor": {
                    "protocol_version": TOOL_ENDPOINT_PROTOCOL,
                    "endpoint_id": "policy.lerobot",
                }
            }
        )


def test_descriptor_payload_rejects_protocol_mismatch() -> None:
    descriptor = ToolEndpointDescriptor(
        protocol_version="forge.tool.endpoint/v2",
        endpoint_id="policy.lerobot",
        operations=(
            ToolOperationDescriptor(
                name="execute",
                semantics="session",
                status_supported=True,
            ),
        ),
    )

    with pytest.raises(ToolProtocolError) as captured:
        endpoint_descriptor_to_payload(descriptor)

    assert captured.value.code == "FORGE_PROTOCOL_UNSUPPORTED_VERSION"
    assert captured.value.path == "payload.descriptor.protocol_version"


def test_descriptor_payload_rejects_non_string_object_keys() -> None:
    with pytest.raises(ToolProtocolError, match="keys must be strings"):
        endpoint_descriptor_from_payload({1: "invalid"})  # type: ignore[dict-item]


def test_descriptor_payload_reports_operation_path() -> None:
    payload = endpoint_descriptor_to_payload(_descriptor())
    descriptor = payload["descriptor"]
    assert isinstance(descriptor, dict)
    operations = descriptor["operations"]
    assert isinstance(operations, list)
    operation = operations[0]
    assert isinstance(operation, dict)
    operation["max_concurrency"] = 0

    with pytest.raises(ToolProtocolError) as captured:
        endpoint_descriptor_from_payload(payload)

    assert captured.value.path == "payload.descriptor.operations[0]"
