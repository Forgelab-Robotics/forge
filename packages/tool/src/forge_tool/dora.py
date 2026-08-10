"""Optional Arrow/Dora carrier binding for an embedded ToolEndpoint handler."""

from __future__ import annotations

import pyarrow as pa
from forge_msgs import ToolMessage

from .handler import ToolEndpointHandler
from .wire import ToolEnvelope, validate_message_envelope


type _ToolArrowValue = pa.RecordBatch | pa.Table | pa.StructArray | bytes


def tool_message_to_envelope(message: ToolMessage) -> ToolEnvelope:
    """Convert one validated Arrow carrier model to its logical envelope."""
    if not isinstance(message, ToolMessage):
        raise TypeError("message must be a forge_msgs.ToolMessage")
    return ToolEnvelope(
        protocol=message.protocol,
        message_type=message.message_type,
        request_id=message.request_id,
        invocation_id=message.invocation_id,
        attempt_id=message.attempt_id,
        endpoint_id=message.endpoint_id,
        endpoint_instance_id=message.endpoint_instance_id,
        operation=message.operation,
        sequence=message.sequence,
        payload=message.payload(),
    )


def tool_envelope_to_message(envelope: ToolEnvelope) -> ToolMessage:
    """Convert one typed logical envelope to the exact Arrow carrier model."""
    if not isinstance(envelope, ToolEnvelope):
        raise TypeError("envelope must be a ToolEnvelope")
    validate_message_envelope(envelope)
    return ToolMessage.from_payload(
        message_type=envelope.message_type,
        request_id=envelope.request_id,
        invocation_id=envelope.invocation_id,
        attempt_id=envelope.attempt_id,
        endpoint_id=envelope.endpoint_id,
        endpoint_instance_id=envelope.endpoint_instance_id,
        operation=envelope.operation,
        sequence=envelope.sequence,
        payload=envelope.payload,
    )


class DoraToolEndpointBinding:
    """Bridge one Dora ToolMessage input value to a logical endpoint handler.

    The binding owns no Dora ``Node`` and does not observe or rewrite Dora event
    metadata. A business node remains responsible for receiving the input, awaiting
    ``handle_input``, and publishing the returned RecordBatch on its configured output.
    """

    __slots__ = ("_handler",)

    def __init__(self, handler: ToolEndpointHandler) -> None:
        if not isinstance(handler, ToolEndpointHandler):
            raise TypeError("handler must be a ToolEndpointHandler")
        self._handler = handler

    @property
    def handler(self) -> ToolEndpointHandler:
        """Return the embedded transport-independent handler."""
        return self._handler

    async def handle_input(self, value: _ToolArrowValue) -> pa.RecordBatch:
        """Decode one Query invoke input and return its Arrow response value."""
        message = ToolMessage.from_arrow(value)
        request = tool_message_to_envelope(message)
        response = await self._handler.handle_invoke(request)
        return tool_envelope_to_message(response).to_arrow()


__all__ = [
    "DoraToolEndpointBinding",
    "tool_envelope_to_message",
    "tool_message_to_envelope",
]
