"""Pydantic models for messages and responses."""

from app.models.enums import ErrorCode, MessageType, ResponseType, WebSocketSubprotocol
from app.models.messages import (
    GetHistoryPayload,
    IncomingMessage,
    MessageMetadata,
    OrchestratePayload,
    PingPayload,
    SubscribePayload,
    UnsubscribePayload,
    UserQueryPayload,
)
from app.models.responses import (
    AssistantResponsePayload,
    ErrorPayload,
    HistoryMessage,
    HistoryResponsePayload,
    OrchestrationResultPayload,
    OutgoingResponse,
    PongPayload,
    ResponseMetadata,
)

__all__ = [
    # Enums
    "MessageType",
    "ResponseType",
    "ErrorCode",
    "WebSocketSubprotocol",
    # Incoming messages
    "MessageMetadata",
    "UserQueryPayload",
    "PingPayload",
    "GetHistoryPayload",
    "OrchestratePayload",
    "SubscribePayload",
    "UnsubscribePayload",
    "IncomingMessage",
    # Outgoing responses
    "ResponseMetadata",
    "AssistantResponsePayload",
    "PongPayload",
    "HistoryMessage",
    "HistoryResponsePayload",
    "OrchestrationResultPayload",
    "ErrorPayload",
    "OutgoingResponse",
]
