# JIRA Ticket: Orchestrator Integration (Async Flow)

Copy the sections below into a new JIRA ticket (Story). Sub-tasks are listed at the end.

---

## Summary

Enable the WebSocket server to forward A2A user messages to the orchestrator via an async flow, controlled by the deployment-level `async_flow_enabled` config flag and `agent_base_url` setting. The orchestrator responds asynchronously via a webhook, and the backend delivers the result to the UI over the WebSocket.

---

## Description

**Context:** The WebSocket server (`cdcai-microsvc-uber-assistant-frontend`) currently returns canned responses for all A2A queries. For integration testing, staging, and production, we need the ability to forward requests to the real orchestrator and return its response to the UI over the WebSocket.

**Routing logic:**

```
Incoming A2A message
   │
   ├── is_first_chat? → YES → canned welcome (always local)
   │
   └── NO
        │
        ├── async_flow_enabled=True + agent_base_url set → forward to orchestrator
        │
        └── otherwise → canned response
```

**Decision:** Routing is a deployment-level decision via config, not per-message. No `useOrchestrator` flag in the request metadata. When `async_flow_enabled=True` and `agent_base_url` is configured, ALL non-welcome A2A messages are forwarded to the orchestrator.

**End-to-end flow:**

```
1. UI sends WebSocket message (JSON-RPC method: message/send)

2. Backend:
   a. Validates/creates session
   b. If first chat → return canned welcome
   c. If async_flow_enabled + agent_base_url → forward to orchestrator:
      - Store requestId → connectionId mapping in correlation store
      - POST to {agent_base_url}/async/request
      - Return "in_progress" acknowledgement to UI
   d. Otherwise → canned response

3. Orchestrator processes the request, then:
   - POST result to /ciscoua/api/v1/ws/async/response

4. Backend webhook handler:
   - Look up requestId in correlation store
   - Build UIResponse from orchestrator content
   - Send UIResponse over WebSocket to the correct connection
```

**Config settings:**

| Setting | Default | Description |
|---------|---------|-------------|
| `async_flow_enabled` | `False` | Enable forwarding to orchestrator |
| `agent_base_url` | `http://cdcai-microsvc-uber-assistant-orchestration-agent-svc.ns-qry-aiml-stg-api.svc.cluster.local:8006` | Orchestrator base URL |

**Correlation key:** `requestId` from the UI (JSON-RPC `id` field). If null, backend generates a UUID fallback. The orchestrator echoes `requestId` in its webhook callback.

**Webhook path:** `POST /ciscoua/api/v1/ws/async/response`

---

## Acceptance Criteria

- [x] `async_flow_enabled` and `agent_base_url` config settings control orchestrator routing at the deployment level.
- [x] When `async_flow_enabled=True` and `agent_base_url` is set, all non-welcome A2A messages are forwarded to the orchestrator.
- [x] When `async_flow_enabled=False`, all messages receive canned responses (existing behavior preserved).
- [x] Welcome messages (first chat) are always served locally, regardless of config.
- [x] `requestId` is used as the correlation key (no `correlationId`). Fallback UUID generated if `requestId` is null.
- [x] Payload sent to orchestrator includes: `message`, `requestId`, `sessionId`, `contextId`, `CP_GUTC_Id`, `referrer`. No `webhookUrl` in payload.
- [x] Webhook endpoint at `/ciscoua/api/v1/ws/async/response` receives orchestrator response and delivers it to the correct WebSocket via correlation store lookup.
- [x] Webhook returns 400 if `requestId` is missing, 503 if delivery fails, 200 on success.
- [x] `AgentClient.send_async()` posts to `{agent_base_url}/async/request`.
- [x] Error handling: orchestrator timeout, non-2xx response, and connection errors are logged and `send_async` returns `False`.
- [ ] Unit test: correlation store set/get/remove by `requestId`.
- [ ] Integration test: WebSocket round-trip with orchestrator forwarding (mocked orchestrator).

---

## Sub-Tasks

### Sub-Task 1: Webhook path + correlation key changes — DONE

**Description:** Change webhook router prefix from `/webhooks` to `/ws`. Remove `correlationId` from all payloads and models. Use `requestId` as the correlation key throughout.

**Files changed:**
- `app/config.py` — `webhook_async_path` default → `"ws/async/response"`
- `app/api/webhooks.py` — router prefix `/ws`, lookup by `requestId`
- `app/services/message_handler.py` — use `requestId` as correlation key, remove `webhookUrl` construction
- `app/core/correlation_store.py` — keyed by `request_id`
- `app/services/agent_client.py` — removed `webhook_url` and `correlation_id` params
- `app/models/webhook_requests.py` — removed `correlationId` and `webhookUrl` from both models
- `app/models/responses.py` — `AsyncAcceptedResponse` uses `request_id` only

**Status:** Complete

---

### Sub-Task 2: Config — set orchestrator base URL default — DONE

**Description:** Set the default `agent_base_url` to the staging orchestrator service.

**Files changed:** `app/config.py`

**Status:** Complete

---

### Sub-Task 3: Tests

**Description:** Add unit and integration tests for the orchestrator async flow.

**Files:** `tests/test_websocket_integration.py`, `tests/test_correlation_store.py` (new)

**AC:**
- [ ] Unit test: `CorrelationStore.set()` / `get_and_remove()` by `requestId` works correctly.
- [ ] Unit test: `get_and_remove()` returns `None` for unknown `requestId`.
- [ ] Unit test: `get_and_remove()` consumes the entry (second call returns `None`).
- [ ] Integration test: WebSocket message returns `in_progress` when `async_flow_enabled=True` (agent mocked).
- [ ] Integration test: Webhook POST with valid `requestId` delivers response to WebSocket.
- [ ] Integration test: Webhook POST with unknown `requestId` returns 503.
- [ ] Integration test: Webhook POST without `requestId` returns 400.

---

## Labels (suggested)

`orchestrator`, `websocket`, `integration`, `backend`, `feature`

---

## Component

`cdcai-microsvc-uber-assistant-frontend`

---

## Story Points

(Set per your team's sizing. Suggested: 3 points — reduced from 5 since routing logic and payload changes are complete.)

---

## Links

- Orchestrator API reference: `/docs/API_GUIDE.md`
- UI Request/Response spec: `docs/UI_REQUEST_RESPONSE_SPEC.md`
- Orchestrator payload samples: `docs/ORCHESTRATOR_PAYLOAD_SAMPLES.html`
