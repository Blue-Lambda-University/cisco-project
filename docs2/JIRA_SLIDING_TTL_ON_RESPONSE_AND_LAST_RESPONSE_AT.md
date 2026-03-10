# JIRA Ticket: Sliding TTL on Response & Write `last_response_at` to Redis

Copy the sections below into a new JIRA ticket (Story). Sub-tasks are listed at the end.

---

## Summary

Extend session TTL when **sending** a response (not just on request), and write a `last_response_at` timestamp to the Redis session hash — improving session reliability during long-running orchestrator calls and providing response delivery visibility.

---

## Description

**Context:** The WebSocket server (`cdcai-microsvc-uber-assistant-frontend`) uses a sliding-window TTL for sessions. Currently, `extend_ttl` is called only when an incoming request is received. This means the session's idle timer starts counting from the last **request**, not the last **response**.

### Problem 1: Session can expire while waiting for orchestrator

If the orchestrator takes a long time to respond (e.g., 25 minutes on a 30-minute idle TTL), the session could be very close to expiry by the time the response is ready. The user receives the response, but their next request a few minutes later may hit a session expired error.

This is especially critical for the async/webhook flow where the orchestrator response arrives via HTTP callback — potentially many minutes after the original request.

**Solution — Sliding TTL on response:** Call `extend_ttl(session_id)` when delivering a response to the UI, not just when receiving a request. This resets the idle timer so the user gets a full idle window from the moment they last received information.

### Problem 2: No visibility into response delivery timing

There is no record of when the backend last sent a response to the user. This makes it hard to:
- Debug "user says they never got a response" scenarios.
- Distinguish between "user was idle" (no requests) vs "backend was processing" (request received, response pending).
- Provide analytics on response latency and delivery.

**Solution — `last_response_at` in Redis:** Write a `last_response_at` timestamp to the Redis session hash each time a response is delivered. This gives a clear audit trail alongside the existing `last_activity_at` (which tracks incoming requests).

### Combined Redis session hash (after implementation)

| Field | Updated On | Description |
|-------|-----------|-------------|
| `session_id` | Create | The session ID |
| `expires_at` | Request + Response | Sliding TTL — extended on both request and response delivery |
| `created_at` | Create | When the session was first created |
| `last_activity_at` | Request | When the user last sent a message (incoming request) |
| `last_response_at` | Response | **New** — When the backend last sent a response to the user |

### Where TTL extension and `last_response_at` are triggered

| Code Path | Current TTL Extend | Proposed TTL Extend | Write `last_response_at` |
|-----------|-------------------|--------------------|-----------------------|
| `message_handler._handle_a2a_request` (on request) | Yes | Yes (no change) | No |
| `websocket.handle_connection` (before `send_text`) | No | **Yes** | **Yes** |
| `webhooks._handle_async_response` (before sending to WS) | No | **Yes** | **Yes** |

---

## Acceptance Criteria

- [ ] Session TTL is extended when delivering a response over WebSocket (synchronous path).
- [ ] Session TTL is extended when delivering a response via webhook callback (async path).
- [ ] `last_response_at` field is written to the Redis session hash on every response delivery.
- [ ] `Session` dataclass includes `last_response_at: datetime | None`.
- [ ] `RedisSessionStore.get()` reads and populates `last_response_at` from Redis.
- [ ] `SessionStore` protocol includes `record_response(session_id)` method.
- [ ] `InMemorySessionStore` implements `record_response()` (updates in-memory `Session.last_response_at` + extends TTL).
- [ ] `RedisSessionStore` implements `record_response()` (writes `last_response_at` to hash + extends TTL).
- [ ] Session store is accessible as a dependency in the webhook handler.
- [ ] Unit tests cover `record_response()` for both store implementations.
- [ ] Integration test: after a WebSocket round-trip, `last_response_at` is populated.
- [ ] No regression in existing tests.

---

## Sub-Tasks

### Sub-Task 1: Add `last_response_at` to session data model

**Description:** Add the new field to the `Session` dataclass and the Redis field constant. Update `RedisSessionStore.get()` to read it.

**Files:** `app/core/session_store.py`

**AC:**
- [ ] `REDIS_FIELD_LAST_RESPONSE_AT = "last_response_at"` constant added.
- [ ] `last_response_at: datetime | None = None` added to `Session` dataclass.
- [ ] `RedisSessionStore.get()` reads `last_response_at` from the hash and populates the field.

---

### Sub-Task 2: Add `record_response()` method to session stores

**Description:** Add a `record_response(session_id)` method that writes `last_response_at = now` and extends the session TTL. Implement in both `InMemorySessionStore` and `RedisSessionStore`, and add to the `SessionStore` protocol.

**Files:** `app/core/session_store.py`

**AC:**
- [ ] `SessionStore` protocol includes `record_response(self, session_id: str, now: datetime | None = None) -> bool`.
- [ ] `InMemorySessionStore.record_response()` updates `session.last_response_at` and calls `extend_ttl`.
- [ ] `RedisSessionStore.record_response()` writes `last_response_at` to Redis hash, calls `extend_ttl`, and updates Redis key TTL.
- [ ] Returns `True` if session was found and updated, `False` otherwise.

---

### Sub-Task 3: Extend TTL and record response on WebSocket delivery

**Description:** In the WebSocket message handling loop, after the response is built and before (or after) `send_text()`, call `session_store.record_response(session_id)`. Extract `sessionId` from the response metadata.

**Files:** `app/api/websocket.py`

**AC:**
- [ ] `session_store` is accessible in the WebSocket handler (injected via dependency).
- [ ] `record_response(session_id)` is called after building the response for `UIResponse` instances.
- [ ] `sessionId` is extracted from `UIResponse.a2a_response["metadata"]["sessionId"]`.
- [ ] Does not break non-UIResponse paths (legacy responses, async accepted).

---

### Sub-Task 4: Extend TTL and record response on webhook delivery

**Description:** In the webhook handler, after building the `UIResponse` from the orchestrator callback and before sending to the WebSocket, call `session_store.record_response(session_id)`.

**Files:** `app/api/webhooks.py`, `app/dependencies/providers.py`

**AC:**
- [ ] `session_store` is injected as a dependency in the webhook router/handler.
- [ ] `record_response(session_id)` is called after building the `UIResponse` and before sending to the WebSocket.
- [ ] `sessionId` is taken from the resolved session (already available in the handler).

---

### Sub-Task 5: Tests

**Description:** Add unit and integration tests for the new `record_response()` method and TTL extension on response delivery.

**Files:** `tests/test_session_store.py`, `tests/test_websocket_integration.py`

**AC:**
- [ ] Unit test: `record_response()` updates `last_response_at` in `InMemorySessionStore`.
- [ ] Unit test: `record_response()` calls `extend_ttl` (TTL is extended).
- [ ] Unit test: `record_response()` on expired/missing session returns `False`.
- [ ] Unit test (Redis): `record_response()` writes `last_response_at` field to Redis hash (mocked Redis).
- [ ] Integration test: WebSocket round-trip followed by checking that `session.last_response_at` is populated.
- [ ] No regression in existing tests.

---

## Labels (suggested)

`session-management`, `redis`, `websocket`, `backend`, `feature`

---

## Component

`cdcai-microsvc-uber-assistant-frontend`

---

## Story Points

(Set per your team's sizing. Suggested: 3–5 points.)

---

## Links

- Session workflow doc: `docs/SESSION_CONNECTION_WORKFLOW.md`
- Session Max Lifetime Renewal plan: `docs/SESSION_MAX_LIFETIME_RENEWAL_PLAN.md`
