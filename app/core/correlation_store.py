"""Correlation store: requestId -> pending async request context.

Two backends:
- CorrelationStore: in-memory (single pod)
- RedisCorrelationStore: Redis-backed (multi-pod — any pod can look up the request)

Used when we forward a request to the orchestrator: we store the connection_id and
metadata so that when the orchestrator calls our webhook with the same requestId,
we can send the response to the correct WebSocket.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Protocol

from app.logging.setup import get_logger

logger = get_logger()

REDIS_CORRELATION_KEY_PREFIX = "ws_pending_request:"
REDIS_DELIVERED_KEY_PREFIX = "ws_delivered:"
DELIVERED_CACHE_TTL_SECONDS = 120


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
    created_at: float = field(default_factory=time.monotonic)


class CorrelationStoreProtocol(Protocol):
    """Protocol shared by in-memory and Redis correlation stores."""

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
    ) -> None: ...

    def get_and_remove(self, request_id: str) -> PendingAsyncRequest | None: ...

    def mark_delivered(self, request_id: str) -> None: ...

    def was_delivered(self, request_id: str) -> bool: ...

    def get_expired(self, timeout_seconds: float) -> list[tuple[str, PendingAsyncRequest]]: ...

    def remove_by_connection(self, connection_id: str) -> list[str]: ...


# ---------------------------------------------------------------------------
# In-memory backend (single pod)
# ---------------------------------------------------------------------------


class CorrelationStore:
    """
    In-memory mapping of requestId -> PendingAsyncRequest.
    One-time use: get_and_remove consumes the entry.
    Tracks recently-delivered IDs so retried webhooks get an idempotent 200.
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingAsyncRequest] = {}
        self._delivered: dict[str, float] = {}

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

    def mark_delivered(self, request_id: str) -> None:
        """Remember that this requestId was successfully delivered."""
        self._delivered[request_id] = time.monotonic()
        self._prune_delivered()

    def was_delivered(self, request_id: str) -> bool:
        """Check whether this requestId was recently delivered."""
        self._prune_delivered()
        return request_id in self._delivered

    def _prune_delivered(self) -> None:
        cutoff = time.monotonic() - DELIVERED_CACHE_TTL_SECONDS
        self._delivered = {k: v for k, v in self._delivered.items() if v > cutoff}

    def get_expired(self, timeout_seconds: float) -> list[tuple[str, PendingAsyncRequest]]:
        """Remove and return all entries older than timeout_seconds."""
        now = time.monotonic()
        expired: list[tuple[str, PendingAsyncRequest]] = []
        to_remove: list[str] = []
        for rid, req in self._pending.items():
            if now - req.created_at > timeout_seconds:
                expired.append((rid, req))
                to_remove.append(rid)
        for rid in to_remove:
            del self._pending[rid]
        return expired

    def remove_by_connection(self, connection_id: str) -> list[str]:
        """Remove all entries for a given connection_id. Returns removed requestIds."""
        to_remove = [
            rid for rid, req in self._pending.items()
            if req.connection_id == connection_id
        ]
        for rid in to_remove:
            del self._pending[rid]
        return to_remove


# ---------------------------------------------------------------------------
# Redis backend (multi-pod)
# ---------------------------------------------------------------------------


class RedisCorrelationStore:
    """
    Redis-backed correlation store.

    Key:   ws_pending_request:{requestId}
    Value: JSON hash with connection_id, session_id, context_id, etc.
    TTL:   auto_expire_seconds (set on write, Redis auto-deletes expired entries)

    This allows any pod to look up a pending request by requestId when the
    orchestrator webhook arrives.
    """

    def __init__(self, redis_url: str, auto_expire_seconds: int = 120) -> None:
        self._redis_url = redis_url
        self._auto_expire_seconds = auto_expire_seconds
        self._client = None
        self._logger = logger.bind(component="redis_correlation_store")

    def _get_client(self):
        if self._client is None:
            import redis
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    def _key(self, request_id: str) -> str:
        return f"{REDIS_CORRELATION_KEY_PREFIX}{request_id}"

    def _serialize(self, req: PendingAsyncRequest) -> str:
        return json.dumps({
            "connection_id": req.connection_id,
            "session_id": req.session_id,
            "context_id": req.context_id,
            "conversation_id": req.conversation_id,
            "cp_gutc_id": req.cp_gutc_id,
            "referrer": req.referrer,
            "query_text": req.query_text,
            "created_at": req.created_at,
        })

    def _deserialize(self, raw: str) -> PendingAsyncRequest:
        data = json.loads(raw)
        return PendingAsyncRequest(
            connection_id=data["connection_id"],
            session_id=data.get("session_id"),
            context_id=data.get("context_id"),
            conversation_id=data.get("conversation_id"),
            cp_gutc_id=data.get("cp_gutc_id"),
            referrer=data.get("referrer"),
            query_text=data.get("query_text"),
            created_at=data.get("created_at", 0.0),
        )

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
        """Store context in Redis with auto-expiry TTL."""
        req = PendingAsyncRequest(
            connection_id=connection_id,
            session_id=session_id,
            context_id=context_id,
            conversation_id=conversation_id,
            cp_gutc_id=cp_gutc_id,
            referrer=referrer,
            query_text=query_text,
        )
        client = self._get_client()
        key = self._key(request_id)
        client.set(key, self._serialize(req), ex=self._auto_expire_seconds)
        self._logger.debug("correlation_stored", request_id=request_id)

    def get_and_remove(self, request_id: str) -> PendingAsyncRequest | None:
        """Atomically get and delete the pending request from Redis."""
        client = self._get_client()
        key = self._key(request_id)
        raw = client.getdel(key)
        if raw is None:
            return None
        return self._deserialize(raw)

    def mark_delivered(self, request_id: str) -> None:
        """Remember that this requestId was successfully delivered (short TTL)."""
        client = self._get_client()
        client.set(
            f"{REDIS_DELIVERED_KEY_PREFIX}{request_id}",
            "1",
            ex=DELIVERED_CACHE_TTL_SECONDS,
        )

    def was_delivered(self, request_id: str) -> bool:
        """Check whether this requestId was recently delivered."""
        client = self._get_client()
        return bool(client.exists(f"{REDIS_DELIVERED_KEY_PREFIX}{request_id}"))

    def get_expired(self, timeout_seconds: float) -> list[tuple[str, PendingAsyncRequest]]:
        """
        Redis handles expiry via TTL — keys auto-delete.
        This method is a no-op for Redis; the sweep task can still call it safely.
        """
        return []

    def remove_by_connection(self, connection_id: str) -> list[str]:
        """
        Scan for keys belonging to this connection and remove them.
        Uses SCAN to avoid blocking Redis on large keyspaces.
        """
        client = self._get_client()
        removed: list[str] = []
        cursor = 0
        pattern = f"{REDIS_CORRELATION_KEY_PREFIX}*"
        while True:
            cursor, keys = client.scan(cursor=cursor, match=pattern, count=100)
            for key in keys:
                raw = client.get(key)
                if raw is None:
                    continue
                try:
                    data = json.loads(raw)
                    if data.get("connection_id") == connection_id:
                        client.delete(key)
                        rid = key.removeprefix(REDIS_CORRELATION_KEY_PREFIX)
                        removed.append(rid)
                except (json.JSONDecodeError, KeyError):
                    pass
            if cursor == 0:
                break
        return removed
