# Session ID Implementation Plan

Implementation plan for aligning WebSocket session and connection identifiers with best practices (server-issued session IDs, validation, optional persistence, and secure handling).

---

## 1. Current State

| Concept | Where | How |
|--------|--------|-----|
| **Connection ID** | `app/core/connection_manager.py` | Server-generated via `uuid.uuid4()` on connect. Used for connection lifecycle and logging. |
| **Session ID** | `app/models/messages.py` (`MessageMetadata.session_id`) | Client-supplied in every JSON message. No server validation or binding. |

**Gap:** Session ID is fully client-controlled; no server-issued option, no validation, no binding to connection or auth.

---

## 2. Goals

- Keep **connection ID** as the single identifier per WebSocket connection (no change to generation).
- Introduce **server-issued session ID** option: server can create and return a session ID (e.g. on first message or connect).
- **Validate** client-supplied session IDs (format, length, character set).
- Optionally **persist** session metadata (e.g. Redis or in-memory with TTL) for reconnect and analytics.
- **Document** and enforce clear semantics: connection ID = transport, session ID = application/session scope.
- **Security**: avoid logging full IDs where appropriate; prepare for optional auth binding later.

---

## 3. Out of Scope (for this plan)

- Full authentication/authorization (tokens, cookies).
- Production persistence choice (e.g. Redis) — plan assumes an abstract session store interface so backend can be swapped.
- UI/client changes (only contract and server behavior are specified).

---

## 4. Implementation Phases

### Phase 1: Session ID validation and model (client-supplied path)

**Objective:** Validate and normalize client-supplied `session_id` without changing who generates it.

| Task | Description | Files / Areas |
|------|-------------|----------------|
| 1.1 | Define session ID format rules (e.g. max length 256, allowed charset `[a-zA-Z0-9_-]` or similar). | `app/models/messages.py` or new `app/models/session.py` |
| 1.2 | Add validation in `MessageMetadata` (Pydantic validator or `field_validator`) for `session_id`. | `app/models/messages.py` |
| 1.3 | Return a clear validation error (e.g. `ErrorCode.INVALID_PAYLOAD` or new `ErrorCode.INVALID_SESSION_ID`) when validation fails. | `app/services/message_handler.py`, `app/models/enums.py` (if new code) |
| 1.4 | Add unit tests for valid/invalid session ID formats. | `tests/test_models.py` |

**Acceptance criteria:** Client sending an invalid `session_id` receives a structured error response; valid IDs pass through unchanged.

---

### Phase 2: Server-issued session ID (optional flow)

**Objective:** Allow the server to create a session ID and send it to the client (e.g. on first message or on connect).

| Task | Description | Files / Areas |
|------|-------------|----------------|
| 2.1 | Define a “session” concept in the server: e.g. map `connection_id` → `session_id` for the lifetime of the connection, and optionally generate `session_id` on first message if client did not send one. | `app/core/connection_manager.py` and/or new `app/core/session_manager.py` |
| 2.2 | Generate server session IDs with a CSPRNG (e.g. `secrets.token_urlsafe(32)` or keep `uuid.uuid4()`). | New helper or `ConnectionManager` / `SessionManager` |
| 2.3 | Include `session_id` in the first response to the client (e.g. in response metadata or a dedicated “session_created” message type). | `app/models/responses.py`, `app/core/response_router.py` or websocket handler |
| 2.4 | Document the contract: when the server issues a session ID, client should send it back in subsequent messages for the same logical session. | README or `docs/` |

**Acceptance criteria:** Server can generate and return a session ID; client can use it in later messages; connection ID remains separate and connection-scoped.

---

### Phase 3: Session store abstraction (optional persistence)

**Objective:** Introduce an abstract session store so session metadata can later be persisted (e.g. Redis) or kept in-memory with TTL.

| Task | Description | Files / Areas |
|------|-------------|----------------|
| 3.1 | Define a minimal `SessionStore` protocol or abstract class: e.g. `get(session_id)`, `set(session_id, data, ttl_seconds)`, `delete(session_id)`. | New `app/core/session_store.py` or `app/services/session_store.py` |
| 3.2 | Implement an in-memory store (e.g. dict + TTL or use a small library). Use it as the default. | Same module or `app/core/session_store.py` |
| 3.3 | Wire the store into the app (e.g. FastAPI dependency or `ConnectionManager` / `SessionManager`). | `app/dependencies/providers.py`, `app/config.py` (e.g. session TTL config) |
| 3.4 | On “session create” or first message, optionally write minimal session metadata (e.g. `connection_id`, `created_at`, `client_ip`) into the store. | Where session is created (Phase 2) |

**Acceptance criteria:** Sessions can be stored and retrieved by ID; default implementation is in-memory with configurable TTL; interface allows swapping to Redis later.

---

### Phase 4: Reconnect and lifecycle

**Objective:** Define behavior when the client reconnects and sends a previous session ID.

| Task | Description | Files / Areas |
|------|-------------|----------------|
| 4.1 | Document desired behavior: if client sends a valid `session_id` that exists in the store, treat it as “resumed” (e.g. same conversation/history); otherwise treat as new session. | `docs/` or README |
| 4.2 | If using the session store, on connect or first message: look up `session_id`; if found and not expired, associate new `connection_id` with existing session; otherwise create new session and return new `session_id`. | `app/core/session_manager.py` (or equivalent), websocket handler |
| 4.3 | Add configuration for session TTL (idle and/or absolute). | `app/config.py` |

**Acceptance criteria:** Reconnecting client can send previous session ID and server either resumes that session or issues a new one; TTL is configurable.

---

### Phase 5: Security and operations

**Objective:** Reduce risk of session ID misuse and improve operability.

| Task | Description | Files / Areas |
|------|-------------|----------------|
| 5.1 | Review logging: avoid logging full session/connection IDs in every line where not required; consider truncation or hashing for sensitive paths. | `app/logging/setup.py`, `app/api/websocket.py`, `app/core/connection_manager.py` |
| 5.2 | Ensure session IDs are never used alone for authorization; document that auth (if added later) will be token/cookie-based with server-side validation. | `docs/` |
| 5.3 | If session store holds PII, document retention and ensure TTL/cleanup is in place. | Config, docs |

**Acceptance criteria:** Logging and docs align with security best practices; no auth reliance on session ID alone.

---

## 5. Dependencies and Order

```
Phase 1 (validation)     → can be done first, no dependency on 2–5
Phase 2 (server-issued)   → can run in parallel with 1; needed for 4
Phase 3 (session store)  → can follow 2; needed for 4 if you want persistence
Phase 4 (reconnect)      → depends on 2 and optionally 3
Phase 5 (security)       → can be done in parallel or after 1–4
```

---

## 6. Testing Strategy

- **Unit:** Session ID validation (Phase 1); session ID generation (Phase 2); store get/set/delete and TTL (Phase 3).
- **Integration:** WebSocket flow: connect → send message with no session_id → receive response with server-issued session_id → send second message with that session_id → verify same session; then reconnect and send old session_id and verify resume vs new session (Phases 2, 4).
- **Security:** No sensitive IDs in high-volume logs; validation rejects obviously bad inputs (Phase 5).

---

## 7. Rollback

- Phase 1: Revert validation and error code; client can send any string again.
- Phase 2: Stop generating and returning server session IDs; keep client-only path.
- Phase 3: Remove store dependency; keep in-memory only or no persistence.
- Phase 4: Revert to “every connection is a new session” if needed.
- Phase 5: Revert logging/docs only.

---

## 8. Document History

| Date | Change |
|------|--------|
| (Initial) | Plan created for session ID best practices implementation. |
