"""Handles incoming WebSocket messages with validation and routing."""

import json
import uuid
from typing import Any

import structlog
from pydantic import ValidationError

from app.config import Settings
from app.core.correlation_store import CorrelationStore, RedisCorrelationStore
from app.core.response_router import ResponseRouter
from app.core.session_store import InMemorySessionStore, RedisSessionStore
from app.logging.setup import bind_message_context
from app.models.a2a_requests import (
    A2ASendMessageRequest,
    extract_a2a_ids_and_query,
    parse_a2a_request,
)
from app.models.enums import ErrorCode, MessageType
from app.models.messages import PAYLOAD_MODELS, IncomingMessage
from app.models.responses import (
    A2AErrorDetail,
    A2AErrorResponse,
    OutgoingResponse,
    UIResponse,
)
from app.services.agent_client import AgentClient
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
        session_store: InMemorySessionStore | RedisSessionStore,
        logger: structlog.BoundLogger,
        settings: Settings | None = None,
        correlation_store: CorrelationStore | RedisCorrelationStore | None = None,
        agent_client: AgentClient | None = None,
    ) -> None:
        self._router = router
        self._a2a_handler = a2a_handler
        self._session_store = session_store
        self._logger = logger.bind(component="message_handler")
        self._settings = settings
        self._correlation_store = correlation_store
        self._agent_client = agent_client

    async def handle(
        self,
        raw_message: str,
        connection_id: str | None = None,
    ) -> OutgoingResponse | UIResponse | A2AErrorResponse | None:
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

        # A2A JSON-RPC (agent/sendMessage): handle before legacy IncomingMessage
        a2a_request = parse_a2a_request(data)
        if a2a_request is not None:
            return await self._handle_a2a_request(a2a_request, connection_id=connection_id)

        # If it looks like JSON-RPC A2A but failed to parse, return A2A error (not legacy)
        method = data.get("method")
        params = data.get("params")
        is_a2a_style = (
            data.get("jsonrpc") == "2.0"
            and (method is None or method in ("agent/sendMessage", "SendMessage"))
            and isinstance(params, dict)
            and "message" in params
        )
        if is_a2a_style:
            response_id = data.get("id")
            if response_id is not None:
                response_id = str(response_id)
            self._logger.warning(
                "a2a_request_parse_failed",
                method=method,
                has_params=True,
            )
            return A2AErrorResponse(
                jsonrpc="2.0",
                error=A2AErrorDetail(
                    code=-32602,
                    message="Invalid params: expected params.message with role and parts (e.g. parts[].text).",
                ),
                id=response_id,
            )

        # Validate message structure (legacy type/payload/metadata)
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

        # Session: get or create, validate, extend TTL (sliding window)
        session_id = message.metadata.session_id if message.metadata.session_id else None
        if session_id and session_id.strip():
            session_id = session_id.strip()
            if self._session_store.get(session_id) is None:
                self._logger.info("session_expired_or_unknown", session_id=session_id)
                return self._router.create_error_response(
                    code=ErrorCode.SESSION_EXPIRED,
                    message="Session expired or not found. Start a new session.",
                    correlation_id=message.metadata.correlation_id,
                )
            self._session_store.extend_ttl(session_id)
        else:
            session_id = self._session_store.create()

        self._logger.info(
            "message_received",
            payload_keys=list(message.payload.keys()),
            session_id=session_id,
        )

        # Route to response (include session_id so client can store or confirm)
        return await self._router.route(
            message_type=message.type,
            payload=message.payload,
            correlation_id=message.metadata.correlation_id,
            session_id=session_id,
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

    async def _handle_a2a_request(
        self,
        a2a_request: A2ASendMessageRequest,
        connection_id: str | None = None,
    ) -> UIResponse | A2AErrorResponse | None:
        """Handle A2A agent/sendMessage: extract query/ids, session get/create/extend, call A2A handler or forward to orchestrator."""
        query_text, request_id, session_id, conversation_id, cp_gutc_id, referrer, is_first_chat = extract_a2a_ids_and_query(
            a2a_request
        )
        response_id = str(a2a_request.id) if a2a_request.id is not None else None

        if not query_text and not is_first_chat:
            bind_message_context(
                message_type="a2a",
                correlation_id=response_id,
                session_id=session_id,
            )
            return A2AErrorResponse(
                jsonrpc="2.0",
                error=A2AErrorDetail(
                    code=-32422,
                    message="Invalid params: expected params.message with role and parts (e.g. parts[].text).",
                ),
                id=response_id,
            )

        # Option B: resolve session from conversationId if no sessionId in request
        if not session_id and conversation_id and hasattr(self._session_store, "get_session_for_conversation"):
            resolved = self._session_store.get_session_for_conversation(conversation_id)
            if resolved and self._session_store.get(resolved) is not None:
                session_id = resolved
                self._session_store.extend_ttl(session_id)
                self._logger.debug("session_resolved_from_conversation", conversation_id=conversation_id, session_id=session_id)

        if session_id:
            if self._session_store.get(session_id) is None:
                bind_message_context(
                    message_type="a2a",
                    correlation_id=str(response_id) if response_id is not None else None,
                    session_id=session_id,
                )
                self._logger.info("session_expired_or_unknown", session_id=session_id)
                return A2AErrorResponse(
                    jsonrpc="2.0",
                    error=A2AErrorDetail(
                        code=-32404,
                        message="Session expired or not found.",
                    ),
                    id=response_id,
                )
            self._session_store.extend_ttl(session_id)
        else:
            session_id = self._session_store.create()

        # Store conversation -> session mapping when using Redis (one session, many conversations)
        if conversation_id and hasattr(self._session_store, "set_conversation_session"):
            self._session_store.set_conversation_session(conversation_id, session_id)

        # First chat: return welcome message (UI replaces {user_name})
        if is_first_chat:
            bind_message_context(
                message_type="a2a",
                correlation_id=response_id,
                session_id=session_id,
            )
            self._logger.info("a2a_first_chat_welcome", session_id=session_id)
            return self._a2a_handler.build_welcome_response(
                session_id=session_id,
                request_id=response_id,
                context_id=conversation_id,
                cp_gutc_id=cp_gutc_id,
                referrer=referrer,
            )

        # Async flow: forward to orchestrator and return accepted immediately
        if (
            self._settings
            and self._settings.async_flow_enabled
            and self._settings.agent_base_url
            and connection_id
            and self._correlation_store is not None
            and self._agent_client is not None
        ):
            request_id_str = str(response_id) if response_id is not None else str(uuid.uuid4())
            self._correlation_store.set(
                request_id=request_id_str,
                connection_id=connection_id,
                session_id=session_id,
                context_id=None,
                conversation_id=conversation_id,
                cp_gutc_id=cp_gutc_id,
                referrer=referrer,
                query_text=query_text,
            )
            message_payload = {
                "role": "user",
                "parts": [{"kind": "text", "text": query_text}],
            }
            ok = await self._agent_client.send_async(
                message=message_payload,
                request_id=request_id_str,
                session_id=session_id,
                context_id=conversation_id,
                cp_gutc_id=cp_gutc_id,
                referrer=referrer,
            )
            self._logger.info(
                "a2a_request_forwarded_async",
                request_id=request_id_str,
                connection_id=connection_id,
                agent_accepted=ok,
            )
            return None

        bind_message_context(
            message_type="a2a",
            correlation_id=str(response_id) if response_id is not None else None,
            session_id=session_id,
        )
        self._logger.info(
            "a2a_request_handled",
            query_preview=query_text[:80],
            session_id=session_id,
            has_conversation_id=bool(conversation_id),
        )
        return await self._a2a_handler.handle_a2a_request(
            query=query_text,
            session_id=session_id,
            request_id=str(request_id) if request_id else None,
            conversation_id=conversation_id,
            cp_gutc_id=cp_gutc_id,
            referrer=referrer,
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
    ) -> OutgoingResponse | UIResponse | A2AErrorResponse | None:
        """
        Handle a message with additional connection context.

        Returns:
            OutgoingResponse for legacy JSON; A2AResponse or A2AErrorResponse for A2A.
        """
        # Bind connection context
        self._logger = self._logger.bind(
            connection_id=connection_id,
            subprotocol=subprotocol,
        )
        
        return await self.handle(raw_message, connection_id=connection_id)
