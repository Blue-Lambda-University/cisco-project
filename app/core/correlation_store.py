"""In-memory store for webhook correlation: requestId -> (connection_id, metadata).

Used when we forward a request to the orchestrator: we store the connection_id and
metadata so that when the orchestrator calls our webhook with the same requestId,
we can send the response to the correct WebSocket.
"""

from dataclasses import dataclass


@dataclass
class PendingAsyncRequest:
    """Context stored for a request forwarded to the orchestrator."""

    connection_id: str
    session_id: str | None
    context_id: str | None
    conversation_id: str | None
    cp_gutc_id: str | None
    referrer: str | None
    query_text: str | None = None


class CorrelationStore:
    """
    In-memory mapping of requestId -> PendingAsyncRequest.
    One-time use: get_and_remove consumes the entry.
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingAsyncRequest] = {}

    def set(
        self,
        request_id: str,
        connection_id: str,
        session_id: str | None = None,
        context_id: str | None = None,
        conversation_id: str | None = None,
        cp_gutc_id: str | None = None,
        referrer: str | None = None,
        query_text: str | None = None,
    ) -> None:
        """Store context for a pending async request, keyed by requestId."""
        self._pending[request_id] = PendingAsyncRequest(
            connection_id=connection_id,
            session_id=session_id,
            context_id=context_id,
            conversation_id=conversation_id,
            cp_gutc_id=cp_gutc_id,
            referrer=referrer,
            query_text=query_text,
        )

    def get_and_remove(self, request_id: str) -> PendingAsyncRequest | None:
        """Return and remove the pending request for this requestId, or None."""
        return self._pending.pop(request_id, None)
