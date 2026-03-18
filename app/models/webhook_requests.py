"""Pydantic models for webhook/orchestrator request and response payloads.

Mapping:
- UI sends CP_GUTC_Id, referrer in A2A params.metadata.
- We forward them in the payload TO the orchestrator (outgoing).
- Orchestrator echoes requestId and metadata when calling our webhook (incoming).
- We use requestId to look up the correlation store and deliver the response.
"""

from typing import Any

from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Payload we SEND to the orchestrator
# -----------------------------------------------------------------------------


class OutgoingMessageMetadata(BaseModel):
    """Metadata embedded inside params.message for the orchestrator (snake_case keys)."""

    user_id: str | None = Field(default=None)
    conversation_id: str | None = Field(default=None)
    session_id: str | None = Field(default=None)
    request_id: str | None = Field(default=None)
    cp_gutc_id: str | None = Field(default=None)
    referrer: str | None = Field(default=None)


class OutgoingMessage(BaseModel):
    """The message object inside params, with metadata nested inside."""

    role: str = Field(default="user")
    parts: list[dict] = Field(default_factory=list)
    message_id: str | None = Field(default=None, alias="messageId")
    context_id: str | None = Field(default=None, alias="contextId")
    metadata: OutgoingMessageMetadata | None = Field(default=None)

    model_config = {"populate_by_name": True}


class OutgoingConfiguration(BaseModel):
    """Configuration block sent to the orchestrator."""

    accepted_output_modes: list[str] = Field(
        default_factory=lambda: ["text"],
        alias="acceptedOutputModes",
    )

    model_config = {"populate_by_name": True}


class OutgoingParams(BaseModel):
    """params block of the JSON-RPC payload to the orchestrator."""

    message: OutgoingMessage
    configuration: OutgoingConfiguration = Field(default_factory=OutgoingConfiguration)


class WebhookOutgoingBody(BaseModel):
    """
    Full JSON-RPC 2.0 payload sent to the orchestrator (POST /a2a/).

    Structure matches what the orchestrator expects:
      { jsonrpc, id, method, params: { message: { ..., metadata: {...} }, configuration } }
    """

    jsonrpc: str = Field(default="2.0")
    id: str | None = Field(default=None)
    method: str = Field(default="message/stream")
    params: OutgoingParams

    model_config = {"populate_by_name": True}


# -----------------------------------------------------------------------------
# Payload we RECEIVE from the orchestrator (POST to our webhook endpoint)
# -----------------------------------------------------------------------------


class WebhookIncomingInner(BaseModel):
    """
    Inner payload from the orchestrator (the fields inside "body" or at root).
    The requestId is used to look up the correlation store.
    """

    request_id: str | None = Field(default=None, alias="requestId")
    content: Any = Field(default=None, description="Subagent output: string, dict with artifacts, list, or null")
    session_id: str | None = Field(default=None, alias="sessionId")
    context_id: str | None = Field(default=None, alias="contextId")
    cp_gutc_id: str | None = Field(default=None, alias="CP_GUTC_Id")
    referrer: str | None = Field(default=None)

    model_config = {"populate_by_name": True}


class WebhookIncomingBody(BaseModel):
    """
    Accepts both formats from the orchestrator:
      - Wrapped:   {"body": {"requestId": ..., "content": ..., ...}}
      - Unwrapped: {"requestId": ..., "content": ..., ...}
    """

    body: WebhookIncomingInner | None = Field(default=None)
    request_id: str | None = Field(default=None, alias="requestId")
    content: Any = Field(default=None)
    session_id: str | None = Field(default=None, alias="sessionId")
    context_id: str | None = Field(default=None, alias="contextId")
    cp_gutc_id: str | None = Field(default=None, alias="CP_GUTC_Id")
    referrer: str | None = Field(default=None)

    model_config = {"populate_by_name": True}

    def resolve(self) -> WebhookIncomingInner:
        """Return the inner payload regardless of which format was used."""
        if self.body is not None:
            return self.body
        return WebhookIncomingInner(
            request_id=self.request_id,
            content=self.content,
            session_id=self.session_id,
            context_id=self.context_id,
            cp_gutc_id=self.cp_gutc_id,
            referrer=self.referrer,
        )
