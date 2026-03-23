"""Correlation store: pending async request context with FIFO queue support.

Two backends:
- CorrelationStore: in-memory (single pod)
- RedisCorrelationStore: Redis-backed (multi-pod)

Entries are indexed by both requestId (for SSE-path removal) and conversationId
(for webhook-path FIFO delivery).  The orchestrator sends conversationId as the
webhook requestId, so multiple messages in the same conversation are queued and
delivered in order.
"""

import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

from app.logging.setup import get_logger

logger = get_logger()

REDIS_CORRELATION_KEY_PREFIX = "ws_pending_request:"
REDIS_CONVERSATION_QUEUE_PREFIX = "ws_pending_queue:"
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
    request_id: str | None = None
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

    def pop_by_conversation(self, conversation_id: str) -> PendingAsyncRequest | None: ...

    def mark_delivered(self, key: str) -> None: ...

    def was_delivered(self, key: str) -> bool: ...

    def get_expired(self, timeout_seconds: float) -> list[tuple[str, PendingAsyncRequest]]: ...

    def remove_by_connection(self, connection_id: str) -> list[str]: ...


# ---------------------------------------------------------------------------
# In-memory backend (single pod)
# ---------------------------------------------------------------------------


class CorrelationStore:
    """
    In-memory correlation store with dual indexing:
    - _pending: requestId -> entry  (for SSE-path exact removal)
    - _conversation_queue: conversationId -> deque[requestId]  (for webhook FIFO)
    - _delivered: recently delivered keys (idempotent 200 on retries)
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingAsyncRequest] = {}
        self._conversation_queue: dict[str, deque[str]] = {}
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
        """Store context indexed by requestId and queued by conversationId."""
        entry = PendingAsyncRequest(
            connection_id=connection_id,
            session_id=session_id,
            context_id=context_id,
            conversation_id=conversation_id,
            cp_gutc_id=cp_gutc_id,
            referrer=referrer,
            query_text=query_text,
            request_id=request_id,
        )
        self._pending[request_id] = entry
        if conversation_id:
            self._conversation_queue.setdefault(conversation_id, deque()).append(request_id)

    def get_and_remove(self, request_id: str) -> PendingAsyncRequest | None:
        """Remove by exact requestId (SSE path). Also removes from conversation queue."""
        entry = self._pending.pop(request_id, None)
        if entry and entry.conversation_id:
            q = self._conversation_queue.get(entry.conversation_id)
            if q:
                try:
                    q.remove(request_id)
                except ValueError:
                    pass
                if not q:
                    del self._conversation_queue[entry.conversation_id]
        return entry

    def pop_by_conversation(self, conversation_id: str) -> PendingAsyncRequest | None:
        """Pop the oldest pending entry for a conversationId (FIFO). Used by webhook."""
        q = self._conversation_queue.get(conversation_id)
        while q:
            request_id = q.popleft()
            entry = self._pending.pop(request_id, None)
            if not q:
                del self._conversation_queue[conversation_id]
            if entry is not None:
                return entry
        if conversation_id in self._conversation_queue:
            del self._conversation_queue[conversation_id]
        return None

    def mark_delivered(self, key: str) -> None:
        """Remember that this key was successfully delivered."""
        self._delivered[key] = time.monotonic()
        self._prune_delivered()

    def was_delivered(self, key: str) -> bool:
        """Check whether this key was recently delivered."""
        self._prune_delivered()
        return key in self._delivered

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
            entry = self._pending.pop(rid, None)
            if entry and entry.conversation_id:
                q = self._conversation_queue.get(entry.conversation_id)
                if q:
                    try:
                        q.remove(rid)
                    except ValueError:
                        pass
                    if not q:
                        del self._conversation_queue[entry.conversation_id]
        return expired

    def remove_by_connection(self, connection_id: str) -> list[str]:
        """Remove all entries for a given connection_id. Returns removed requestIds."""
        to_remove = [
            rid for rid, req in self._pending.items()
            if req.connection_id == connection_id
        ]
        for rid in to_remove:
            entry = self._pending.pop(rid, None)
            if entry and entry.conversation_id:
                q = self._conversation_queue.get(entry.conversation_id)
                if q:
                    try:
                        q.remove(rid)
                    except ValueError:
                        pass
                    if not q:
                        del self._conversation_queue[entry.conversation_id]
        return to_remove


# ---------------------------------------------------------------------------
# Redis backend (multi-pod)
# ---------------------------------------------------------------------------


class RedisCorrelationStore:
    """
    Redis-backed correlation store with FIFO queue support.

    Entry storage:
        Key:   ws_pending_request:{requestId}
        Value: JSON with connection_id, session_id, etc.

    Conversation queue (FIFO):
        Key:   ws_pending_queue:{conversationId}
        Value: Redis List of requestIds (RPUSH to enqueue, LPOP to dequeue)
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

    def _queue_key(self, conversation_id: str) -> str:
        return f"{REDIS_CONVERSATION_QUEUE_PREFIX}{conversation_id}"

    def _serialize(self, req: PendingAsyncRequest) -> str:
        return json.dumps({
            "connection_id": req.connection_id,
            "session_id": req.session_id,
            "context_id": req.context_id,
            "conversation_id": req.conversation_id,
            "cp_gutc_id": req.cp_gutc_id,
            "referrer": req.referrer,
            "query_text": req.query_text,
            "request_id": req.request_id,
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
            request_id=data.get("request_id"),
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
        """Store entry in Redis and enqueue in conversation FIFO."""
        req = PendingAsyncRequest(
            connection_id=connection_id,
            session_id=session_id,
            context_id=context_id,
            conversation_id=conversation_id,
            cp_gutc_id=cp_gutc_id,
            referrer=referrer,
            query_text=query_text,
            request_id=request_id,
        )
        client = self._get_client()
        key = self._key(request_id)
        client.set(key, self._serialize(req), ex=self._auto_expire_seconds)
        if conversation_id:
            queue_key = self._queue_key(conversation_id)
            client.rpush(queue_key, request_id)
            client.expire(queue_key, self._auto_expire_seconds)
        self._logger.debug("correlation_stored", request_id=request_id, conversation_id=conversation_id)

    def get_and_remove(self, request_id: str) -> PendingAsyncRequest | None:
        """Atomically get and delete by requestId. Also removes from conversation queue."""
        client = self._get_client()
        key = self._key(request_id)
        raw = client.getdel(key)
        if raw is None:
            return None
        entry = self._deserialize(raw)
        if entry.conversation_id:
            client.lrem(self._queue_key(entry.conversation_id), 1, request_id)
        return entry

    def pop_by_conversation(self, conversation_id: str) -> PendingAsyncRequest | None:
        """Pop the oldest pending entry for a conversationId (FIFO)."""
        client = self._get_client()
        queue_key = self._queue_key(conversation_id)
        while True:
            request_id = client.lpop(queue_key)
            if request_id is None:
                return None
            entry_key = self._key(request_id)
            raw = client.getdel(entry_key)
            if raw is not None:
                return self._deserialize(raw)

    def mark_delivered(self, key: str) -> None:
        """Remember that this key was successfully delivered (short TTL)."""
        client = self._get_client()
        client.set(
            f"{REDIS_DELIVERED_KEY_PREFIX}{key}",
            "1",
            ex=DELIVERED_CACHE_TTL_SECONDS,
        )

    def was_delivered(self, key: str) -> bool:
        """Check whether this key was recently delivered."""
        client = self._get_client()
        return bool(client.exists(f"{REDIS_DELIVERED_KEY_PREFIX}{key}"))

    def get_expired(self, timeout_seconds: float) -> list[tuple[str, PendingAsyncRequest]]:
        """Redis handles expiry via TTL — no-op."""
        return []

    def remove_by_connection(self, connection_id: str) -> list[str]:
        """Scan for keys belonging to this connection and remove them."""
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
                        conv_id = data.get("conversation_id")
                        if conv_id:
                            client.lrem(self._queue_key(conv_id), 1, rid)
                except (json.JSONDecodeError, KeyError):
                    pass
            if cursor == 0:
                break
        return removed
