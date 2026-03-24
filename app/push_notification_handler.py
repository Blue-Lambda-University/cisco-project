"""Webhook routing for async sub-agent push notifications.

Conversation-centric design: delivery config (frontend_async_push_url,
live-agent mode) is stored per *conversation* in a Redis Hash, registered
eagerly before the sub-agent stream starts.  A lightweight task index maps
each sub_agent_task_id back to a conversation so webhooks resolve in O(1).

Supports Redis-backed shared state for multi-pod deployments.
Falls back to in-memory-only when Redis is unavailable.
"""

import asyncio
import json
import logging
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from a2a.types import TaskStatusUpdateEvent, TaskArtifactUpdateEvent, Task

from .oauth2_client import OAuth2Client
from .properties import (
    REDIS_TTL_TASK_MAPPING,
    REDIS_TTL_PENDING_WEBHOOK,
)

logger = logging.getLogger(__name__)

_KEY_CONV = "orchestration:conv:"
_KEY_TASK = "orchestration:task:"
_KEY_PENDING = "orchestration:pending:"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ConversationRecord:
    """Per-conversation delivery config.  Registered eagerly before the
    sub-agent stream starts so webhook routing always has a target."""
    conversation_id: str
    frontend_async_push_url: Optional[str] = None
    orchestration_task_id: str = ""
    request_id: str = ""
    session_id: str = ""
    routed_agent: Optional[str] = None
    live_agent_mode: bool = False
    pending_subagent_task_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class TaskRecord:
    """Lightweight reverse index: sub-agent task -> conversation + orch task."""
    sub_agent_task_id: str
    conversation_id: str
    orchestration_task_id: str
    routed_agent: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ForwardResult:
    """Result of forwarding a push notification to the caller."""
    status: str  # forwarded | buffered | undeliverable | delivery_failed
    detail: str


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_conversation(rec: ConversationRecord) -> dict:
    """Serialize to a flat dict suitable for Redis HSET."""
    return {
        "frontend_async_push_url": rec.frontend_async_push_url or "",
        "orchestration_task_id": rec.orchestration_task_id,
        "request_id": rec.request_id,
        "session_id": rec.session_id,
        "routed_agent": rec.routed_agent or "",
        "live_agent_mode": "1" if rec.live_agent_mode else "0",
        "pending_subagent_task_id": rec.pending_subagent_task_id or "",
        "created_at": rec.created_at.isoformat(),
        "updated_at": rec.updated_at.isoformat(),
    }


def _deserialize_conversation(conversation_id: str, data: dict) -> ConversationRecord:
    """Deserialize Redis Hash fields to ConversationRecord."""
    return ConversationRecord(
        conversation_id=conversation_id,
        frontend_async_push_url=data.get("frontend_async_push_url") or None,
        orchestration_task_id=data.get("orchestration_task_id", ""),
        request_id=data.get("request_id", ""),
        session_id=data.get("session_id", ""),
        routed_agent=data.get("routed_agent") or None,
        live_agent_mode=data.get("live_agent_mode") == "1",
        pending_subagent_task_id=data.get("pending_subagent_task_id") or None,
        created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
        updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
    )


def _serialize_task(rec: TaskRecord) -> str:
    """Serialize TaskRecord to JSON string for Redis."""
    return json.dumps({
        "sub_agent_task_id": rec.sub_agent_task_id,
        "conversation_id": rec.conversation_id,
        "orchestration_task_id": rec.orchestration_task_id,
        "routed_agent": rec.routed_agent,
        "created_at": rec.created_at.isoformat(),
    })


def _deserialize_task(raw: str) -> TaskRecord:
    """Deserialize JSON string from Redis to TaskRecord."""
    d = json.loads(raw)
    return TaskRecord(
        sub_agent_task_id=d["sub_agent_task_id"],
        conversation_id=d["conversation_id"],
        orchestration_task_id=d["orchestration_task_id"],
        routed_agent=d.get("routed_agent", ""),
        created_at=datetime.fromisoformat(d["created_at"]) if d.get("created_at") else datetime.now(),
    )


def _event_to_dict(event) -> dict:
    """Normalize an event to a JSON-serializable dict."""
    if isinstance(event, dict):
        return event
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json")
    if hasattr(event, "dict"):
        return event.dict()
    return {"raw": str(event)}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class PushNotificationRouter:
    """Routes incoming push notifications from sub-agents to original callers.

    State is persisted to Redis (when configured) for cross-pod routing
    and crash recovery.  In-memory dicts serve as a local write-through
    cache and fallback when Redis is unreachable.
    """

    def __init__(
        self,
        httpx_client: Optional[httpx.AsyncClient] = None,
        frontend_async_push_url: Optional[str] = None,
    ):
        self.httpx_client = httpx_client or httpx.AsyncClient()
        self.oauth2_client = OAuth2Client(httpx_client=self.httpx_client)
        self.frontend_async_push_url = frontend_async_push_url

        self._conversations: Dict[str, ConversationRecord] = {}
        self._tasks: Dict[str, TaskRecord] = {}
        self.pending_webhooks: Dict[str, list] = {}

    @staticmethod
    def _get_redis():
        """Return the shared Redis client (or None)."""
        from .redis_client import get_redis
        return get_redis()

    # ------------------------------------------------------------------
    # Conversation registration and lookup
    # ------------------------------------------------------------------

    async def register_conversation(
        self,
        conversation_id: str,
        orchestration_task_id: str,
        frontend_async_push_url: Optional[str] = None,
        routed_agent: Optional[str] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """Register (or update) conversation-level delivery config.

        Called eagerly *before* the sub-agent stream starts so that
        webhook routing always has a target, even if sub_agent_task_id
        is never extracted.
        """
        if not conversation_id:
            return

        existing = self._conversations.get(conversation_id)
        now = datetime.now()
        rec = ConversationRecord(
            conversation_id=conversation_id,
            frontend_async_push_url=frontend_async_push_url or (existing.frontend_async_push_url if existing else None),
            orchestration_task_id=orchestration_task_id,
            request_id=request_id or (existing.request_id if existing else ""),
            session_id=session_id or (existing.session_id if existing else ""),
            routed_agent=routed_agent or (existing.routed_agent if existing else None),
            live_agent_mode=existing.live_agent_mode if existing else False,
            pending_subagent_task_id=existing.pending_subagent_task_id if existing else None,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._conversations[conversation_id] = rec

        rc = self._get_redis()
        if rc:
            try:
                key = f"{_KEY_CONV}{conversation_id}"
                await rc.hset(key, mapping=_serialize_conversation(rec))
                await rc.expire(key, REDIS_TTL_TASK_MAPPING)
            except Exception as e:
                logger.warning("Redis register_conversation failed: %s", e)

        logger.info(
            "Registered conversation: %s (orch_task=%s, agent=%s)",
            conversation_id, orchestration_task_id, routed_agent,
        )

    async def get_conversation(self, conversation_id: str) -> Optional[ConversationRecord]:
        """Look up conversation delivery config.  Populates local cache on
        Redis hit (read-through)."""
        if not conversation_id:
            return None

        rc = self._get_redis()
        if rc:
            try:
                data = await rc.hgetall(f"{_KEY_CONV}{conversation_id}")
                if data:
                    rec = _deserialize_conversation(conversation_id, data)
                    self._conversations[conversation_id] = rec
                    return rec
            except Exception as e:
                logger.warning("Redis get_conversation failed: %s", e)

        return self._conversations.get(conversation_id)

    # ------------------------------------------------------------------
    # Live-agent mode (stored in conversation Hash)
    # ------------------------------------------------------------------

    async def set_live_agent_mode(self, conversation_id: str, value: bool) -> None:
        """Mark a conversation as in or out of live agent (async) mode."""
        if not conversation_id:
            return

        existing = self._conversations.get(conversation_id)
        if existing:
            existing.live_agent_mode = value
            existing.updated_at = datetime.now()
        else:
            self._conversations[conversation_id] = ConversationRecord(
                conversation_id=conversation_id,
                live_agent_mode=value,
            )

        rc = self._get_redis()
        if rc:
            try:
                key = f"{_KEY_CONV}{conversation_id}"
                await rc.hset(key, "live_agent_mode", "1" if value else "0")
                await rc.expire(key, REDIS_TTL_TASK_MAPPING)
            except Exception as e:
                logger.warning("Redis set_live_agent_mode failed: %s", e)

        action = "Set" if value else "Cleared"
        logger.debug("%s live_agent_mode for conversation_id=%s", action, conversation_id[:16])

    async def get_live_agent_mode(self, conversation_id: str) -> bool:
        """Return True if this conversation is in live agent mode."""
        if not conversation_id:
            return False

        rc = self._get_redis()
        if rc:
            try:
                val = await rc.hget(f"{_KEY_CONV}{conversation_id}", "live_agent_mode")
                if val is not None:
                    return val == "1"
            except Exception as e:
                logger.warning("Redis get_live_agent_mode failed: %s", e)

        existing = self._conversations.get(conversation_id)
        return existing.live_agent_mode if existing else False

    # ------------------------------------------------------------------
    # Pending interrupt (input-required sub-agent task)
    # ------------------------------------------------------------------

    async def set_pending_interrupt(
        self, conversation_id: str, subagent_task_id: str,
    ) -> None:
        """Record that a sub-agent task is paused (input-required).

        Only ``pending_subagent_task_id`` is stored on the conversation;
        the context_id and agent name are derived from the existing
        ``TaskRecord`` on resume via :meth:`get_pending_interrupt`.
        """
        if not conversation_id or not subagent_task_id:
            return

        existing = self._conversations.get(conversation_id)
        if existing:
            existing.pending_subagent_task_id = subagent_task_id
            existing.updated_at = datetime.now()
        else:
            self._conversations[conversation_id] = ConversationRecord(
                conversation_id=conversation_id,
                pending_subagent_task_id=subagent_task_id,
            )

        rc = self._get_redis()
        if rc:
            try:
                key = f"{_KEY_CONV}{conversation_id}"
                await rc.hset(key, "pending_subagent_task_id", subagent_task_id)
                await rc.expire(key, REDIS_TTL_TASK_MAPPING)
            except Exception as e:
                logger.warning("Redis set_pending_interrupt failed: %s", e)

        logger.info(
            "Set pending interrupt for conversation %s -> sub-agent task %s",
            conversation_id[:16], subagent_task_id[:16],
        )

    async def get_pending_interrupt(
        self, conversation_id: str,
    ) -> "tuple[str, str, str] | None":
        """Return ``(subagent_task_id, context_id, sub_agent_name)`` if this
        conversation has a pending interrupt, else ``None``.

        The ``context_id`` and ``sub_agent_name`` are derived from the
        existing ``TaskRecord`` for the paused task.  If the TaskRecord
        has expired the interrupt is treated as stale and cleared.
        """
        if not conversation_id:
            return None

        pending_id: str | None = None

        rc = self._get_redis()
        if rc:
            try:
                val = await rc.hget(f"{_KEY_CONV}{conversation_id}", "pending_subagent_task_id")
                if val:
                    pending_id = val
            except Exception as e:
                logger.warning("Redis get_pending_interrupt failed: %s", e)

        if not pending_id:
            existing = self._conversations.get(conversation_id)
            if existing:
                pending_id = existing.pending_subagent_task_id

        if not pending_id:
            return None

        task_rec = await self.get_task(pending_id)
        if not task_rec:
            logger.warning(
                "Pending interrupt task %s expired (TaskRecord gone); clearing interrupt",
                pending_id[:16],
            )
            await self.clear_pending_interrupt(conversation_id)
            return None

        return (
            pending_id,
            task_rec.orchestration_task_id,
            task_rec.routed_agent,
        )

    async def clear_pending_interrupt(self, conversation_id: str) -> None:
        """Remove the pending interrupt marker from a conversation."""
        if not conversation_id:
            return

        existing = self._conversations.get(conversation_id)
        if existing:
            existing.pending_subagent_task_id = None
            existing.updated_at = datetime.now()

        rc = self._get_redis()
        if rc:
            try:
                key = f"{_KEY_CONV}{conversation_id}"
                await rc.hset(key, "pending_subagent_task_id", "")
                await rc.expire(key, REDIS_TTL_TASK_MAPPING)
            except Exception as e:
                logger.warning("Redis clear_pending_interrupt failed: %s", e)

        logger.debug("Cleared pending interrupt for conversation %s", conversation_id[:16])

    # ------------------------------------------------------------------
    # Task registration and lookup
    # ------------------------------------------------------------------

    async def register_task(
        self,
        sub_agent_task_id: str,
        conversation_id: str,
        orchestration_task_id: str,
        routed_agent: str = "",
    ) -> None:
        """Register the sub-agent task -> conversation reverse index.

        Called after extracting sub_agent_task_id from the SSE stream,
        or auto-registered when a webhook arrives for an unknown task
        but a known conversation.
        """
        rec = TaskRecord(
            sub_agent_task_id=sub_agent_task_id,
            conversation_id=conversation_id,
            orchestration_task_id=orchestration_task_id,
            routed_agent=routed_agent,
        )
        self._tasks[sub_agent_task_id] = rec

        rc = self._get_redis()
        if rc:
            try:
                await rc.set(
                    f"{_KEY_TASK}{sub_agent_task_id}",
                    _serialize_task(rec),
                    ex=REDIS_TTL_TASK_MAPPING,
                )
            except Exception as e:
                logger.warning("Redis register_task failed: %s", e)

        logger.info(
            "Registered task: %s -> conv=%s (orch=%s, agent=%s)",
            sub_agent_task_id, conversation_id, orchestration_task_id, routed_agent,
        )

        await self._replay_pending(sub_agent_task_id)

    async def get_task(self, sub_agent_task_id: str) -> Optional[TaskRecord]:
        """Look up task record.  Populates local cache on Redis hit."""
        if not sub_agent_task_id:
            return None

        rc = self._get_redis()
        if rc:
            try:
                raw = await rc.get(f"{_KEY_TASK}{sub_agent_task_id}")
                if raw:
                    rec = _deserialize_task(raw)
                    self._tasks[sub_agent_task_id] = rec
                    return rec
            except Exception as e:
                logger.warning("Redis get_task failed: %s", e)

        return self._tasks.get(sub_agent_task_id)

    # ------------------------------------------------------------------
    # Pending webhook buffering and replay
    # ------------------------------------------------------------------

    async def _buffer_event(self, sub_agent_task_id: str, event_dict: dict) -> None:
        """Buffer an event for later replay when task record is registered."""
        if sub_agent_task_id not in self.pending_webhooks:
            self.pending_webhooks[sub_agent_task_id] = []
        self.pending_webhooks[sub_agent_task_id].append(event_dict)

        rc = self._get_redis()
        if rc:
            try:
                await rc.rpush(
                    f"{_KEY_PENDING}{sub_agent_task_id}",
                    json.dumps(event_dict),
                )
                await rc.expire(
                    f"{_KEY_PENDING}{sub_agent_task_id}",
                    REDIS_TTL_PENDING_WEBHOOK,
                )
            except Exception as e:
                logger.warning("Redis buffer_event failed: %s", e)

    async def _replay_pending(self, sub_agent_task_id: str) -> None:
        """Replay buffered events after a task record is registered."""
        redis_events: List[dict] = []
        local_events: List[dict] = self.pending_webhooks.pop(sub_agent_task_id, [])

        rc = self._get_redis()
        if rc:
            try:
                raw_events = await rc.lrange(
                    f"{_KEY_PENDING}{sub_agent_task_id}", 0, -1,
                )
                await rc.delete(f"{_KEY_PENDING}{sub_agent_task_id}")
                redis_events = [json.loads(e) for e in raw_events]
            except Exception as e:
                logger.warning("Redis replay_pending read failed: %s", e)

        seen = set()
        merged: List[dict] = []
        for ev in redis_events + local_events:
            key = json.dumps(ev, sort_keys=True)
            if key not in seen:
                seen.add(key)
                merged.append(ev)

        if merged:
            logger.info(
                "Replaying %d pending webhooks for task %s",
                len(merged), sub_agent_task_id,
            )
            for event in merged:
                asyncio.create_task(
                    self.forward_notification(event, sub_agent_task_id=sub_agent_task_id)
                )

    # ------------------------------------------------------------------
    # Forward notification
    # ------------------------------------------------------------------

    async def forward_notification(
        self,
        event: TaskStatusUpdateEvent | TaskArtifactUpdateEvent | Task | dict,
        sub_agent_task_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> ForwardResult:
        """Forward a push notification from a sub-agent to the original caller.

        Resolution order:
        1. Look up TaskRecord by *sub_agent_task_id* to find the conversation.
        2. Look up ConversationRecord by *conversation_id* for delivery config.
        3. If conversation is known but task is not, auto-register the task
           so subsequent webhooks for this task resolve in O(1).
        4. If neither task nor conversation is known, buffer the event.
        5. Deliver to ``ConversationRecord.frontend_async_push_url`` or fall back
           to ``self.frontend_async_push_url``.
        """
        task_rec: Optional[TaskRecord] = None
        conv: Optional[ConversationRecord] = None

        if sub_agent_task_id:
            task_rec = await self.get_task(sub_agent_task_id)
            if task_rec:
                conversation_id = conversation_id or task_rec.conversation_id

        if conversation_id:
            conv = await self.get_conversation(conversation_id)

        if not task_rec and sub_agent_task_id and conv:
            await self.register_task(
                sub_agent_task_id=sub_agent_task_id,
                conversation_id=conv.conversation_id,
                orchestration_task_id=conv.orchestration_task_id,
                routed_agent=conv.routed_agent or "",
            )
            task_rec = await self.get_task(sub_agent_task_id)

        if not conv:
            if sub_agent_task_id:
                logger.info(
                    "No conversation or task record for %s, buffering webhook",
                    sub_agent_task_id,
                )
                await self._buffer_event(sub_agent_task_id, _event_to_dict(event))
                return ForwardResult("buffered", "Queued for replay when task registers")

            return ForwardResult(
                "undeliverable",
                "No delivery URL configured. Set FRONTEND_ASYNC_PUSH_URL.",
            )

        request_id = conv.request_id
        transformed_event = self._transform_event(
            event, request_id, conv.conversation_id, session_id=conv.session_id,
        )

        delivery_url = conv.frontend_async_push_url or self.frontend_async_push_url
        if not delivery_url:
            logger.warning(
                "No delivery URL for push notification (task=%s conversation=%s). "
                "Set FRONTEND_ASYNC_PUSH_URL.",
                sub_agent_task_id,
                conversation_id,
            )
            return ForwardResult(
                "undeliverable",
                "No delivery URL configured. Set FRONTEND_ASYNC_PUSH_URL.",
            )

        try:
            headers = await self.oauth2_client.get_auth_headers()
            headers["Content-Type"] = "application/json"

            inner = transformed_event.get("body", transformed_event) if isinstance(transformed_event, dict) else {}
            logger.info(
                "Forwarding to frontend: url=%s requestId=%s contextId=%s sessionId=%s",
                delivery_url[:80],
                inner.get("requestId", "?"),
                inner.get("contextId", "?"),
                inner.get("sessionId", "?"),
            )

            response = await self.httpx_client.post(
                delivery_url,
                json=transformed_event,
                headers=headers,
                timeout=15.0,
            )

            if response.status_code in (200, 201, 202, 204):
                logger.info(
                    "Forwarded notification to %s (task=%s conversation=%s)",
                    delivery_url[:60],
                    sub_agent_task_id,
                    conversation_id,
                )
                conv.updated_at = datetime.now()
                return ForwardResult("forwarded", f"Delivered to {delivery_url}")

            logger.warning(
                "Caller delivery returned %s: %s",
                response.status_code,
                response.text[:200] if response.text else "",
            )
            return ForwardResult(
                "delivery_failed",
                f"Downstream returned {response.status_code}",
            )

        except Exception as e:
            logger.error("Error forwarding notification: %s", e, exc_info=True)
            return ForwardResult("delivery_failed", str(e))

    @staticmethod
    def _transform_event(
        event: TaskStatusUpdateEvent | TaskArtifactUpdateEvent | Task | dict,
        request_id: str,
        conversation_id: str,
        session_id: str = "",
    ) -> dict:
        """Build the payload the frontend WebSocket server expects.

        The ``output`` value from the relay webhook is passed through as-is
        in the ``content`` field.  ``request_id`` is the frontend's original
        correlation key so it can look up the WebSocket connection.
        """
        event_dict = _event_to_dict(event)
        return {
            "body": {
                "requestId": request_id,
                "content": event_dict.get("output"),
                "sessionId": session_id,
                "contextId": conversation_id,
                "CP_GUTC_Id": "",
                "referrer": "",
            }
        }
