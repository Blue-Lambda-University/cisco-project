# Session & Connection Workflow

This document matches the **Session & Connection Workflow** PDF and the existing `SESSION_CONNECTION_WORKFLOW.html`. Use it as the single source of truth for editing; the HTML adds Mermaid diagrams for the same content.

Workflow for handling WebSocket connections, session IDs, multiple tabs, and when to start a new session. Sessions have a **TTL (time-to-live)**; the backend uses a **sliding window** so that each valid request (and optionally ping) extends the session’s expiry—active users don’t hit expiry mid-chat. Documentation only (no code changes).

---

## 1. Connection vs session (overview)

| Concept | Description |
|--------|-------------|
| **Connection ID** | One per WebSocket (per tab). Server-generated. Lives only while the socket is open. (e.g. `websocket_connection_id`: conn-aaa, conn-bbb) |
| **Session ID** | One per logical chat. Can be shared across tabs. (e.g. `session_id`) |
| **Session TTL** | Each session has an expiry (TTL). The backend uses a **sliding window**: every valid request (and optionally WebSocket ping) extends the session’s TTL so active users don’t hit expiry mid-chat. Expired sessions are rejected; the client must clear storage and start a new session. |

**Diagram (conceptual):**

- **User:** Tab 1, Tab 2  
- **Server:** Connection A (`websocket_connection_id`: conn-aaa), Connection B (`websocket_connection_id`: conn-bbb), one **Session** (`session_id`)  
- Tab 1 → WebSocket → Connection A → Session  
- Tab 2 → WebSocket → Connection B → Session  

---

## 2. User opens first tab (initial load)

**No session_id (first visit or cleared):**

1. User opens app Tab 1.
2. Frontend checks localStorage for `session_id` — none.
3. Frontend connects WebSocket → server creates `websocket_connection_id` → connection accepted.
4. Frontend sends first message with no `session_id` or null.
5. Server creates new session (with TTL) if server-issued.
6. Response includes `session_id` if server-issued.
7. Frontend stores `session_id` (e.g. localStorage).

**Has session_id (returning user or refresh):**

1. Frontend connects WebSocket → server creates `websocket_connection_id` → connection accepted.
2. Frontend sends message with `session_id`.
3. Server looks up session, checks TTL (not expired), extends TTL (sliding window), resumes or creates new.
4. Response indicates session resumed or new.

**TTL:** When the server creates a new session, it sets an expiry (e.g. `expires_at = now + idle_ttl`). When the client sends a message with an existing `session_id`, the server validates that the session is not expired and extends its TTL (sliding window) before processing.

---

## 3. User opens another tab (shared session)

- **Tab 1:** Page load → read `session_id` from localStorage → connect WebSocket → send messages with same `session_id`.
- **Tab 2:** Page load → read **same** `session_id` from localStorage → connect WebSocket → send messages with same `session_id`.
- **Server:** Two connections (Connection A, Connection B), **one session** (same `session_id`). Each valid message extends the session’s TTL (sliding window).

**Steps:**

1. Tab 1: Connect, get or create `session_id`, store in localStorage.
2. Tab 2: On load, read same `session_id` from localStorage.
3. Tab 2: Connect (new `websocket_connection_id` on server), send messages with that `session_id`.
4. Server: Two connections, one session — each valid message extends the session’s TTL (sliding window).

---

## 4. When to reuse vs start a new session (frontend decision)

**Flow:**

- User action or page load → **Have stored session_id?**
  - **No** → Treat as new session; do not send `session_id` (or send null) → server creates/returns new `session_id` → store if needed → ready for next message.
  - **Yes** → Send existing `session_id` → server resumes or validates:
    - **OK / resumed** → Continue with same session → ready for next message.
    - **Expired / invalid** → Clear `session_id`, treat as new session → server creates new `session_id` → store if needed → ready for next message.

**Decision table:**

| Scenario | Reuse session_id? | Action |
|----------|------------------|--------|
| First visit, no stored session_id | No | Don't send (or send null); server creates new session. |
| Same tab, user keeps chatting | Yes | Send same session_id. |
| Reconnect after network drop | Yes | Send same session_id (resume). |
| User clicks "New chat" | Yes | Same session continues until server returns session expired or user logs out. |
| New tab, shared session | Yes | Read session_id from localStorage; send it. |
| Server returns "session expired" / "invalid session" | No | Clear stored session_id; next message starts new session. |
| User logs out or clears site data | No | Clear session_id; next connect is new session. |

**TTL and sliding window:** The server treats a session as valid only if it exists and is not past its `expires_at`. Each valid request extends the session’s TTL (sliding window), so active users don’t hit expiry mid-chat. When the server returns “session expired”, the frontend must clear stored `session_id` and treat the next action as a new session.

---

## 5. End-to-end: reconnect after disconnect (resume)

1. User was connected; then network drops → connection closed.
2. Frontend keeps `session_id` in storage (do not clear).
3. User still on page or reopens → frontend reads `session_id` from storage.
4. Frontend reconnects → new WebSocket connect → new `websocket_connection_id` (old one is gone) → accepted.
5. Frontend sends message with stored `session_id` (e.g. session_id sess-111).
6. Server looks up session:
   - **Session found and not expired:** Attach this connection to session, extend TTL (sliding window) → response resumed, same history and context.
   - **Session not found or expired:** Error or new session (e.g. session_expired) → frontend clears `session_id`, treats as new session.

**TTL:** The server looks up the session and checks that it has not expired (e.g. `now < expires_at`). If valid, it extends the session’s TTL (sliding window) and resumes. If expired or missing, the server returns session_expired (or equivalent); the frontend clears storage and starts fresh.

---

## 6. Summary diagram (all paths)

| Entry points | Frontend decision | Action | Server |
|--------------|------------------|--------|--------|
| First tab load | Have session_id? No | Send no session_id | New websocket_connection_id every time; new or resumed session by session_id, validate TTL, extend sliding window |
| New tab load | Shared session across tabs? Yes | Send stored session_id | Same |
| Reconnect after disconnect | Have session_id? Yes / No | Send stored session_id or clear then send no session_id | Same |
| User: New chat (UI only) | — | Send stored session_id (same session until expired) | Same |

---

## 7. Edge cases

This section details **TTL and sliding window** behaviour referenced earlier in the document.

### 7.1 Extending session TTL near end of session (sliding window)

Every request (and optionally WebSocket ping) that carries a valid session ID extends the session’s TTL (e.g. +30 min from now) so active users don’t hit expiry mid-chat. **Backend:** on each valid request, update the session’s `expires_at` in the store. Optionally cap with a max lifetime (e.g. 8h).

### 7.2 Request in flight when session ends

If the session expires while the backend is processing: validate session when the request is accepted; optionally re-check when sending the response. If expired at response time, return a dedicated **session_expired** instead of the normal payload. **Client:** on session_expired, clear session ID (memory + localStorage), show a message, and treat the next action as a new session. Do not retry with the old session ID.

---

## 8. Implementation steps

### Backend: Sliding-window TTL

1. Add a session store with at least `session_id`, `expires_at`; optionally `created_at`, `last_activity_at`, max lifetime.
2. Add config: idle TTL (e.g. 30 min), optional max session lifetime (e.g. 8h).
3. In the request path, after parsing the message: read the session ID from the request (e.g. message metadata).
4. If no session ID: create a new session ID.
5. If session ID present: look up the session in the store.
6. If session expired: return a dedicated **session_expired** and do not process the message.
7. If session missing: return a dedicated **session_missing** and do not process the message.
8. If session valid: update the store so this session’s expiry is extended (e.g. `expires_at = now + idle_ttl`), respecting max lifetime if configured.
9. Then process the message and send the response.
10. When creating a new session: create an entry in the store with `expires_at = now + idle_ttl`.
11. Optional: treat WebSocket ping as activity and extend TTL the same way.

### Contract (backend and frontend)

1. Agree where the client sends the session ID (e.g. message metadata field name).
2. Agree where the server returns the new session ID (e.g. response metadata field name).
3. Agree the exact shape of the “session expired” response so the frontend can detect it and clear storage.
