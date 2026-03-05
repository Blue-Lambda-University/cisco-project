"""Tests for session store (sliding-window TTL)."""

from datetime import datetime, timedelta

import pytest

from app.core.session_store import (
    InMemorySessionStore,
    REDIS_SESSION_KEY_PREFIX,
    RedisSessionStore,
    Session,
)


class TestSession:
    """Tests for Session dataclass."""

    def test_is_expired_future(self):
        """Session with future expires_at is not expired."""
        future = datetime.utcnow() + timedelta(minutes=5)
        session = Session(session_id="s1", expires_at=future)
        assert session.is_expired() is False

    def test_is_expired_past(self):
        """Session with past expires_at is expired."""
        past = datetime.utcnow() - timedelta(minutes=1)
        session = Session(session_id="s1", expires_at=past)
        assert session.is_expired() is True


class TestInMemorySessionStore:
    """Tests for InMemorySessionStore."""

    def test_create_returns_id(self):
        """create() returns a non-empty session ID (no prefix)."""
        store = InMemorySessionStore(idle_ttl_seconds=60)
        sid = store.create()
        assert sid is not None
        assert len(sid) > 10

    def test_get_returns_created_session(self):
        """get() returns a session right after create()."""
        store = InMemorySessionStore(idle_ttl_seconds=60)
        sid = store.create()
        session = store.get(sid)
        assert session is not None
        assert session.session_id == sid

    def test_get_returns_none_for_unknown(self):
        """get() returns None for unknown session ID."""
        store = InMemorySessionStore(idle_ttl_seconds=60)
        assert store.get("unknown-id") is None

    def test_extend_ttl_updates_expiry(self):
        """extend_ttl() updates expires_at."""
        store = InMemorySessionStore(idle_ttl_seconds=60)
        sid = store.create()
        session_before = store.get(sid)
        assert session_before is not None
        store.extend_ttl(sid)
        session_after = store.get(sid)
        assert session_after is not None
        assert session_after.expires_at >= session_before.expires_at

    def test_extend_ttl_returns_false_for_unknown(self):
        """extend_ttl() returns False for unknown session."""
        store = InMemorySessionStore(idle_ttl_seconds=60)
        assert store.extend_ttl("unknown-id") is False

    def test_get_stats(self):
        """get_stats() returns total and active counts."""
        store = InMemorySessionStore(idle_ttl_seconds=60)
        store.create()
        store.create()
        stats = store.get_stats()
        assert stats["total_sessions"] == 2
        assert stats["active_sessions"] == 2


def _redis_available() -> bool:
    """Return True if Redis is reachable at localhost:6379."""
    try:
        import redis
        r = redis.from_url("redis://localhost:6379/1", decode_responses=True)
        r.ping()
        r.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _redis_available(), reason="Redis not available")
class TestRedisSessionStore:
    """Tests for RedisSessionStore (require Redis at localhost:6379)."""

    @pytest.fixture
    def redis_store(self):
        """Redis store using db=1 to avoid clashing with other data."""
        store = RedisSessionStore(
            redis_url="redis://localhost:6379/1",
            idle_ttl_seconds=60,
            max_lifetime_seconds=3600,
        )
        yield store
        # Clean up: delete test keys (ws_user_session:* in db 1)
        try:
            client = store._get_client()
            for key in client.scan_iter(f"{REDIS_SESSION_KEY_PREFIX}*", count=100):
                client.delete(key)
        except Exception:
            pass

    def test_create_returns_id(self, redis_store):
        """create() returns a non-empty session ID (no prefix)."""
        sid = redis_store.create()
        assert sid is not None
        assert len(sid) > 10

    def test_get_returns_created_session(self, redis_store):
        """get() returns a session right after create()."""
        sid = redis_store.create()
        session = redis_store.get(sid)
        assert session is not None
        assert session.session_id == sid

    def test_get_returns_none_for_unknown(self, redis_store):
        """get() returns None for unknown session ID."""
        assert redis_store.get("unknown-id-not-in-redis") is None

    def test_extend_ttl_updates_expiry(self, redis_store):
        """extend_ttl() updates expires_at."""
        sid = redis_store.create()
        session_before = redis_store.get(sid)
        assert session_before is not None
        redis_store.extend_ttl(sid)
        session_after = redis_store.get(sid)
        assert session_after is not None
        assert session_after.expires_at >= session_before.expires_at

    def test_extend_ttl_returns_false_for_unknown(self, redis_store):
        """extend_ttl() returns False for unknown session."""
        assert redis_store.extend_ttl("unknown-id") is False

    def test_get_stats_returns_backend(self, redis_store):
        """get_stats() returns dict with backend key."""
        stats = redis_store.get_stats()
        assert stats["backend"] == "redis"
        assert "total_sessions" in stats
        assert "active_sessions" in stats
