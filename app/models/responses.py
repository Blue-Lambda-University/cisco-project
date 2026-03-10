"""Pydantic models for outgoing WebSocket responses."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import ErrorCode, ResponseType


# =============================================================================
# UI Response Wrapper (top-level contract between UI and backend)
# =============================================================================


class UIResponse(BaseModel):
    """
    Top-level response sent to the UI over WebSocket.

    Wraps the A2A JSON-RPC response inside ``a2aResponse`` and promotes
    convenience fields (``response``, ``contextId``, ``conversationId``)
    to the top level so the UI does not need to dig into nested structures.
    """

    context_id: str = Field(default="", alias="contextId")
    response: str = Field(default="")
    conversation_id: str = Field(default="", alias="conversationId")
    a2a_response: dict[str, Any] = Field(default_factory=dict, alias="a2aResponse")
    error: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="success")

    model_config = {"populate_by_name": True}


# =============================================================================
# A2A (Agent-to-Agent) JSON-RPC 2.0 Response Models
# =============================================================================


class A2AArtifactPart(BaseModel):
    """A single part within an A2A artifact."""

    kind: str = Field(
        default="text",
        description="The type of content (e.g., 'text', 'image', 'code')"
    )
    text: str = Field(
        ...,
        description="The text content of this part"
    )


class A2AArtifact(BaseModel):
    """An artifact in the A2A response containing response content."""

    artifactId: str = Field(
        ...,
        alias="artifactId",
        description="Unique identifier for this artifact"
    )
    name: str = Field(
        default="Response from orchestration",
        description="Human-readable name for this artifact"
    )
    parts: list[A2AArtifactPart] = Field(
        default_factory=list,
        description="List of content parts in this artifact"
    )

    model_config = {
        "populate_by_name": True,
    }


class A2ATaskStatus(BaseModel):
    """Status information for an A2A task."""

    state: str = Field(
        default="completed",
        description="Current state of the task (e.g., 'completed', 'in_progress', 'failed')"
    )
    message: str | None = Field(
        default=None,
        description="Optional status message"
    )
    timestamp: str = Field(
        ...,
        description="ISO 8601 timestamp of the status update"
    )


class A2AResultMetadata(BaseModel):
    """Metadata inside result (timestamp, sessionId, conversationId, CP_GUTC_Id, referrer)."""

    timestamp: str | None = Field(
        default=None,
        description="ISO 8601 timestamp when the response was generated",
    )
    sessionId: str | None = Field(
        default=None,
        alias="sessionId",
        description="Session ID for the client to store and send on subsequent requests",
    )
    conversationId: str | None = Field(
        default=None,
        alias="conversationId",
        description="Conversation/context ID for follow-up turns (same as result.contextId)",
    )
    cp_gutc_id: str | None = Field(
        default=None,
        alias="CP_GUTC_Id",
        description="CP GUTC Id from UI (echoed back from webhook/orchestrator)",
    )
    referrer: str | None = Field(
        default=None,
        description="Referrer from UI (echoed back from webhook/orchestrator)",
    )

    model_config = {"populate_by_name": True}


class A2ATaskResult(BaseModel):
    """The result object within an A2A JSON-RPC response."""

    kind: Literal["task"] = Field(
        default="task",
        description="The kind of result (always 'task' for task responses)"
    )
    id: str = Field(
        ...,
        description="Unique identifier for this task"
    )
    contextId: str | None = Field(
        default=None,
        alias="contextId",
        description="Context/conversation id (echoed from request; server never creates)",
    )
    status: A2ATaskStatus = Field(
        ...,
        description="Status information for the task"
    )
    artifacts: list[A2AArtifact] = Field(
        default_factory=list,
        description="List of artifacts produced by the task"
    )
    role: str = Field(
        default="assistant",
        description="Role of the responder (e.g. 'assistant' for agent output)",
    )
    metadata: A2AResultMetadata | None = Field(
        default=None,
        description="Request/response metadata (timestamp, sessionId, conversationId)",
    )

    model_config = {
        "populate_by_name": True,
    }


class A2AErrorDetail(BaseModel):
    """JSON-RPC 2.0 error object for A2A."""

    code: int = Field(..., description="Error code (e.g. -32602 invalid params, -32000 server/session)")
    message: str = Field(..., description="Human-readable error message")


class A2AErrorResponse(BaseModel):
    """A2A JSON-RPC 2.0 error response."""

    jsonrpc: Literal["2.0"] = Field(default="2.0", description="JSON-RPC version")
    error: A2AErrorDetail = Field(..., description="Error details")
    id: str | int | None = Field(default=None, description="Request id (echoed from request)")


class AsyncAcceptedResponse(BaseModel):
    """
    Returned when the request was forwarded to the orchestrator.
    The UI receives an in-progress style response; the full result is delivered via webhook.
    """

    request_id: str = Field(..., description="Request id used to correlate the webhook response")

    def to_a2a_in_progress_json(self) -> str:
        """Serialize as an A2A-style in_progress result for the WebSocket."""
        import json
        payload = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "result": {
                "kind": "task",
                "id": self.request_id,
                "status": {"state": "in_progress", "message": "Forwarded to agent; response will follow via webhook."},
            },
        }
        return json.dumps(payload)


class A2AResponse(BaseModel):
    """
    A2A (Agent-to-Agent) JSON-RPC 2.0 Response.
    
    This is the standard response format for A2A protocol communications,
    following the JSON-RPC 2.0 specification with A2A-specific result structure.
    """

    jsonrpc: Literal["2.0"] = Field(
        default="2.0",
        description="JSON-RPC protocol version"
    )
    id: str | None = Field(
        default=None,
        description="Request identifier (echoed from request)",
    )
    result: A2ATaskResult = Field(
        ...,
        description="The task result object"
    )

    model_config = {
        "populate_by_name": True,
    }


# =============================================================================
# Standard WebSocket Response Models
# =============================================================================


class ResponseMetadata(BaseModel):
    """
    Metadata for outgoing responses.
    
    Provides correlation with requests and timing information
    for monitoring and debugging.
    """

    correlation_id: str | None = Field(
        default=None,
        description="Correlation ID from the original request"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Response timestamp"
    )
    latency_ms: int | None = Field(
        default=None,
        ge=0,
        description="Simulated latency in milliseconds"
    )
    session_id: str | None = Field(
        default=None,
        description="Session ID (included so client can store or confirm)"
    )


class AssistantResponsePayload(BaseModel):
    """Payload for assistant responses to user queries."""

    message: str = Field(
        ...,
        description="Assistant's response message"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score of the response"
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Sources used for the response"
    )
    suggested_actions: list[str] = Field(
        default_factory=list,
        description="Suggested follow-up actions"
    )


class PongPayload(BaseModel):
    """Payload for pong responses."""

    client_timestamp: datetime = Field(
        ...,
        description="Original client timestamp from ping"
    )
    server_timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Server timestamp when pong is sent"
    )


class HistoryMessage(BaseModel):
    """Single message in conversation history."""

    role: str = Field(
        ...,
        description="Message role (user, assistant, system)"
    )
    content: str = Field(
        ...,
        description="Message content"
    )
    timestamp: datetime = Field(
        ...,
        description="When the message was sent"
    )


class HistoryResponsePayload(BaseModel):
    """Payload for history responses."""

    messages: list[HistoryMessage] = Field(
        default_factory=list,
        description="List of history messages"
    )
    total_count: int = Field(
        ...,
        ge=0,
        description="Total number of messages in history"
    )
    has_more: bool = Field(
        ...,
        description="Whether more messages are available"
    )


class OrchestrationResultPayload(BaseModel):
    """Payload for orchestration results."""

    action: str = Field(
        ...,
        description="The action that was performed"
    )
    status: str = Field(
        ...,
        description="Status of the orchestration (completed, failed, pending)"
    )
    result: dict[str, Any] = Field(
        default_factory=dict,
        description="Result data from the orchestration"
    )
    agents_invoked: list[str] = Field(
        default_factory=list,
        description="List of agents that were invoked"
    )


class SubscriptionAckPayload(BaseModel):
    """Payload for subscription acknowledgment."""

    topics: list[str] = Field(
        ...,
        description="Topics that were subscribed/unsubscribed"
    )
    status: str = Field(
        ...,
        description="Subscription status (active, removed)"
    )


class ErrorPayload(BaseModel):
    """Payload for error responses."""

    code: ErrorCode = Field(
        ...,
        description="Machine-readable error code"
    )
    message: str = Field(
        ...,
        description="Human-readable error message"
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Additional error details"
    )


class OutgoingResponse(BaseModel):
    """
    Base outgoing WebSocket response.
    
    All responses from the server conform to this structure with a type,
    payload, and metadata.
    """

    type: ResponseType = Field(
        ...,
        description="Response type identifier"
    )
    payload: dict[str, Any] = Field(
        ...,
        description="Response payload"
    )
    metadata: ResponseMetadata = Field(
        default_factory=ResponseMetadata,
        description="Response metadata"
    )

    model_config = {
        "use_enum_values": True,
    }
