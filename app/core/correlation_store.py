"""In-memory + Redis-backed correlation store for async request tracking."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Protocol, runtime_checkable

from app.logging.setup import get_logger

logger = get_logger()

REDIS_KEY_PREFIX = "ws_async_req:"
REDIS_DELIVERED_KEY_PREFIX = "ws_async_delivered:"
DEFAULT_TTL_SECONDS = 300


@dataclass
class PendingAsyncRequest:
    """Context stashed when the UI sends a message that will be answered asynchronously."""

    connection_id: str
    session_id: str
    context_id: str
    conversation_id: str
    cp_gutc_id: str = ""
    referrer: str = ""
    query_text: str = ""
    created_at: float = field(default_factory=time.time)


@runtime_checkable
class CorrelationStoreProtocol(Protocol):
    """Minimal interface so both in-memory and Redis stores are interchangeable."""

    def set(self, request_id: str, record: PendingAsyncRequest) -> None: ...

    def get(self, request_id: str) -> PendingAsyncRequest | None: ...

    def get_and_remove(self, request_id: str) -> PendingAsyncRequest | None: ...

    def remove_by_connection(self, connection_id: str) -> list[str]: ...

    def get_expired(self, timeout_seconds: int) -> list[tuple[str, PendingAsyncRequest]]: ...


class CorrelationStore:
    """Simple in-memory store — fine for single-pod dev / staging."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingAsyncRequest] = {}

    def set(self, request_id: str, record: PendingAsyncRequest) -> None:
        self._pending[request_id] = record
        logger.debug("correlation_store_set", request_id=request_id, connection_id=record.connection_id)

    def get(self, request_id: str) -> PendingAsyncRequest | None:
        """Non-destructive lookup — entry stays in the store for subsequent webhooks."""
        entry = self._pending.get(request_id)
        if entry is None:
            logger.warning("correlation_store_miss", request_id=request_id)
        else:
            logger.debug("correlation_store_hit", request_id=request_id)
        return entry

    def get_and_remove(self, request_id: str) -> PendingAsyncRequest | None:
        entry = self._pending.pop(request_id, None)
        if entry is None:
            logger.warning("correlation_store_miss", request_id=request_id)
        else:
            logger.debug("correlation_store_hit_removed", request_id=request_id)
        return entry

    def remove_by_connection(self, connection_id: str) -> list[str]:
        """Remove all entries for a given connection (cleanup on WS disconnect)."""
        orphaned = [
            rid for rid, rec in self._pending.items()
            if rec.connection_id == connection_id
        ]
        for rid in orphaned:
            del self._pending[rid]
        return orphaned

    def get_expired(self, timeout_seconds: int) -> list[tuple[str, PendingAsyncRequest]]:
        """Return and remove entries older than timeout_seconds."""
        now = time.time()
        expired: list[tuple[str, PendingAsyncRequest]] = []
        for rid, rec in list(self._pending.items()):
            if now - rec.created_at > timeout_seconds:
                expired.append((rid, rec))
                del self._pending[rid]
        return expired


class RedisCorrelationStore:
    """Redis-backed store for multi-pod deployments."""

    def __init__(self, redis_url: str, auto_expire_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._redis_url = redis_url
        self._ttl = auto_expire_seconds
        self._client = None

    def _get_client(self):
        if self._client is None:
            import redis
            self._client = redis.Redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    @staticmethod
    def _key(request_id: str) -> str:
        return f"{REDIS_KEY_PREFIX}{request_id}"

    @staticmethod
    def _serialize(record: PendingAsyncRequest) -> str:
        return json.dumps(asdict(record))

    @staticmethod
    def _deserialize(raw: str) -> PendingAsyncRequest:
        return PendingAsyncRequest(**json.loads(raw))

    def set(self, request_id: str, record: PendingAsyncRequest) -> None:
        client = self._get_client()
        client.set(self._key(request_id), self._serialize(record), ex=self._ttl)
        logger.debug("redis_correlation_store_set", request_id=request_id)

    def get(self, request_id: str) -> PendingAsyncRequest | None:
        """Non-destructive lookup — entry stays in Redis for subsequent webhooks."""
        client = self._get_client()
        raw = client.get(self._key(request_id))
        if raw is None:
            logger.warning("redis_correlation_store_miss", request_id=request_id)
            return None
        logger.debug("redis_correlation_store_hit", request_id=request_id)
        return self._deserialize(raw)

    def get_and_remove(self, request_id: str) -> PendingAsyncRequest | None:
        client = self._get_client()
        raw = client.getdel(self._key(request_id))
        if raw is None:
            logger.warning("redis_correlation_store_miss", request_id=request_id)
            return None
        logger.debug("redis_correlation_store_hit_removed", request_id=request_id)
        return self._deserialize(raw)

    def remove_by_connection(self, connection_id: str) -> list[str]:
        """Remove all entries for a given connection. Scans matching keys."""
        client = self._get_client()
        orphaned: list[str] = []
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor, match=f"{REDIS_KEY_PREFIX}*", count=100)
            for key in keys:
                raw = client.get(key)
                if raw is None:
                    continue
                rec = self._deserialize(raw)
                if rec.connection_id == connection_id:
                    request_id = key.removeprefix(REDIS_KEY_PREFIX)
                    client.delete(key)
                    orphaned.append(request_id)
            if cursor == 0:
                break
        return orphaned

    def get_expired(self, timeout_seconds: int) -> list[tuple[str, PendingAsyncRequest]]:
        """Return and remove entries older than timeout_seconds. Redis TTL handles most cleanup."""
        now = time.time()
        client = self._get_client()
        expired: list[tuple[str, PendingAsyncRequest]] = []
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor, match=f"{REDIS_KEY_PREFIX}*", count=100)
            for key in keys:
                raw = client.get(key)
                if raw is None:
                    continue
                rec = self._deserialize(raw)
                if now - rec.created_at > timeout_seconds:
                    request_id = key.removeprefix(REDIS_KEY_PREFIX)
                    client.delete(key)
                    expired.append((request_id, rec))
            if cursor == 0:
                break
        return expired
