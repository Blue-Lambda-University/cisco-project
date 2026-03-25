"""Handles incoming WebSocket messages with validation and routing."""

import json
import uuid
from typing import Any, Callable, Awaitable

import structlog
from pydantic import ValidationError

from app.config import Settings
from app.core.correlation_store import CorrelationStore, PendingAsyncRequest, RedisCorrelationStore
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
from app.services.a2a_handler import A2AHandler
from app.services.agent_client import AgentClient


class MessageHandler:
    """
    Handles incoming WebSocket messages.
    
    Responsibilities:
    - Parse and validate incoming JSON messages
    - Handle plain text queries via A2A handler
    - Validate message structure and payload
    - Route messages to response generation
    - Generate appropriate error responses
    - Forward A2A requests to orchestrator (async flow)
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
        send_fn: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutgoingResponse | UIResponse | A2AErrorResponse | None:
        """
        Handle a raw WebSocket message.
        
        Supports both JSON messages (existing flow) and plain text queries (A2A flow).
        
        Args:
            raw_message: The raw message string from the WebSocket.
            connection_id: WebSocket connection identifier (needed for correlation store).
            send_fn: Callback to push intermediate streaming frames to the client.
            
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
            return await self._handle_a2a_request(
                a2a_request, connection_id=connection_id, send_fn=send_fn,
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
            if await self._session_store.get(session_id) is None:
                self._logger.info("session_expired_or_unknown", session_id=session_id)
                return self._router.create_error_response(
                    code=ErrorCode.SESSION_EXPIRED,
                    message="Session expired or not found. Start a new session.",
                    correlation_id=message.metadata.correlation_id,
                )
            await self._session_store.extend_ttl(session_id)
        else:
            session_id = await self._session_store.create()

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
        send_fn: Callable[[str], Awaitable[None]] | None = None,
    ) -> UIResponse | A2AErrorResponse | None:
        """Handle A2A agent/sendMessage: extract query/ids, session get/create/extend, call A2A handler."""
        extracted = extract_a2a_ids_and_query(a2a_request)
        query_text = extracted.query_text
        request_id = extracted.request_id
        session_id = extracted.session_id
        conversation_id = extracted.conversation_id
        cp_gutc_id = extracted.cp_gutc_id or ""
        referrer = extracted.referrer or ""
        is_first_chat = extracted.is_first_chat
        message_id = extracted.message_id or str(uuid.uuid4())
        user_id = extracted.user_id
        email = extracted.email
        response_id = a2a_request.id if a2a_request.id is not None else None

        # First chat → return welcome message immediately (no orchestrator call)
        if is_first_chat:
            if not session_id:
                session_id = await self._session_store.create()
            if conversation_id:
                await self._session_store.set_conversation_session(conversation_id, session_id)
            bind_message_context(
                message_type="a2a",
                correlation_id=str(response_id) if response_id is not None else None,
                session_id=session_id,
            )
            self._logger.info(
                "first_chat_welcome",
                session_id=session_id,
                conversation_id=conversation_id,
            )
            return self._a2a_handler.build_welcome_response(
                session_id=session_id,
                request_id=response_id,
                context_id=conversation_id,
                cp_gutc_id=cp_gutc_id,
                referrer=referrer,
            )

        if not query_text:
            bind_message_context(
                message_type="a2a",
                correlation_id=str(response_id) if response_id is not None else None,
                session_id=session_id,
            )
            return A2AErrorResponse(
                jsonrpc="2.0",
                error=A2AErrorDetail(
                    code=-32602,
                    message="Missing or empty query in params.message.parts",
                ),
                id=response_id,
            )

        if session_id:
            if await self._session_store.get(session_id) is None:
                bind_message_context(
                    message_type="a2a",
                    correlation_id=str(response_id) if response_id is not None else None,
                    session_id=session_id,
                )
                self._logger.info("session_expired_or_unknown", session_id=session_id)
                return A2AErrorResponse(
                    jsonrpc="2.0",
                    error=A2AErrorDetail(
                        code=-32000,
                        message="Session expired or not found. Start a new session.",
                    ),
                    id=response_id,
                )
            await self._session_store.extend_ttl(session_id)
        else:
            session_id = await self._session_store.create()

        bind_message_context(
            message_type="a2a",
            correlation_id=str(response_id) if response_id is not None else None,
            session_id=session_id,
        )

        # ── Streaming flow: POST to orchestrator, read SSE stream, push to WS ──
        if (
            self._settings
            and self._settings.async_flow_enabled
            and self._settings.agent_base_url
            and connection_id
            and self._correlation_store is not None
            and self._agent_client is not None
        ):
            request_id_str = str(response_id) if response_id is not None else str(uuid.uuid4())

            await self._correlation_store.set(
                request_id_str,
                PendingAsyncRequest(
                    connection_id=connection_id,
                    session_id=session_id or "",
                    context_id=conversation_id or "",
                    conversation_id=conversation_id or "",
                    cp_gutc_id=cp_gutc_id,
                    referrer=referrer,
                    query_text=query_text,
                ),
            )

            accumulated_text = ""
            got_content = False

            async for event in self._agent_client.send_streaming(
                query_text=query_text,
                request_id=request_id_str,
                session_id=session_id,
                conversation_id=conversation_id,
                message_id=message_id,
                cp_gutc_id=cp_gutc_id,
                referrer=referrer,
                user_id=user_id,
                email=email,
            ):
                text, state, is_final = self._a2a_handler.extract_text_from_sse_event(event)
                if text and not (is_final and got_content):
                    accumulated_text += text
                    got_content = True

            if got_content:
                final_resp = self._a2a_handler.build_a2a_response_from_content(
                    content=accumulated_text,
                    session_id=session_id,
                    request_id=request_id_str,
                    context_id=conversation_id,
                    conversation_id=conversation_id,
                    cp_gutc_id=cp_gutc_id,
                    referrer=referrer,
                    query_text=query_text,
                )
                if send_fn:
                    await send_fn(final_resp.model_dump_json(by_alias=True))
                    return None
                return final_resp

            self._logger.warning(
                "streaming_no_content_received",
                request_id=request_id_str,
            )
            return None

        # ── Canned / local response ──
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
        send_fn: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutgoingResponse | UIResponse | A2AErrorResponse | None:
        """
        Handle a message with additional connection context.

        Returns:
            OutgoingResponse for legacy JSON; A2AResponse or A2AErrorResponse for A2A;
            None when the request was forwarded to the orchestrator (streaming flow).
        """
        self._logger = self._logger.bind(
            connection_id=connection_id,
            subprotocol=subprotocol,
        )

        return await self.handle(
            raw_message, connection_id=connection_id, send_fn=send_fn,
        )
