"""Pydantic models for webhook/orchestrator request and response payloads.

Mapping:
- UI sends CP_GUTC_Id, referrer in A2A params.metadata.
- We forward them in the payload TO the orchestrator (outgoing).
- Orchestrator returns them in the payload when calling our webhook (incoming).
- We put them in result.metadata in the A2A response back to the frontend.
"""

from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Payload we SEND to the orchestrator (e.g. POST to orchestrator with webhook URL)
# -----------------------------------------------------------------------------


class WebhookOutgoingBody(BaseModel):
    """
    Payload sent to the orchestrator when forwarding a user message.
    JSON keys use camelCase to match UI (sessionId, requestId, etc.).
    """

    webhook_url: str = Field(..., alias="webhookUrl", description="Our callback URL for async response")
    correlation_id: str = Field(..., alias="correlationId", description="Id to correlate the webhook response")
    message: dict = Field(default_factory=dict, description="User message (e.g. role, parts)")
    request_id: str | None = Field(default=None, alias="requestId", description="Request id from UI (echoed in response)")
    session_id: str | None = Field(default=None, alias="sessionId", description="Session id from UI")
    context_id: str | None = Field(default=None, alias="contextId", description="Conversation/context id from UI")
    cp_gutc_id: str | None = Field(
        default=None,
        alias="CP_GUTC_Id",
        description="CP GUTC Id from UI (orchestrator echoes back in webhook)",
    )
    referrer: str | None = Field(default=None, description="Referrer from UI (orchestrator echoes back in webhook)")

    model_config = {"populate_by_name": True}


# -----------------------------------------------------------------------------
# Payload we RECEIVE from the orchestrator (POST to our webhook endpoint)
# -----------------------------------------------------------------------------


class WebhookIncomingBody(BaseModel):
    """
    Payload received from the orchestrator when they POST to our webhook.
    JSON keys use camelCase to match UI (sessionId, requestId, etc.).
    """

    correlation_id: str | None = Field(default=None, alias="correlationId", description="Correlates to the original request (or pass as query correlationId)")
    content: str | None = Field(default=None, description="Response text / content for the user")
    request_id: str | None = Field(default=None, alias="requestId", description="Request id to echo in response")
    session_id: str | None = Field(default=None, alias="sessionId", description="Session id to echo in result")
    context_id: str | None = Field(default=None, alias="contextId", description="Conversation/context id to echo in result")
    cp_gutc_id: str | None = Field(
        default=None,
        alias="CP_GUTC_Id",
        description="CP GUTC Id (from UI, echoed back from orchestrator)",
    )
    referrer: str | None = Field(default=None, description="Referrer (from UI, echoed back from orchestrator)")

    model_config = {"populate_by_name": True}
