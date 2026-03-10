# JIRA Ticket: Implement Session Max Lifetime Renewal Strategy

Copy the sections below into a new JIRA ticket (Story). Sub-tasks are listed at the end.

---

## Summary

Implement proactive session expiry logic so that when a session approaches its max lifetime (8 hours) and the user has been idle, the backend returns `-32404 Session expired` — prompting the UI to clear state, generate a new `conversationId`, and establish a fresh session on the next request.

---

## Description

**Context:** The WebSocket server (`cdcai-microsvc-uber-assistant-frontend`) uses a sliding-window TTL for sessions with a hard max lifetime of 8 hours. Today, when the max lifetime is reached, the session expires and the user receives a `-32404 Session expired` error — even if they were recently active or just returned to chat.

**Problem:** If a user starts or continues a conversation shortly before the 8-hour mark, their session expires mid-conversation, causing a disruptive error. The hard cap on `extend_ttl` means no further extension is possible once `created_at + max_lifetime_seconds` is reached.

**Proposed Solution — Early Expiry (Proactive `-32404`):**

When both of the following conditions are met, `extend_ttl` returns `"expired"` — triggering the existing `-32404` session expired flow:

1. The session is in the **renewal zone** — the last `idle_ttl_seconds` (30 min) before max expiry.
2. The user has been **idle** for longer than `session_renewal_idle_threshold_seconds` (configurable, default 15 min).

If the user is actively chatting when they enter the renewal zone, the session is extended normally (no disruption). Early expiry only triggers for users who were away and came back near max expiry.

**End-to-end flow:**

1. User sends message with old `sessionId`.
2. Backend detects: in renewal zone + idle duration exceeds threshold.
3. Backend returns `-32404 Session expired` (same error as natural expiry).
4. UI handles session expired: clears old `sessionId` and `conversationId`.
5. UI generates a **new `conversationId`**, resends the message with no `sessionId`.
6. Backend creates a new session, processes the message, returns response with new `sessionId`.

**Key design rules:**

- **Reuses existing `-32404` handling:** No new error codes or response formats. The UI's existing session-expired logic handles this transparently.
- **ConversationId does NOT carry over:** A `conversationId` is permanently tied to the `sessionId` it was created under. The `ws_user_conversation:{conversationId}` mapping is NOT updated. The UI must generate a new `conversationId` after receiving `-32404`.
- **Old session is not deleted:** It stays in Redis until natural expiry. The UI has already cleared the old `sessionId` and will not send it again.
- **User's message is not lost:** The UI resends it automatically after establishing the new session.

**Design document:** `docs/SESSION_MAX_LIFETIME_RENEWAL_PLAN.md` (includes full flow diagrams, decision matrix, Redis impact, edge cases, and API contract impact).

---

## Acceptance Criteria

- [ ] `extend_ttl` returns `"extended"` or `"expired"` (string) instead of `bool` — for both `InMemorySessionStore` and `RedisSessionStore`.
- [ ] Early expiry is triggered only when **both** conditions are met: session is in the renewal zone AND `(now - last_activity_at) > session_renewal_idle_threshold_seconds`.
- [ ] When early expiry is triggered, the backend returns `-32404 Session expired` — the same response as natural expiry.
- [ ] Active users in the renewal zone get `"extended"` (no disruption, no early expiry).
- [ ] The old `conversationId → sessionId` Redis mapping is NOT touched on early expiry.
- [ ] The old session stays in Redis until natural expiry (not deleted).
- [ ] New config setting `session_renewal_idle_threshold_seconds` (default 900 / 15 min) is added and respected.
- [ ] `SessionStore` protocol updated to reflect new `extend_ttl` return type.
- [ ] Unit tests cover: normal extend, early expiry triggered (idle user in zone), early expiry skipped (active user in zone), naturally expired session.
- [ ] Integration test: WebSocket round-trip where early expiry triggers `-32404`, followed by UI resend that creates a new session.
- [ ] Existing tests updated so they pass with the new `extend_ttl` return type.

---

## Sub-Tasks

### Sub-Task 1: Update `extend_ttl` return type and early expiry logic

**Description:** Change `extend_ttl` in `InMemorySessionStore`, `RedisSessionStore`, and the `SessionStore` protocol to return `str` (`"extended"` / `"expired"`). Add renewal zone + idle threshold detection logic that returns `"expired"` when both conditions are met.

**Files:** `app/core/session_store.py`

**AC:**
- [ ] `extend_ttl` returns `"extended"` when TTL is extended normally.
- [ ] `extend_ttl` returns `"expired"` when session not found, naturally expired, OR in renewal zone with idle duration exceeding threshold (early expiry).
- [ ] Active users in the renewal zone get `"extended"` (no disruption).
- [ ] Both `InMemorySessionStore` and `RedisSessionStore` implement the new logic.
- [ ] `SessionStore` protocol updated.

---

### Sub-Task 2: Add `session_renewal_idle_threshold_seconds` config

**Description:** Add the new configuration setting and wire it into both session store implementations.

**Files:** `app/config.py`, `app/dependencies/providers.py`

**AC:**
- [ ] `session_renewal_idle_threshold_seconds` added to `Settings` with default 900 (15 min).
- [ ] Passed to `InMemorySessionStore` and `RedisSessionStore` constructors.
- [ ] Overridable via environment variable (`UA_WS_SESSION_RENEWAL_IDLE_THRESHOLD_SECONDS`).

---

### Sub-Task 3: Verify message handler handles new return type

**Description:** The existing `-32404` handling in `_handle_a2a_request` already covers the `"expired"` return. Verify no changes are needed — the message handler treats early expiry identically to natural expiry.

**Files:** `app/services/message_handler.py`

**AC:**
- [ ] When `extend_ttl` returns `"expired"` (early or natural), existing `-32404` error response is sent.
- [ ] When `extend_ttl` returns `"extended"`, existing behavior is preserved (no change).
- [ ] No new branching or special handling is needed in the message handler.

---

### Sub-Task 4: Unit tests for early expiry logic

**Description:** Add unit tests for the `extend_ttl` early expiry logic in both session store implementations.

**Files:** `tests/test_session_store.py`

**AC:**
- [ ] Test: normal extend returns `"extended"`.
- [ ] Test: session in renewal zone + idle user returns `"expired"` (early expiry).
- [ ] Test: session in renewal zone + active user returns `"extended"`.
- [ ] Test: naturally expired session returns `"expired"`.
- [ ] Test: missing session returns `"expired"`.
- [ ] Tests cover both `InMemorySessionStore` and `RedisSessionStore` (mocked Redis).

---

### Sub-Task 5: Integration test for early expiry over WebSocket

**Description:** Add an integration test that simulates a WebSocket round-trip where early expiry triggers `-32404`, followed by a resend that creates a new session.

**Files:** `tests/test_websocket_integration.py`

**AC:**
- [ ] Test sends a message with a session in renewal zone and idle for longer than the threshold.
- [ ] Response is `-32404 Session expired`.
- [ ] Test resends the message with no `sessionId` and a new `conversationId`.
- [ ] Response is a normal `UIResponse` with a new `sessionId`.

---

### Sub-Task 6: Update existing tests for new `extend_ttl` return type

**Description:** Existing tests that check `extend_ttl` return values (`True`/`False`) must be updated to check for `"extended"`/`"expired"`.

**Files:** `tests/test_session_store.py`, `tests/test_websocket_integration.py`

**AC:**
- [ ] All existing tests pass with the new string return type.
- [ ] No regressions.

---

## Labels (suggested)

`session-management`, `websocket`, `redis`, `backend`, `feature`

---

## Component

`cdcai-microsvc-uber-assistant-frontend`

---

## Story Points

(Set per your team's sizing. Suggested: 3–5 points — simpler than originally scoped since it reuses existing `-32404` handling.)

---

## Links

- Design document: `docs/SESSION_MAX_LIFETIME_RENEWAL_PLAN.md`
- Session workflow doc: `docs/SESSION_CONNECTION_WORKFLOW.md`
- Session ID implementation plan: `docs/SESSION_ID_IMPLEMENTATION_PLAN.md`
