# JIRA Ticket: WebSocket Timeout & Heartbeat

Copy the sections below into a new JIRA ticket (Story). Sub-tasks are listed at the end.

---

## Summary

Implement WebSocket heartbeat (server-side ping), dead connection detection, and orchestrator response timeout to ensure connections stay alive through infrastructure proxies and stale/orphaned requests are cleaned up.

---

## Description

**Context:** With the async orchestrator flow, the backend forwards user messages to the orchestrator and the UI receives nothing until the orchestrator calls our webhook back. There are several failure modes that are currently unhandled:

**Problem 1 — Dead connections go undetected:**
The WebSocket connection has no heartbeat. If a client silently disconnects (network drop, browser crash, mobile sleep), the server won't know until it tries to send. Meanwhile, correlation store entries for that connection remain in memory, and webhook responses fail to deliver.

**Problem 2 — Infrastructure proxies kill idle connections:**
Kubernetes ingress controllers, Istio sidecars, and load balancers commonly have idle connection timeouts (often 60–120 seconds). During the async flow, the WebSocket is silent while waiting for the orchestrator — a proxy may close the connection for being idle, breaking the flow.

**Problem 3 — Orchestrator never responds:**
If the orchestrator accepts the request but never calls the webhook (crash, bug, network partition), the UI waits forever. The `PendingAsyncRequest` entry in the correlation store is never cleaned up, leaking memory.

**Problem 4 — Orchestrator responds after client disconnects:**
The orchestrator calls the webhook, but the WebSocket is already gone. The webhook returns 503. The correlation store entry is consumed, but the user never gets the response.

---

## Proposed Design

### A. Server-Side Heartbeat (Ping/Pong)

The server sends a periodic `ping` message to each connected client. The client is expected to reply with a `pong`. If no pong is received within a configurable timeout, the server closes the connection.

**Flow:**

```
Server                          Client
  │                               │
  ├── {"type": "ping"} ─────────>│
  │                               ├── {"type": "pong"} ──>│
  │  (client alive, reset timer)  │
  │                               │
  │  ... 20 seconds later ...     │
  │                               │
  ├── {"type": "ping"} ─────────>│
  │                               │  (no pong within 10s)
  │  close connection ────────────X
```

**Implementation:**

- Background `asyncio.Task` per connection, created in `handle_connection()`
- Sends `{"type": "ping"}` every `heartbeat_interval_seconds` (default: 20s)
- Tracks `last_pong_at` timestamp; if no pong within `heartbeat_timeout_seconds` (default: 10s), close connection
- The message loop recognizes incoming `{"type": "pong"}` and updates `last_pong_at`
- Task is cancelled in the `finally` block when the connection closes

**Config:**

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `heartbeat_interval_seconds` | `UA_WS_HEARTBEAT_INTERVAL_SECONDS` | `20` | How often to send ping |
| `heartbeat_timeout_seconds` | `UA_WS_HEARTBEAT_TIMEOUT_SECONDS` | `10` | Max wait for pong before closing |

**Why application-level ping (not WebSocket protocol ping frames)?**
- FastAPI/Starlette doesn't expose a clean API for protocol-level ping frames
- Application-level pings are visible in logs and easier to debug
- The UI can easily handle `{"type": "ping"}` in its message handler

### B. Correlation Store TTL & Sweep

Each `PendingAsyncRequest` gets a `created_at` timestamp. A background sweep task periodically checks for expired entries and sends a timeout error to the UI.

**Flow:**

```
t=0s    Backend stores PendingAsyncRequest (created_at = now)
t=0s    Backend POSTs to orchestrator → accepted
        ... UI waiting ...
t=60s   Sweep task runs, finds entry older than async_response_timeout_seconds
t=60s   Sends timeout error to UI via WebSocket:
        {"jsonrpc":"2.0", "id":"req-abc-123", "error":{"code":-32408, "message":"Request timed out waiting for orchestrator response"}}
t=60s   Removes entry from correlation store
```

**Implementation:**

- Add `created_at: float` field to `PendingAsyncRequest` (using `time.monotonic()`)
- Background `asyncio.Task` started in the application lifespan (`app/main.py`)
- Runs every `sweep_interval_seconds` (e.g., 15s)
- For each expired entry:
  - Attempt to send a JSON-RPC error (`-32408 Request timeout`) to the UI via `ConnectionManager`
  - Remove from correlation store regardless of send success
- Task is cancelled on shutdown

**Config:**

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `async_response_timeout_seconds` | `UA_WS_ASYNC_RESPONSE_TIMEOUT_SECONDS` | `60` | Max wait for orchestrator webhook callback |

**Error response sent to UI on timeout:**

```json
{
  "jsonrpc": "2.0",
  "id": "req-abc-123",
  "error": {
    "code": -32408,
    "message": "Request timed out waiting for orchestrator response",
    "data": {
      "timeoutSeconds": 60
    }
  }
}
```

### C. Graceful Task Cleanup

- Heartbeat task is cancelled in `handle_connection()` `finally` block
- Sweep task is cancelled in the application lifespan shutdown
- Connection cleanup removes any correlation store entries tied to that connection (prevents zombie entries after disconnect)

---

## Acceptance Criteria

### Heartbeat
- [ ] Server sends `{"type": "ping"}` to each connected client every `heartbeat_interval_seconds`.
- [ ] Server tracks `last_pong_at` per connection; if no `{"type": "pong"}` received within `heartbeat_timeout_seconds`, connection is closed.
- [ ] Incoming `{"type": "pong"}` messages are handled in the message loop (not forwarded to message handler).
- [ ] Heartbeat task is cancelled cleanly on disconnect.
- [ ] `heartbeat_interval_seconds` and `heartbeat_timeout_seconds` are configurable via env vars.

### Correlation Store Timeout
- [ ] `PendingAsyncRequest` records `created_at` timestamp.
- [ ] Background sweep task runs periodically and removes entries older than `async_response_timeout_seconds`.
- [ ] For expired entries, a `-32408` timeout error is sent to the UI via WebSocket (if connection is still open).
- [ ] Sweep task starts on application startup and stops on shutdown.
- [ ] `async_response_timeout_seconds` is configurable via env var.

### Cleanup
- [ ] When a WebSocket disconnects, any pending correlation store entries for that connection are cleaned up.
- [ ] Heartbeat task does not leak on disconnect (no orphaned tasks).
- [ ] Sweep task does not leak on application shutdown.

### Tests
- [ ] Unit test: heartbeat sends ping at configured interval.
- [ ] Unit test: connection closed when pong not received within timeout.
- [ ] Unit test: correlation store entry is removed after TTL.
- [ ] Unit test: timeout error sent to UI for expired entries.
- [ ] Integration test: WebSocket stays alive during long orchestrator wait (heartbeat keeps it open).

---

## Sub-Tasks

### Sub-Task 1: Add config settings

**Description:** Add heartbeat and timeout config values to `Settings`.

**Files:** `app/config.py`, `config/cdcai-microsvc-uber-assistant-frontend-deployment-stg.yaml`

**AC:**
- [ ] `heartbeat_interval_seconds: int` added (default: 20).
- [ ] `heartbeat_timeout_seconds: int` added (default: 10).
- [ ] `async_response_timeout_seconds: int` added (default: 60).
- [ ] ConfigMap updated with `UA_WS_HEARTBEAT_INTERVAL_SECONDS`, `UA_WS_HEARTBEAT_TIMEOUT_SECONDS`, `UA_WS_ASYNC_RESPONSE_TIMEOUT_SECONDS`.

---

### Sub-Task 2: Implement server-side heartbeat

**Description:** Add a per-connection heartbeat task that sends pings and monitors for pong responses. Close the connection if the client doesn't respond.

**Files:** `app/api/websocket.py`

**AC:**
- [ ] Background `asyncio.Task` created per connection in `handle_connection()`.
- [ ] Sends `{"type": "ping"}` every `heartbeat_interval_seconds`.
- [ ] Tracks `last_pong_at`; closes connection if pong not received within `heartbeat_timeout_seconds`.
- [ ] Message loop detects `{"type": "pong"}` and updates `last_pong_at` (skips message handler).
- [ ] Task cancelled in `finally` block.
- [ ] Errors in heartbeat task don't crash the connection.

---

### Sub-Task 3: Correlation store TTL and sweep task

**Description:** Add `created_at` to `PendingAsyncRequest`. Implement a background sweep task that removes expired entries and sends timeout errors to the UI.

**Files:** `app/core/correlation_store.py`, `app/main.py`

**AC:**
- [ ] `created_at: float` added to `PendingAsyncRequest` (set to `time.monotonic()` on creation).
- [ ] `get_expired(timeout_seconds) -> list[tuple[str, PendingAsyncRequest]]` method added to `CorrelationStore`.
- [ ] Background sweep task started in application lifespan.
- [ ] Expired entries: send `-32408` error to UI via `ConnectionManager`, then remove from store.
- [ ] Sweep task cancelled on shutdown.

---

### Sub-Task 4: Connection disconnect cleanup

**Description:** When a WebSocket disconnects, clean up any pending correlation store entries for that connection to prevent orphaned entries.

**Files:** `app/api/websocket.py`, `app/core/correlation_store.py`

**AC:**
- [ ] `remove_by_connection(connection_id) -> list[str]` method added to `CorrelationStore`.
- [ ] Called in `handle_connection()` `finally` block after `connection_manager.disconnect()`.
- [ ] Logged: which `requestId`s were orphaned.

---

### Sub-Task 5: Tests

**Description:** Unit and integration tests for heartbeat and timeout behavior.

**Files:** `tests/test_websocket_integration.py`, `tests/test_correlation_store.py` (new)

**AC:**
- [ ] Unit test: `PendingAsyncRequest` records `created_at`.
- [ ] Unit test: `get_expired()` returns entries older than timeout.
- [ ] Unit test: `remove_by_connection()` removes correct entries.
- [ ] Integration test: server sends ping messages on schedule.
- [ ] Integration test: connection closed when pong timeout exceeded.
- [ ] Integration test: timeout error sent to UI when orchestrator doesn't respond.

---

## Labels (suggested)

`websocket`, `timeout`, `heartbeat`, `reliability`, `backend`, `feature`

---

## Component

`cdcai-microsvc-uber-assistant-frontend`

---

## Story Points

(Set per your team's sizing. Suggested: 5 points.)

---

## Links

- Current WebSocket handler: `app/api/websocket.py`
- Correlation store: `app/core/correlation_store.py`
- Orchestrator integration ticket: `docs/JIRA_ORCHESTRATOR_INTEGRATION.md`
