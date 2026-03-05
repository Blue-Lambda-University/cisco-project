"""Handles incoming WebSocket messages with validation and routing."""

import json
from typing import Any

import structlog
from pydantic import ValidationError

from app.core.response_router import ResponseRouter
from app.models.enums import ErrorCode, MessageType
from app.models.messages import PAYLOAD_MODELS, IncomingMessage
from app.models.responses import A2AResponse, OutgoingResponse
from app.services.a2a_handler import A2AHandler


class MessageHandler:
    """
    Handles incoming WebSocket messages.
    
    Responsibilities:
    - Parse and validate incoming JSON messages
    - Handle plain text queries via A2A handler
    - Validate message structure and payload
    - Route messages to response generation
    - Generate appropriate error responses
    """

    def __init__(
        self,
        router: ResponseRouter,
        a2a_handler: A2AHandler,
        logger: structlog.BoundLogger,
    ) -> None:
        """
        Initialize the message handler.
        
        Args:
            router: Response router for generating responses.
            a2a_handler: A2A handler for plain text queries.
            logger: Bound logger instance.
        """
        self._router = router
        self._a2a_handler = a2a_handler
        self._logger = logger.bind(component="message_handler")

    async def handle(self, raw_message: str) -> OutgoingResponse | A2AResponse:
        """
        Handle a raw WebSocket message.
        
        Supports both JSON messages (existing flow) and plain text queries (A2A flow).
        
        Args:
            raw_message: The raw message string from the WebSocket.
            
        Returns:
            OutgoingResponse for JSON messages, or A2AResponse for plain text queries.
        """
        # Try to parse as JSON first
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            # Not valid JSON - treat as plain text query for A2A
            self._logger.info(
                "plain_text_query_detected",
                raw_message_preview=raw_message[:100] if raw_message else None,
            )
            return await self._a2a_handler.handle(raw_message)

        # Validate message structure
        try:
            message = IncomingMessage.model_validate(data)
        except ValidationError as e:
            self._logger.warning(
                "message_validation_failed",
                errors=e.errors(),
            )
            return self._router.create_error_response(
                code=ErrorCode.VALIDATION_ERROR,
                message="Message validation failed",
                details={"errors": self._format_validation_errors(e)},
            )

        # Bind message context for logging
        self._logger = self._logger.bind(
            message_type=message.type,
            correlation_id=message.metadata.correlation_id,
            session_id=message.metadata.session_id,
        )

        # Validate payload based on message type
        validation_result = self._validate_payload(message.type, message.payload)
        if validation_result is not None:
            return validation_result

        self._logger.info(
            "message_received",
            payload_keys=list(message.payload.keys()),
        )

        # Route to response
        return await self._router.route(
            message_type=message.type,
            payload=message.payload,
            correlation_id=message.metadata.correlation_id,
        )

    def _validate_payload(
        self,
        message_type: str,
        payload: dict[str, Any],
    ) -> OutgoingResponse | None:
        """
        Validate payload against the expected model for the message type.
        
        Args:
            message_type: The message type.
            payload: The payload to validate.
            
        Returns:
            Error response if validation fails, None if valid.
        """
        # Get the payload model for this message type
        try:
            msg_type = MessageType(message_type)
        except ValueError:
            # Unknown message type - let router handle it
            return None

        payload_model = PAYLOAD_MODELS.get(msg_type)
        if payload_model is None:
            return None

        try:
            payload_model.model_validate(payload)
            return None
        except ValidationError as e:
            self._logger.warning(
                "payload_validation_failed",
                message_type=message_type,
                errors=e.errors(),
            )
            return self._router.create_error_response(
                code=ErrorCode.INVALID_PAYLOAD,
                message=f"Invalid payload for message type '{message_type}'",
                details={
                    "errors": self._format_validation_errors(e),
                    "message_type": message_type,
                },
            )

    def _format_validation_errors(self, error: ValidationError) -> list[dict[str, Any]]:
        """
        Format Pydantic validation errors for response.
        
        Args:
            error: The ValidationError.
            
        Returns:
            List of formatted error dictionaries.
        """
        formatted = []
        for err in error.errors():
            formatted.append({
                "field": ".".join(str(loc) for loc in err["loc"]),
                "message": err["msg"],
                "type": err["type"],
            })
        return formatted

    async def handle_with_context(
        self,
        raw_message: str,
        connection_id: str,
        subprotocol: str | None = None,
    ) -> OutgoingResponse | A2AResponse:
        """
        Handle a message with additional connection context.
        
        Args:
            raw_message: The raw message string.
            connection_id: The connection ID.
            subprotocol: The negotiated subprotocol.
            
        Returns:
            OutgoingResponse for JSON messages, or A2AResponse for plain text queries.
        """
        # Bind connection context
        self._logger = self._logger.bind(
            connection_id=connection_id,
            subprotocol=subprotocol,
        )
        
        return await self.handle(raw_message)
