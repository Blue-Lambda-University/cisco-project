"""In-memory + Redis-backed correlation store for async request tracking."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Protocol, runtime_checkable

from app.logging.setup import get_logger

logger = get_logger()

REDIS_KEY_PREFIX = "ws_async_req:"
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

    def get_and_remove(self, request_id: str) -> PendingAsyncRequest | None: ...


class CorrelationStore:
    """Simple in-memory store — fine for single-pod dev / staging."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingAsyncRequest] = {}

    def set(self, request_id: str, record: PendingAsyncRequest) -> None:
        self._pending[request_id] = record
        logger.debug("correlation_store_set", request_id=request_id, connection_id=record.connection_id)

    def get_and_remove(self, request_id: str) -> PendingAsyncRequest | None:
        entry = self._pending.pop(request_id, None)
        if entry is None:
            logger.warning("correlation_store_miss", request_id=request_id)
        else:
            logger.debug("correlation_store_hit", request_id=request_id)
        return entry


class RedisCorrelationStore:
    """Redis-backed store for multi-pod deployments."""

    def __init__(self, redis_url: str, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        self._redis_url = redis_url
        self._ttl = ttl
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

    def get_and_remove(self, request_id: str) -> PendingAsyncRequest | None:
        client = self._get_client()
        raw = client.getdel(self._key(request_id))
        if raw is None:
            logger.warning("redis_correlation_store_miss", request_id=request_id)
            return None
        logger.debug("redis_correlation_store_hit", request_id=request_id)
        return self._deserialize(raw)
