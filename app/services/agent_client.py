"""Client for forwarding A2A requests to the orchestrator (async flow)."""

import httpx

from app.logging.setup import get_logger
from app.models.webhook_requests import (
    OutgoingConfiguration,
    OutgoingMessage,
    OutgoingMessageMetadata,
    OutgoingParams,
    WebhookOutgoingBody,
)

logger = get_logger()


class AgentClient:
    """
    Forwards user message to the orchestrator via POST /a2a/.
    The orchestrator is expected to POST the result back to our webhook when done.
    """

    def __init__(self, agent_base_url: str, timeout_seconds: float = 30.0) -> None:
        self._base_url = agent_base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._logger = logger.bind(component="agent_client")

    async def send_async(
        self,
        query_text: str,
        request_id: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
        message_id: str | None = None,
        cp_gutc_id: str | None = None,
        referrer: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        """
        Build JSON-RPC 2.0 payload and POST to the orchestrator /a2a/ endpoint.
        Returns True if the orchestrator accepted the request (2xx), False otherwise.
        """
        metadata = OutgoingMessageMetadata(
            user_id=user_id,
            conversation_id=conversation_id,
            session_id=session_id,
            request_id=request_id,
            cp_gutc_id=cp_gutc_id,
            referrer=referrer,
        )
        message = OutgoingMessage(
            role="user",
            parts=[{"kind": "text", "text": query_text}],
            message_id=message_id,
            context_id=conversation_id,
            metadata=metadata,
        )
        body = WebhookOutgoingBody(
            id=request_id,
            params=OutgoingParams(
                message=message,
                configuration=OutgoingConfiguration(),
            ),
        )
        payload = body.model_dump(by_alias=True, exclude_none=True)
        url = f"{self._base_url}/a2a/"

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
