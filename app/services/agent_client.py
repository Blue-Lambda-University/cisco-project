"""Client for forwarding A2A requests to the orchestrator (async flow)."""

import json
from typing import AsyncIterator

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

    @staticmethod
    def _build_forwarded_headers(
        user_token: str, email_address: str, ccoid: str = "",
    ) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if user_token:
            headers["X-User-Token"] = user_token
        if email_address:
            headers["X-User-Email"] = email_address
        if ccoid:
            headers["X-User-ID"] = ccoid
        return headers

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
        email: str | None = None,
        user_token: str = "",
        email_address: str = "",
        ccoid: str = "",
    ) -> bool:
        """
        Build JSON-RPC 2.0 payload and POST to the orchestrator /a2a/ endpoint.
        Returns True if the orchestrator accepted the request (2xx), False otherwise.
        """
        metadata = OutgoingMessageMetadata(
            user_id=user_id,
            email=email,
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
        headers = self._build_forwarded_headers(user_token, email_address, ccoid=ccoid)

        self._logger.info(
            "forwarding_headers_to_orchestrator",
            request_id=request_id,
            headers_keys=list(headers.keys()),
            email_address=headers.get("X-User-Email", ""),
            ccoid=headers.get("X-User-ID", ""),
            user_token_present="X-User-Token" in headers,
        )

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
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

    async def send_streaming(
        self,
        query_text: str,
        request_id: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
        message_id: str | None = None,
        cp_gutc_id: str | None = None,
        referrer: str | None = None,
        user_id: str | None = None,
        email: str | None = None,
        user_token: str = "",
        email_address: str = "",
        ccoid: str = "",
    ) -> AsyncIterator[dict]:
        """POST to orchestrator and yield parsed SSE events as they arrive."""
        metadata = OutgoingMessageMetadata(
            user_id=user_id,
            email=email,
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
        forwarded_headers = self._build_forwarded_headers(user_token, email_address, ccoid=ccoid)

        self._logger.info(
            "forwarding_headers_to_orchestrator",
            request_id=request_id,
            headers_keys=list(forwarded_headers.keys()),
            email_address=forwarded_headers.get("X-User-Email", ""),
            ccoid=forwarded_headers.get("X-User-ID", ""),
            user_token_present="X-User-Token" in forwarded_headers,
        )

        timeout = httpx.Timeout(30.0, read=120.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=forwarded_headers) as response:
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if data_str:
                                try:
                                    yield json.loads(data_str)
                                except json.JSONDecodeError:
                                    pass
        except Exception as e:
            self._logger.exception(
                "streaming_request_error", request_id=request_id, error=str(e),
            )
