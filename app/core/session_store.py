"""Session store with sliding-window TTL (in-memory and Redis backends)."""

import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.logging.setup import get_logger

logger = get_logger()


class SessionStore(Protocol):
    """Protocol for session store backends (in-memory or Redis)."""

    def get(self, session_id: str, now: datetime | None = None) -> "Session | None": ...
    def create(self, now: datetime | None = None) -> str: ...
    def extend_ttl(self, session_id: str, now: datetime | None = None) -> bool: ...
    def get_stats(self) -> dict[str, Any]: ...


@dataclass
class Session:
    """A single session with expiry and optional metadata."""

    session_id: str
    expires_at: datetime
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity_at: datetime | None = None

    def is_expired(self, now: datetime | None = None) -> bool:
        """Return True if the session has expired."""
        if now is None:
            now = datetime.utcnow()
        return now >= self.expires_at


class InMemorySessionStore:
    """
    In-memory session store with sliding-window TTL.

    - get(session_id): return session if exists and not expired, else None.
    - create(): create a new session, return session_id.
    - extend_ttl(session_id): extend expires_at by idle_ttl; respect max lifetime.
    """

    def __init__(
        self,
        idle_ttl_seconds: int = 1800,
        max_lifetime_seconds: int | None = 86400,
    ) -> None:
        self._idle_ttl_seconds = idle_ttl_seconds
        self._max_lifetime_seconds = max_lifetime_seconds
        self._sessions: dict[str, Session] = {}
        self._logger = logger.bind(component="session_store")

    def get(self, session_id: str, now: datetime | None = None) -> Session | None:
        """
        Get a session by ID if it exists and is not expired.

        Returns None if missing or expired.
        """
        if now is None:
            now = datetime.utcnow()
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired(now):
            del self._sessions[session_id]
            self._logger.debug("session_expired_removed", session_id=session_id)
            return None
        return session

    def create(self, now: datetime | None = None) -> str:
        """
        Create a new session and return its ID.

        Uses a cryptographically secure random ID.
        """
        if now is None:
            now = datetime.utcnow()
        session_id = secrets.token_urlsafe(32)
        expires_at = self._add_seconds(now, self._idle_ttl_seconds)
        session = Session(
            session_id=session_id,
            expires_at=expires_at,
            created_at=now,
            last_activity_at=now,
        )
        self._sessions[session_id] = session
        self._logger.info(
            "session_created",
            session_id=session_id,
            expires_at=expires_at.isoformat(),
        )
        return session_id

    def extend_ttl(self, session_id: str, now: datetime | None = None) -> bool:
        """
        Extend the session's expiry by idle_ttl from now.
        Respects max_lifetime_seconds if set.

        Returns True if extended, False if session not found or expired.
        """
        session = self.get(session_id, now=now)
        if session is None:
            return False
        if now is None:
            now = datetime.utcnow()
        new_expires = self._add_seconds(now, self._idle_ttl_seconds)
        if self._max_lifetime_seconds is not None:
            max_expires = self._add_seconds(session.created_at, self._max_lifetime_seconds)
            if new_expires > max_expires:
                new_expires = max_expires
        session.expires_at = new_expires
        session.last_activity_at = now
        self._logger.debug(
            "session_ttl_extended",
            session_id=session_id,
            expires_at=new_expires.isoformat(),
        )
        return True

    def _add_seconds(self, dt: datetime, seconds: int) -> datetime:
        """Add seconds to a datetime (timezone-aware safe)."""
        from datetime import timedelta
        return dt + timedelta(seconds=seconds)

    def get_stats(self) -> dict[str, Any]:
        """Return store stats for monitoring."""
        now = datetime.utcnow()
        active = sum(1 for s in self._sessions.values() if not s.is_expired(now))
        return {
            "total_sessions": len(self._sessions),
            "active_sessions": active,
        }


# Redis key prefix and hash field names (schema)
REDIS_SESSION_KEY_PREFIX = "ws_user_session:"
REDIS_CONVERSATION_KEY_PREFIX = "ws_user_conversation:"
REDIS_FIELD_SESSION_ID = "session_id"
REDIS_FIELD_EXPIRES_AT = "expires_at"
REDIS_FIELD_CREATED_AT = "created_at"
REDIS_FIELD_LAST_ACTIVITY_AT = "last_activity_at"


class RedisSessionStore:
    """
    Redis-backed session store with sliding-window TTL.

    Key: ws_user_session:{session_id}
    Value: Hash with session_id, expires_at, created_at, last_activity_at (ISO 8601).
    Key TTL: Set so Redis auto-deletes when the session expires.
    """

    def __init__(
        self,
        redis_url: str,
        idle_ttl_seconds: int = 1800,
        max_lifetime_seconds: int | None = 86400,
    ) -> None:
        self._redis_url = redis_url
        self._idle_ttl_seconds = idle_ttl_seconds
        self._max_lifetime_seconds = max_lifetime_seconds
        self._client = None
        self._logger = logger.bind(component="redis_session_store")

    def _get_client(self):
        """Lazy connection to Redis (sync client)."""
        if self._client is None:
            import redis
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    def _key(self, session_id: str) -> str:
        return f"{REDIS_SESSION_KEY_PREFIX}{session_id}"

    def _conversation_key(self, conversation_id: str) -> str:
        return f"{REDIS_CONVERSATION_KEY_PREFIX}{conversation_id}"

    def _add_seconds(self, dt: datetime, seconds: int) -> datetime:
        from datetime import timedelta
        return dt + timedelta(seconds=seconds)

    def get(self, session_id: str, now: datetime | None = None) -> Session | None:
        """Get a session by ID if it exists and is not expired. Returns None if missing or expired."""
        if now is None:
            now = datetime.utcnow()
        client = self._get_client()
        key = self._key(session_id)
        raw = client.hgetall(key)
        if not raw:
            return None
        try:
            expires_at = datetime.fromisoformat(raw[REDIS_FIELD_EXPIRES_AT])
            created_at = datetime.fromisoformat(raw[REDIS_FIELD_CREATED_AT])
            last_activity_at_raw = raw.get(REDIS_FIELD_LAST_ACTIVITY_AT)
            last_activity_at = (
                datetime.fromisoformat(last_activity_at_raw) if last_activity_at_raw else None
            )
        except (ValueError, KeyError):
            self._logger.warning("redis_session_invalid_fields", session_id=session_id)
            client.delete(key)
            return None
        if now >= expires_at:
            client.delete(key)
            self._logger.debug("session_expired_removed", session_id=session_id)
            return None
        return Session(
            session_id=session_id,
            expires_at=expires_at,
            created_at=created_at,
            last_activity_at=last_activity_at,
        )

    def create(self, now: datetime | None = None) -> str:
        """Create a new session in Redis and return its ID."""
        if now is None:
            now = datetime.utcnow()
        session_id = secrets.token_urlsafe(32)
        expires_at = self._add_seconds(now, self._idle_ttl_seconds)
        key = self._key(session_id)
        client = self._get_client()
        client.hset(key, mapping={
            REDIS_FIELD_SESSION_ID: session_id,
            REDIS_FIELD_EXPIRES_AT: expires_at.isoformat(),
            REDIS_FIELD_CREATED_AT: now.isoformat(),
            REDIS_FIELD_LAST_ACTIVITY_AT: now.isoformat(),
        })
        ttl_seconds = max(1, int((expires_at - now).total_seconds()))
        client.expire(key, ttl_seconds)
        self._logger.info(
            "session_created",
            session_id=session_id,
            expires_at=expires_at.isoformat(),
        )
        return session_id

    def extend_ttl(self, session_id: str, now: datetime | None = None) -> bool:
        """Extend the session's expiry by idle_ttl from now; respect max_lifetime_seconds."""
        session = self.get(session_id, now=now)
        if session is None:
            return False
        if now is None:
            now = datetime.utcnow()
        new_expires = self._add_seconds(now, self._idle_ttl_seconds)
        if self._max_lifetime_seconds is not None:
            max_expires = self._add_seconds(session.created_at, self._max_lifetime_seconds)
            if new_expires > max_expires:
                new_expires = max_expires
        key = self._key(session_id)
        client = self._get_client()
        client.hset(key, mapping={
            REDIS_FIELD_EXPIRES_AT: new_expires.isoformat(),
            REDIS_FIELD_LAST_ACTIVITY_AT: now.isoformat(),
        })
        ttl_seconds = max(1, int((new_expires - now).total_seconds()))
        client.expire(key, ttl_seconds)
        self._logger.debug(
            "session_ttl_extended",
            session_id=session_id,
            expires_at=new_expires.isoformat(),
        )
        return True

    def set_conversation_session(self, conversation_id: str, session_id: str) -> None:
        """
        Store conversationId -> sessionId mapping (one session can have many conversations).
        Key: ws_user_conversation:{conversation_id}, value: session_id. TTL = idle_ttl_seconds.
        """
        if not conversation_id or not session_id:
            return
        client = self._get_client()
        key = self._conversation_key(conversation_id)
        client.set(key, session_id)
        ttl_seconds = max(1, self._idle_ttl_seconds)
        client.expire(key, ttl_seconds)
        self._logger.debug(
            "conversation_session_stored",
            conversation_id=conversation_id,
            session_id=session_id,
        )

    def get_session_for_conversation(self, conversation_id: str) -> str | None:
        """
        Resolve sessionId for a conversationId (Option B: lookup by conversation only).
        Returns None if not found or key expired.
        """
        if not conversation_id:
            return None
        client = self._get_client()
        key = self._conversation_key(conversation_id)
        session_id = client.get(key)
        return session_id

    def get_stats(self) -> dict[str, Any]:
        """Return store stats (Redis does not support cheap key count by prefix; return placeholder)."""
        return {
            "total_sessions": 0,
            "active_sessions": 0,
            "backend": "redis",
        }
