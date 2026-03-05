"""Pydantic models for incoming WebSocket messages."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import MessageType


class MessageMetadata(BaseModel):
    """
    Metadata attached to every incoming message.
    
    Provides context for request tracking, session management,
    and correlation of requests with responses.
    """

    session_id: str | None = Field(
        default=None,
        max_length=256,
        description="Client session identifier (omit or null for new session)"
    )
    correlation_id: str | None = Field(
        default=None,
        max_length=256,
        description="Request correlation ID for tracing"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Message timestamp"
    )


class UserQueryPayload(BaseModel):
    """Payload for user_query messages."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="User's query text"
    )
    context: dict[str, Any] | None = Field(
        default=None,
        description="Additional context for the query"
    )
    language: str = Field(
        default="en",
        min_length=2,
        max_length=10,
        description="Language code (e.g., 'en', 'es', 'fr')"
    )


class PingPayload(BaseModel):
    """Payload for ping messages."""

    client_timestamp: datetime = Field(
        ...,
        description="Client's timestamp when ping was sent"
    )


class GetHistoryPayload(BaseModel):
    """Payload for get_history messages."""

    limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of history items to return"
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Offset for pagination"
    )
    session_id: str | None = Field(
        default=None,
        description="Filter history by session ID"
    )


class OrchestratePayload(BaseModel):
    """Payload for orchestrate messages."""

    action: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Orchestration action to perform"
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Action parameters"
    )
    agents: list[str] = Field(
        default_factory=list,
        description="List of agents to invoke"
    )


class SubscribePayload(BaseModel):
    """Payload for subscribe messages."""

    topics: list[str] = Field(
        ...,
        min_length=1,
        description="Topics to subscribe to"
    )


class UnsubscribePayload(BaseModel):
    """Payload for unsubscribe messages."""

    topics: list[str] = Field(
        ...,
        min_length=1,
        description="Topics to unsubscribe from"
    )


class IncomingMessage(BaseModel):
    """
    Base incoming WebSocket message.
    
    All messages from clients must conform to this structure with a type,
    payload, and metadata. The payload is validated further based on the
    message type.
    """

    type: MessageType = Field(
        ...,
        description="Message type identifier"
    )
    payload: dict[str, Any] = Field(
        ...,
        description="Message payload (validated based on type)"
    )
    metadata: MessageMetadata = Field(
        ...,
        description="Message metadata"
    )

    model_config = {
        "use_enum_values": True,
    }


# Mapping of message types to their payload models for validation
PAYLOAD_MODELS: dict[MessageType, type[BaseModel]] = {
    MessageType.USER_QUERY: UserQueryPayload,
    MessageType.PING: PingPayload,
    MessageType.GET_HISTORY: GetHistoryPayload,
    MessageType.ORCHESTRATE: OrchestratePayload,
    MessageType.SUBSCRIBE: SubscribePayload,
    MessageType.UNSUBSCRIBE: UnsubscribePayload,
}
