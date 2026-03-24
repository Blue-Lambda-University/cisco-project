"""Webhook outcome types and status-to-HTTP mapping for POST /api/webhooks/async-response.

Kept in a lightweight module (no langgraph/app stack) so unit tests can import
and assert the contract without loading the full application.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# HTTP status codes for async webhook outcomes (tested in tests/test_unit.py)
WEBHOOK_STATUS_TO_HTTP = {
    "forwarded": 200,
    "buffered": 202,
    "undeliverable": 422,
    "delivery_failed": 502,
    "unavailable": 503,
}


class AsyncWebhookAcknowledgement(BaseModel):
    """Acknowledgement returned after receiving and processing the webhook."""
    status: str = Field(
        ...,
        description="forwarded | buffered | undeliverable | delivery_failed | unavailable",
    )
    received: bool = Field(
        ...,
        description="True only if the event was delivered downstream",
    )
    message: str = Field(..., description="Human-readable detail")
    id: Optional[str] = Field(default=None, description="Server-side tracking id")
