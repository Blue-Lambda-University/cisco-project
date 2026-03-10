"""Client for forwarding A2A requests to the orchestrator (async flow)."""

from typing import Any

import httpx

from app.logging.setup import get_logger
from app.models.webhook_requests import WebhookOutgoingBody

logger = get_logger()


class AgentClient:
    """
    Forwards user message to the orchestrator with a webhook URL for the response.
    The orchestrator is expected to POST the result to the webhook_url when done.
    """

    def __init__(self, agent_base_url: str, timeout_seconds: float = 30.0) -> None:
        self._base_url = agent_base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._logger = logger.bind(component="agent_client")

    async def send_async(
        self,
        webhook_url: str,
        message: dict[str, Any],
        request_id: str | None = None,
        session_id: str | None = None,
        context_id: str | None = None,
        cp_gutc_id: str | None = None,
        referrer: str | None = None,
    ) -> bool:
        """
        POST the request to the orchestrator with the webhook URL.
        The requestId is included in the payload so the orchestrator echoes it back.
        Returns True if the orchestrator accepted the request (2xx), False otherwise.
        """
        body = WebhookOutgoingBody(
            webhook_url=webhook_url,
            message=message,
            request_id=request_id,
            session_id=session_id,
            context_id=context_id,
            cp_gutc_id=cp_gutc_id,
            referrer=referrer,
        )
        payload = body.model_dump(by_alias=True, exclude_none=True)
        url = f"{self._base_url}/async/request"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload)
            if resp.is_success:
                self._logger.info(
                    "agent_request_sent",
                    request_id=request_id,
                    status_code=resp.status_code,
                )
                return True
            self._logger.warning(
                "agent_request_failed",
                request_id=request_id,
                status_code=resp.status_code,
                body=resp.text[:200],
            )
            return False
        except Exception as e:
            self._logger.exception("agent_request_error", request_id=request_id, error=str(e))
            return False
