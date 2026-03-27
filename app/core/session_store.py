"""Session store with sliding-window TTL (in-memory and Redis backends)."""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.logging.setup import get_logger

logger = get_logger()


class SessionStore(Protocol):
    """Protocol for session store backends (in-memory or Redis)."""

    async def get(self, session_id: str, now: datetime | None = None) -> "Session | None": ...
    async def create(self, now: datetime | None = None, user_token: str = "", email_address: str = "", ccoid: str = "") -> str: ...
    async def extend_ttl(self, session_id: str, now: datetime | None = None) -> str: ...
    async def renew_session(self, session_id: str, now: datetime | None = None) -> "Session | None": ...
    async def delete_session(self, session_id: str) -> bool: ...
    def get_stats(self) -> dict[str, Any]: ...


@dataclass
class Session:
    """A single session with expiry and optional metadata."""

    session_id: str
    expires_at: datetime
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity_at: datetime | None = None
    user_token: str = ""
    email_address: str = ""
    ccoid: str = ""

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
        renewal_idle_threshold_seconds: int = 900,
    ) -> None:
        self._idle_ttl_seconds = idle_ttl_seconds
        self._max_lifetime_seconds = max_lifetime_seconds
        self._renewal_idle_threshold_seconds = renewal_idle_threshold_seconds
        self._sessions: dict[str, Session] = {}
        self._conversation_map: dict[str, str] = {}
        self._logger = logger.bind(component="session_store")

    async def get(self, session_id: str, now: datetime | None = None) -> Session | None:
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

    async def create(
        self,
        now: datetime | None = None,
        user_token: str = "",
        email_address: str = "",
        ccoid: str = "",
    ) -> str:
        if now is None:
            now = datetime.utcnow()
        session_id = secrets.token_urlsafe(32)
        expires_at = now + timedelta(seconds=self._idle_ttl_seconds)
        session = Session(
            session_id=session_id,
            expires_at=expires_at,
            created_at=now,
            last_activity_at=now,
            user_token=user_token,
            email_address=email_address,
            ccoid=ccoid,
        )
        self._sessions[session_id] = session
        self._logger.info(
            "session_created",
            session_id=session_id,
            expires_at=expires_at.isoformat(),
        )
        return session_id

    async def extend_ttl(self, session_id: str, now: datetime | None = None) -> str:
        session = await self.get(session_id, now=now)
        if session is None:
            return "expired"
        if now is None:
            now = datetime.utcnow()

        if self._max_lifetime_seconds is not None:
            max_expires = session.created_at + timedelta(seconds=self._max_lifetime_seconds)
            remaining = (max_expires - now).total_seconds()
            idle_duration = (now - session.last_activity_at).total_seconds() if session.last_activity_at else 0

            if remaining < self._idle_ttl_seconds and idle_duration > self._renewal_idle_threshold_seconds:
                self._logger.info(
                    "session_early_expiry_renewal_zone",
                    session_id=session_id,
                    remaining_seconds=round(remaining),
                    idle_seconds=round(idle_duration),
                )
                return "expired"

        new_expires = now + timedelta(seconds=self._idle_ttl_seconds)
        if self._max_lifetime_seconds is not None:
            max_expires = session.created_at + timedelta(seconds=self._max_lifetime_seconds)
            if new_expires > max_expires:
                new_expires = max_expires
        session.expires_at = new_expires
        session.last_activity_at = now
        self._logger.debug(
            "session_ttl_extended",
            session_id=session_id,
            expires_at=new_expires.isoformat(),
        )
        return "extended"

    async def renew_session(self, session_id: str, now: datetime | None = None) -> Session | None:
        """Reset created_at to now and set expires_at to a full new max lifetime window."""
        session = await self.get(session_id, now=now)
        if session is None:
            return None
        if now is None:
            now = datetime.utcnow()
        session.created_at = now
        lifetime = self._max_lifetime_seconds or self._idle_ttl_seconds
        session.expires_at = now + timedelta(seconds=lifetime)
        session.last_activity_at = now
        self._logger.info(
            "session_renewed",
            session_id=session_id,
            expires_at=session.expires_at.isoformat(),
        )
        return session

    async def delete_session(self, session_id: str) -> bool:
        """Remove a session entirely."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            self._logger.info("session_deleted", session_id=session_id)
            return True
        return False

    async def set_conversation_session(self, conversation_id: str, session_id: str) -> None:
        """Store conversationId -> sessionId mapping (in-memory)."""
        self._conversation_map[conversation_id] = session_id

    async def get_session_for_conversation(self, conversation_id: str) -> str | None:
        """Resolve sessionId for a conversationId."""
        return self._conversation_map.get(conversation_id)

    def get_stats(self) -> dict[str, Any]:
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
REDIS_FIELD_USER_TOKEN = "user_token"
REDIS_FIELD_EMAIL_ADDRESS = "email_address"
REDIS_FIELD_CCOID = "ccoid"


class RedisSessionStore:
    """
    Redis-backed session store with sliding-window TTL (async client).

    Key: ws_user_session:{session_id}
    Value: Hash with session_id, expires_at, created_at, last_activity_at (ISO 8601).
    Key TTL: Set so Redis auto-deletes when the session expires.
    """

    def __init__(
        self,
        redis_url: str,
        idle_ttl_seconds: int = 1800,
        max_lifetime_seconds: int | None = 86400,
        renewal_idle_threshold_seconds: int = 900,
    ) -> None:
        self._redis_url = redis_url
        self._idle_ttl_seconds = idle_ttl_seconds
        self._max_lifetime_seconds = max_lifetime_seconds
        self._renewal_idle_threshold_seconds = renewal_idle_threshold_seconds
        self._client = None
        self._logger = logger.bind(component="redis_session_store")

    def _get_client(self):
        """Lazy connection to Redis (async client)."""
        if self._client is None:
            import redis.asyncio as aioredis
            self._client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
        return self._client

    def _key(self, session_id: str) -> str:
        return f"{REDIS_SESSION_KEY_PREFIX}{session_id}"

    def _conversation_key(self, conversation_id: str) -> str:
        return f"{REDIS_CONVERSATION_KEY_PREFIX}{conversation_id}"

    async def get(self, session_id: str, now: datetime | None = None) -> Session | None:
        """Get a session by ID if it exists and is not expired."""
        if now is None:
            now = datetime.utcnow()
        client = self._get_client()
        key = self._key(session_id)
        raw = await client.hgetall(key)
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
            await client.delete(key)
            return None
        if now >= expires_at:
            await client.delete(key)
            self._logger.debug("session_expired_removed", session_id=session_id)
            return None
        return Session(
            session_id=session_id,
            expires_at=expires_at,
            created_at=created_at,
            last_activity_at=last_activity_at,
            user_token=raw.get(REDIS_FIELD_USER_TOKEN, ""),
            email_address=raw.get(REDIS_FIELD_EMAIL_ADDRESS, ""),
            ccoid=raw.get(REDIS_FIELD_CCOID, ""),
        )

    async def create(
        self,
        now: datetime | None = None,
        user_token: str = "",
        email_address: str = "",
        ccoid: str = "",
    ) -> str:
        """Create a new session in Redis and return its ID."""
        if now is None:
            now = datetime.utcnow()
        session_id = secrets.token_urlsafe(32)
        expires_at = now + timedelta(seconds=self._idle_ttl_seconds)
        key = self._key(session_id)
        client = self._get_client()
        await client.hset(key, mapping={
            REDIS_FIELD_SESSION_ID: session_id,
            REDIS_FIELD_EXPIRES_AT: expires_at.isoformat(),
            REDIS_FIELD_CREATED_AT: now.isoformat(),
            REDIS_FIELD_LAST_ACTIVITY_AT: now.isoformat(),
            REDIS_FIELD_USER_TOKEN: user_token,
            REDIS_FIELD_EMAIL_ADDRESS: email_address,
            REDIS_FIELD_CCOID: ccoid,
        })
        ttl_seconds = max(1, int((expires_at - now).total_seconds()))
        await client.expire(key, ttl_seconds)
        self._logger.info(
            "session_created",
            session_id=session_id,
            expires_at=expires_at.isoformat(),
        )
        return session_id

    async def extend_ttl(self, session_id: str, now: datetime | None = None) -> str:
        """Extend the session's expiry by idle_ttl from now; respect max_lifetime_seconds.

        Returns 'extended' on success, 'expired' if session not found or early expiry triggered.
        """
        session = await self.get(session_id, now=now)
        if session is None:
            return "expired"
        if now is None:
            now = datetime.utcnow()

        if self._max_lifetime_seconds is not None:
            max_expires = session.created_at + timedelta(seconds=self._max_lifetime_seconds)
            remaining = (max_expires - now).total_seconds()
            idle_duration = (now - session.last_activity_at).total_seconds() if session.last_activity_at else 0

            if remaining < self._idle_ttl_seconds and idle_duration > self._renewal_idle_threshold_seconds:
                self._logger.info(
                    "session_early_expiry_renewal_zone",
                    session_id=session_id,
                    remaining_seconds=round(remaining),
                    idle_seconds=round(idle_duration),
                )
                return "expired"

        new_expires = now + timedelta(seconds=self._idle_ttl_seconds)
        if self._max_lifetime_seconds is not None:
            max_expires = session.created_at + timedelta(seconds=self._max_lifetime_seconds)
            if new_expires > max_expires:
                new_expires = max_expires
        key = self._key(session_id)
        client = self._get_client()
        await client.hset(key, mapping={
            REDIS_FIELD_EXPIRES_AT: new_expires.isoformat(),
            REDIS_FIELD_LAST_ACTIVITY_AT: now.isoformat(),
        })
        ttl_seconds = max(1, int((new_expires - now).total_seconds()))
        await client.expire(key, ttl_seconds)
        self._logger.debug(
            "session_ttl_extended",
            session_id=session_id,
            expires_at=new_expires.isoformat(),
        )
        return "extended"

    async def renew_session(self, session_id: str, now: datetime | None = None) -> Session | None:
        """Reset created_at to now and set expires_at to a full new max lifetime window."""
        session = await self.get(session_id, now=now)
        if session is None:
            return None
        if now is None:
            now = datetime.utcnow()
        lifetime = self._max_lifetime_seconds or self._idle_ttl_seconds
        new_expires = now + timedelta(seconds=lifetime)
        key = self._key(session_id)
        client = self._get_client()
        await client.hset(key, mapping={
            REDIS_FIELD_CREATED_AT: now.isoformat(),
            REDIS_FIELD_EXPIRES_AT: new_expires.isoformat(),
            REDIS_FIELD_LAST_ACTIVITY_AT: now.isoformat(),
        })
        ttl_seconds = max(1, int((new_expires - now).total_seconds()))
        await client.expire(key, ttl_seconds)
        session.created_at = now
        session.expires_at = new_expires
        session.last_activity_at = now
        self._logger.info(
            "session_renewed",
            session_id=session_id,
            expires_at=new_expires.isoformat(),
        )
        return session

    async def delete_session(self, session_id: str) -> bool:
        """Remove a session and its Redis key entirely."""
        client = self._get_client()
        key = self._key(session_id)
        deleted = await client.delete(key)
        if deleted:
            self._logger.info("session_deleted", session_id=session_id)
            return True
        return False

    async def set_conversation_session(self, conversation_id: str, session_id: str) -> None:
        """Store conversationId -> sessionId mapping. TTL = idle_ttl_seconds."""
        if not conversation_id or not session_id:
            return
        client = self._get_client()
        key = self._conversation_key(conversation_id)
        await client.set(key, session_id)
        await client.expire(key, max(1, self._idle_ttl_seconds))
        self._logger.debug(
            "conversation_session_stored",
            conversation_id=conversation_id,
            session_id=session_id,
        )

    async def get_session_for_conversation(self, conversation_id: str) -> str | None:
        """Resolve sessionId for a conversationId."""
        if not conversation_id:
            return None
        client = self._get_client()
        key = self._conversation_key(conversation_id)
        return await client.get(key)

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_sessions": 0,
            "active_sessions": 0,
            "backend": "redis",
        }
