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
    """Metadata inside params (requestId, sessionId, conversationId, email, CP_GUTC_Id, referrer)."""

    email: str | None = Field(default=None, description="User email")
    request_id: str | None = Field(default=None, alias="requestId", description="Request id")
    session_id: str | None = Field(default=None, alias="sessionId", description="Session id for TTL")
    conversation_id: str | None = Field(default=None, alias="conversationId", description="Conversation/context id")
    cp_gutc_id: str | None = Field(default=None, alias="CP_GUTC_Id", description="CP GUTC Id from UI (passed to webhook/orchestrator)")
    referrer: str | None = Field(default=None, description="Referrer from UI (passed to webhook/orchestrator)")

    model_config = {"populate_by_name": True, "extra": "ignore"}


class A2ASendMessageParams(BaseModel):
    """Params for agent/sendMessage (message + metadata)."""

    message: A2AMessage = Field(..., description="User message")
    metadata: A2ARequestMetadata | None = Field(default=None, description="Optional metadata")

    model_config = {"populate_by_name": True}


class A2ASendMessageRequest(BaseModel):
    """Full JSON-RPC 2.0 request for agent/sendMessage."""

    jsonrpc: str = Field(default="2.0", description="JSON-RPC version")
    method: str = Field(..., description="Method name, e.g. 'agent/sendMessage'")
    params: A2ASendMessageParams = Field(..., description="Request params")
    id: str | int | None = Field(default=None, description="Request id (JSON-RPC; echoed in response)")
    request_id: str | int | None = Field(
        default=None,
        alias="requestId",
        description="Request id at top level (same as id; preferred for extraction)",
    )

    model_config = {"populate_by_name": True}


def parse_a2a_request(data: dict[str, Any]) -> A2ASendMessageRequest | None:
    """
    Parse raw JSON dict into A2ASendMessageRequest if it looks like A2A.

    Returns None if data is not a valid A2A sendMessage request.
    """
    if data.get("jsonrpc") != "2.0":
        return None
    method = data.get("method")
    if method not in ("agent/sendMessage", "SendMessage"):
        return None
    params = data.get("params")
    if not isinstance(params, dict) or "message" not in params:
        return None
    try:
        return A2ASendMessageRequest.model_validate(data)
    except Exception:
        return None


def extract_a2a_ids_and_query(
    request: A2ASendMessageRequest,
) -> tuple[str, str | None, str | None, str | None, str | None, str | None]:
    """
    Extract query text and ids from a parsed A2A request.

    Returns:
        (query_text, request_id, session_id, conversation_id, cp_gutc_id, referrer)
    """
    request_id = None
    if getattr(request, "request_id", None) is not None:
        request_id = str(request.request_id)
    elif request.id is not None:
        request_id = str(request.id)
    session_id: str | None = None
    conversation_id: str | None = None
    cp_gutc_id: str | None = None
    referrer: str | None = None

    if request.params.metadata:
        meta = request.params.metadata
        if request_id is None and meta.request_id:
            request_id = str(meta.request_id)
        if meta.session_id:
            session_id = (meta.session_id or "").strip() or None
        if meta.conversation_id:
            conversation_id = (meta.conversation_id or "").strip() or None
        if meta.cp_gutc_id:
            cp_gutc_id = (meta.cp_gutc_id or "").strip() or None
        if meta.referrer:
            referrer = (meta.referrer or "").strip() or None

    if not conversation_id and request.params.message.context_id:
        conversation_id = (request.params.message.context_id or "").strip() or None

    query_parts: list[str] = []
    for part in request.params.message.parts or []:
        if getattr(part, "text", None):
            query_parts.append(part.text.strip())
    query_text = " ".join(query_parts).strip() if query_parts else ""

    return query_text, request_id, session_id, conversation_id, cp_gutc_id, referrer
