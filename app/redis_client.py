"""Async Redis client singleton for shared state across pods.

Initialised once during app startup (lifespan). Other modules call
``get_redis()`` to obtain the shared client or ``None`` when Redis is
not configured / unreachable.
"""

import logging
from typing import Optional

import redis.asyncio as aioredis

from .properties import REDIS_HOST, REDIS_PORT, REDIS_DB

logger = logging.getLogger(__name__)

_redis_client: Optional[aioredis.Redis] = None


async def init_redis() -> Optional[aioredis.Redis]:
    """Initialise and verify Redis connection.

    Call once during app startup.  Returns the client on success, or
    ``None`` when Redis is not configured or unreachable.
    """
    global _redis_client

    if not REDIS_HOST:
        logger.info("Redis not configured (REDIS_HOST not set); using in-memory state only")
        return None

    try:
        client = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        if await client.ping():
            _redis_client = client
            logger.info("Redis connected: %s:%s (db=%s)", REDIS_HOST, REDIS_PORT, REDIS_DB)
            return client
    except Exception as e:
        logger.warning("Redis unavailable (falling back to in-memory): %s", e)

    return None


def get_redis() -> Optional[aioredis.Redis]:
    """Return the shared async Redis client, or ``None`` if unavailable."""
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection. Call during app shutdown."""
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis connection closed")
