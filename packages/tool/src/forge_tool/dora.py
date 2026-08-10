"""Optional Arrow/Dora carrier binding for an embedded ToolEndpoint handler."""

from __future__ import annotations

import logging

import pyarrow as pa
from forge_msgs import ToolMessage, ToolMessageSizeError

from .endpoint import ToolError
from .handler import ToolEndpointHandler
from .wire import (
    DEFAULT_MAX_MESSAGE_BYTES,
    ToolEnvelope,
    ToolProtocolError,
    make_error_response_envelope,
    validate_message_envelope,
)
from .wire.codec import encoded_envelope_size

logger = logging.getLogger(__name__)

_CORRELATED_ERROR_RESERVE_BYTES = 512
_MIN_BINDING_MESSAGE_BYTES = 1_024
_DEFAULT_CARRIER_OVERHEAD_BYTES = 65_536

type _ToolArrowValue = pa.RecordBatch | pa.Table | pa.StructArray


def _message_envelope(message: ToolMessage) -> ToolEnvelope:
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


def _validate_maximum(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _validate_envelope_size(envelope: ToolEnvelope, maximum: int) -> None:
    size = encoded_envelope_size(envelope)
    if size > maximum:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_MESSAGE_TOO_LARGE",
            f"message size {size} exceeds limit {maximum}",
        )


def _carrier_size(value: _ToolArrowValue) -> int | None:
    if isinstance(value, (pa.RecordBatch, pa.Table, pa.StructArray)):
        return value.nbytes
    return None


def _validate_carrier_size(value: _ToolArrowValue, maximum: int) -> None:
    size = _carrier_size(value)
    if size is not None and size > maximum:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_MESSAGE_TOO_LARGE",
            f"Arrow carrier size {size} exceeds limit {maximum}",
        )


def _correlated_protocol_error(
    error: ToolProtocolError,
    request: ToolEnvelope,
    *,
    max_message_bytes: int,
    max_request_bytes: int | None = None,
) -> ToolEnvelope:
    details: dict[str, object] = {}
    if error.code == "FORGE_PROTOCOL_MESSAGE_TOO_LARGE":
        message = "ToolEndpoint message exceeds the configured size limit"
        details["max_message_bytes"] = max_message_bytes
        if max_request_bytes is not None:
            details["max_request_bytes"] = max_request_bytes
    else:
        message = "ToolEndpoint response violates the Wire protocol"
    return make_error_response_envelope(
        ToolError(
            code=error.code,
            message=message,
            retryable=False,
            details=details,
        ),
        request,
    )


def _correlated_internal_error(request: ToolEnvelope) -> ToolEnvelope:
    return make_error_response_envelope(
        ToolError(
            code="FORGE_ENDPOINT_INTERNAL",
            message="endpoint failed to produce a valid response",
            retryable=False,
        ),
        request,
    )


def tool_message_to_envelope(
    message: ToolMessage,
    *,
    max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
) -> ToolEnvelope:
    """Convert one carrier model and enforce the logical encoded-message limit."""
    if not isinstance(message, ToolMessage):
        raise TypeError("message must be a forge_msgs.ToolMessage")
    maximum = _validate_maximum(max_message_bytes, "max_message_bytes")
    envelope = _message_envelope(message)
    _validate_envelope_size(envelope, maximum)
    return envelope


def tool_envelope_to_message(
    envelope: ToolEnvelope,
    *,
    max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
) -> ToolMessage:
    """Convert one logical envelope and enforce the logical encoded-message limit."""
    if not isinstance(envelope, ToolEnvelope):
        raise TypeError("envelope must be a ToolEnvelope")
    maximum = _validate_maximum(max_message_bytes, "max_message_bytes")
    validate_message_envelope(envelope)
    _validate_envelope_size(envelope, maximum)
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
    """Bridge one bounded Dora ToolMessage input to a logical endpoint handler.

    The binding owns no Dora ``Node`` and does not observe or rewrite Dora event
    metadata. A business node remains responsible for receiving the input, awaiting
    ``handle_input``, and publishing the returned RecordBatch on its configured output.
    Raw in-memory Arrow carriers and payload JSON are bounded before typed JSON handling.
    IPC bytes are rejected because compressed IPC must be decoded by an upstream transport
    with its own framing and decompression limits. Accepted requests reserve response
    headroom so endpoint and encoding failures can remain correlated within the configured
    logical encoded-message limit.
    """

    __slots__ = (
        "_handler",
        "_max_carrier_bytes",
        "_max_message_bytes",
        "_max_request_bytes",
    )

    def __init__(
        self,
        handler: ToolEndpointHandler,
        *,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        max_carrier_bytes: int | None = None,
    ) -> None:
        if not isinstance(handler, ToolEndpointHandler):
            raise TypeError("handler must be a ToolEndpointHandler")
        maximum = _validate_maximum(max_message_bytes, "max_message_bytes")
        if maximum < _MIN_BINDING_MESSAGE_BYTES:
            raise ValueError(
                f"max_message_bytes must be at least {_MIN_BINDING_MESSAGE_BYTES} "
                "for correlated error responses"
            )
        carrier_maximum = (
            maximum + _DEFAULT_CARRIER_OVERHEAD_BYTES
            if max_carrier_bytes is None
            else _validate_maximum(max_carrier_bytes, "max_carrier_bytes")
        )
        if carrier_maximum < maximum:
            raise ValueError("max_carrier_bytes must be at least max_message_bytes")

        self._handler = handler
        self._max_message_bytes = maximum
        self._max_request_bytes = maximum - _CORRELATED_ERROR_RESERVE_BYTES
        self._max_carrier_bytes = carrier_maximum

    @property
    def handler(self) -> ToolEndpointHandler:
        """Return the embedded transport-independent handler."""
        return self._handler

    @property
    def max_message_bytes(self) -> int:
        """Return the outbound logical encoded-message limit."""
        return self._max_message_bytes

    @property
    def max_request_bytes(self) -> int:
        """Return the inbound execution limit after correlated-error headroom."""
        return self._max_request_bytes

    @property
    def max_carrier_bytes(self) -> int:
        """Return the pre-decode Arrow carrier byte limit."""
        return self._max_carrier_bytes

    def _fallback_to_arrow(
        self,
        fallback: ToolEnvelope,
        request: ToolEnvelope,
        original_error: Exception,
    ) -> pa.RecordBatch:
        try:
            return tool_envelope_to_message(
                fallback,
                max_message_bytes=self._max_message_bytes,
            ).to_arrow()
        except Exception:
            logger.exception(
                "correlated ToolEndpoint fallback does not fit request_id=%s "
                "invocation_id=%s attempt_id=%s endpoint_id=%s "
                "endpoint_instance_id=%s operation=%s",
                request.request_id,
                request.invocation_id,
                request.attempt_id,
                request.endpoint_id,
                request.endpoint_instance_id,
                request.operation,
            )
            raise original_error

    def _response_to_arrow(
        self,
        response: ToolEnvelope,
        request: ToolEnvelope,
    ) -> pa.RecordBatch:
        try:
            return tool_envelope_to_message(
                response,
                max_message_bytes=self._max_message_bytes,
            ).to_arrow()
        except ToolProtocolError as error:
            fallback = _correlated_protocol_error(
                error,
                request,
                max_message_bytes=self._max_message_bytes,
            )
            return self._fallback_to_arrow(fallback, request, error)
        except (TypeError, ValueError, UnicodeError) as error:
            return self._fallback_to_arrow(
                _correlated_internal_error(request),
                request,
                error,
            )

    async def handle_input(self, value: _ToolArrowValue) -> pa.RecordBatch:
        """Decode one Query invoke input and return its bounded Arrow response value."""
        if isinstance(value, bytes):
            raise TypeError(
                "DoraToolEndpointBinding does not accept IPC bytes; decode them upstream "
                "under bounded framing and decompression limits"
            )
        _validate_carrier_size(value, self._max_carrier_bytes)
        try:
            message = ToolMessage.from_arrow(
                value,
                max_payload_json_bytes=self._max_message_bytes,
            )
        except ToolMessageSizeError as error:
            raise ToolProtocolError(
                "FORGE_PROTOCOL_MESSAGE_TOO_LARGE",
                str(error),
            ) from error
        request = _message_envelope(message)

        # Do not answer a request for another endpoint route. Once the route is trusted,
        # accepted requests reserve enough headroom for later correlated failures.
        self._handler.validate_invoke_route(request)
        try:
            _validate_envelope_size(request, self._max_request_bytes)
        except ToolProtocolError as error:
            fallback = _correlated_protocol_error(
                error,
                request,
                max_message_bytes=self._max_message_bytes,
                max_request_bytes=self._max_request_bytes,
            )
            return self._fallback_to_arrow(fallback, request, error)

        try:
            response = await self._handler.handle_invoke(request)
        except Exception:  # noqa: BLE001 - trusted requests must receive a response.
            logger.exception(
                "ToolEndpoint failed request_id=%s invocation_id=%s attempt_id=%s "
                "endpoint_id=%s endpoint_instance_id=%s operation=%s",
                request.request_id,
                request.invocation_id,
                request.attempt_id,
                request.endpoint_id,
                request.endpoint_instance_id,
                request.operation,
            )
            response = _correlated_internal_error(request)
        return self._response_to_arrow(response, request)


__all__ = [
    "DoraToolEndpointBinding",
    "tool_envelope_to_message",
    "tool_message_to_envelope",
]
