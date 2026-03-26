"""Pydantic models for A2A (agent/sendMessage) JSON-RPC 2.0 requests."""

from typing import Any

from pydantic import BaseModel, Field


class MessagePart(BaseModel):
    """A single part in params.message.parts (text or other content)."""

    kind: str = Field(default="text", description="Part type, e.g. 'text'")
    text: str = Field(default="", description="Text content when kind is 'text'")


class A2AMessage(BaseModel):
    """Message object inside params (A2A Message)."""

    role: str = Field(default="user", description="Sender role, e.g. 'user'")
    parts: list[MessagePart] = Field(default_factory=list, description="Content parts")
    message_id: str | None = Field(default=None, alias="messageId", description="Client message id")
    context_id: str | None = Field(default=None, alias="contextId", description="Conversation/context id for follow-up")

    model_config = {"populate_by_name": True}


class A2ARequestMetadata(BaseModel):
    """Metadata inside params (sessionId, conversationId, CP_GUTC_Id, referrer, requestType, userId, email)."""

    session_id: str | None = Field(default=None, alias="sessionId")
    conversation_id: str | None = Field(default=None, alias="conversationId")
    cp_gutc_id: str | None = Field(default=None, alias="CP_GUTC_Id")
    referrer: str | None = Field(default=None)
    request_type: str | None = Field(default=None, alias="requestType")
    user_id: str | None = Field(default=None, alias="userId")
    email: str | None = Field(default=None)

    model_config = {"populate_by_name": True, "extra": "ignore"}


class A2ASendMessageParams(BaseModel):
    """Params for agent/sendMessage (message + metadata)."""

    message: A2AMessage = Field(..., description="User message")
    metadata: A2ARequestMetadata | None = Field(default=None, description="Optional metadata")

    model_config = {"populate_by_name": True}


class A2ASendMessageRequest(BaseModel):
    """Full JSON-RPC 2.0 request for agent/sendMessage (method optional; UI may omit)."""

    jsonrpc: str = Field(default="2.0", description="JSON-RPC version")
    method: str | None = Field(default=None, description="Optional; e.g. 'agent/sendMessage'. UI may omit.")
    params: A2ASendMessageParams = Field(..., description="Request params")
    id: str | int | None = Field(default=None, description="Request id (JSON-RPC; echoed in response as id only)")

    model_config = {"populate_by_name": True}


def parse_a2a_request(data: dict[str, Any]) -> A2ASendMessageRequest | None:
    """
    Parse raw JSON dict into A2ASendMessageRequest if it looks like A2A.

    Returns None if data is not a valid A2A sendMessage request.
    """
    if data.get("jsonrpc") != "2.0":
        return None
    method = data.get("method")
    if method is not None and method not in ("message/stream", "message/send", "agent/sendMessage", "SendMessage"):
        return None
    params = data.get("params")
    if not isinstance(params, dict) or "message" not in params:
        return None
    try:
        return A2ASendMessageRequest.model_validate(data)
    except Exception:
        return None


class A2AExtracted:
    """Extracted fields from an A2A request."""

    __slots__ = (
        "query_text", "request_id", "session_id", "conversation_id",
        "cp_gutc_id", "referrer", "request_type", "user_id", "email", "message_id",
    )

    def __init__(
        self,
        query_text: str = "",
        request_id: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
        cp_gutc_id: str | None = None,
        referrer: str | None = None,
        request_type: str | None = None,
        user_id: str | None = None,
        email: str | None = None,
        message_id: str | None = None,
    ) -> None:
        self.query_text = query_text
        self.request_id = request_id
        self.session_id = session_id
        self.conversation_id = conversation_id
        self.cp_gutc_id = cp_gutc_id
        self.referrer = referrer
        self.request_type = request_type
        self.user_id = user_id
        self.email = email
        self.message_id = message_id


def extract_a2a_ids_and_query(request: A2ASendMessageRequest) -> A2AExtracted:
    """Extract query text, ids, and metadata from a parsed A2A request."""
    result = A2AExtracted(
        request_id=str(request.id) if request.id is not None else None,
    )

    if request.params.metadata:
        meta = request.params.metadata
        result.session_id = (meta.session_id or "").strip() or None
        result.conversation_id = (meta.conversation_id or "").strip() or None
        result.cp_gutc_id = (meta.cp_gutc_id or "").strip() or None
        result.referrer = (meta.referrer or "").strip() or None
        result.request_type = (meta.request_type or "").strip() or None
        result.user_id = (meta.user_id or "").strip() or None
        result.email = (meta.email or "").strip() or None

    if not result.conversation_id and request.params.message.context_id:
        result.conversation_id = (request.params.message.context_id or "").strip() or None

    result.message_id = (request.params.message.message_id or "").strip() or None if request.params.message.message_id else None

    query_parts: list[str] = []
    for part in request.params.message.parts or []:
        if getattr(part, "text", None):
            query_parts.append(part.text.strip())
    result.query_text = " ".join(query_parts).strip() if query_parts else ""

    return result
