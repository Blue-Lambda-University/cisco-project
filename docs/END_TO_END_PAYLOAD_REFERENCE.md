# End-to-End Payload Reference

> All payloads between **UI**, **WebSocket Server (Frontend)**, and **Orchestrator**.
> UUIDs below are examples — the real ones are generated at runtime.

---

## Architecture Overview

```
┌──────┐         WebSocket          ┌────────────────────┐        HTTP POST         ┌──────────────┐
│  UI  │ ◄──────────────────────► │  WS Server (FE)    │ ──────────────────────► │ Orchestrator │
│      │   ws://host/ciscoua/       │                    │   POST /a2a/             │              │
│      │   api/v1/ws                │                    │                          │              │
│      │                            │                    │ ◄── SSE stream ──────── │  (streaming) │
│      │                            │                    │                          │              │
│      │                            │                    │ ◄── POST /ws/async/ ─── │  (webhook)   │
│      │                            │                    │      response            │              │
└──────┘                            └────────────────────┘                          └──────────────┘
```

### Transport Paths

| Path | Direction | Protocol | When Used |
|------|-----------|----------|-----------|
| **Streaming (SSE)** | FE → Orch → FE | HTTP POST + SSE response | Normal queries (default) |
| **Async (Webhook)** | FE → Orch, then Orch → FE | Two separate HTTP POSTs | Live-agent mode, SSE timeout fallback |

### HTTP Headers (Frontend → Orchestrator)

Both `send_streaming()` and `send_async()` attach these headers:

```
Content-Type: application/json
X-User-Token: <user_token>        # only if non-empty
X-User-Email: <email_address>     # only if non-empty
X-User-ID: <ccoid>                # only if non-empty
```

Source: extracted from WebSocket connection headers (`user_token`, `email_address`, `ccoid`).

---

## PATH 1: Welcome (First Chat)

### 1a. UI → WebSocket Server

```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "params": {
    "message": {
      "role": "user",
      "parts": [],
      "messageId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851"
    },
    "metadata": {
      "uaRequestType": "welcome",
      "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "CP_GUTC_Id": "abc123gutc",
      "referrer": "https://app.example.com/dashboard",
      "userAccessLevel": "admin",
      "region": "NA",
      "country": "US",
      "language": "en",
      "locale": "en-US"
    }
  }
}
```

### 1b. WebSocket Server → UI (response)

**NOT forwarded to Orchestrator.** Handled locally by the frontend.

```json
{
  "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "response": "Hello {user_name}, I'm the Uber Assistant...",
  "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "error": {},
  "status": "success",
  "a2aResponse": {
    "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "jsonrpc": "2.0",
    "result": {
      "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "artifacts": [
        {
          "artifactId": "",
          "name": "welcome_message",
          "parts": [{ "kind": "text", "text": "Hello {user_name}, I'm the Uber Assistant..." }]
        }
      ],
      "role": "assistant",
      "metadata": {
        "session_expiration_time": "2026-03-24T01:00:00.000000Z",
        "sessionId": "b7e8f9a0-1234-5678-9abc-def012345678",
        "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
        "CP_GUTC_Id": "abc123gutc",
        "referrer": "https://app.example.com/dashboard"
      }
    }
  }
}
```

---

## PATH 2: Extend Session

### 2a. UI → WebSocket Server

```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "id": "e83bd2c1-4fa7-42e1-9c3a-8b5d6f7e8a90",
  "params": {
    "message": {
      "role": "user",
      "parts": [],
      "messageId": "msg-extend-001"
    },
    "metadata": {
      "uaRequestType": "extend_session",
      "sessionId": "b7e8f9a0-1234-5678-9abc-def012345678",
      "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "CP_GUTC_Id": "abc123gutc",
      "referrer": "https://app.example.com/dashboard"
    }
  }
}
```

### 2b. WebSocket Server → UI (response)

**NOT forwarded to Orchestrator.** Handled locally — resets the 8-hour max lifetime.

```json
{
  "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "response": "Your session has been extended.",
  "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "error": {},
  "status": "success",
  "a2aResponse": {
    "id": "e83bd2c1-4fa7-42e1-9c3a-8b5d6f7e8a90",
    "jsonrpc": "2.0",
    "result": {
      "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "artifacts": [
        {
          "artifactId": "",
          "name": "extend_session_confirmation",
          "parts": [{ "kind": "text", "text": "Your session has been extended." }]
        }
      ],
      "role": "assistant",
      "metadata": {
        "session_expiration_time": "2026-03-24T01:00:00.000000Z",
        "sessionId": "b7e8f9a0-1234-5678-9abc-def012345678",
        "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
        "CP_GUTC_Id": "abc123gutc",
        "referrer": "https://app.example.com/dashboard"
      }
    }
  }
}
```

---

## PATH 3: End Session

### 3a. UI → WebSocket Server

```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "id": "c12d34e5-f678-90ab-cdef-1234567890ab",
  "params": {
    "message": {
      "role": "user",
      "parts": [],
      "messageId": "msg-end-001"
    },
    "metadata": {
      "uaRequestType": "end_session",
      "sessionId": "b7e8f9a0-1234-5678-9abc-def012345678",
      "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "CP_GUTC_Id": "abc123gutc",
      "referrer": "https://app.example.com/dashboard"
    }
  }
}
```

### 3b. WebSocket Server → UI (response)

**NOT forwarded to Orchestrator.** Session is deleted from Redis.

```json
{
  "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "response": "Your session has ended.",
  "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "error": {},
  "status": "success",
  "a2aResponse": {
    "id": "c12d34e5-f678-90ab-cdef-1234567890ab",
    "jsonrpc": "2.0",
    "result": {
      "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "artifacts": [
        {
          "artifactId": "",
          "name": "end_session_confirmation",
          "parts": [{ "kind": "text", "text": "Your session has ended." }]
        }
      ],
      "role": "assistant",
      "metadata": {
        "session_expiration_time": null,
        "sessionId": "b7e8f9a0-1234-5678-9abc-def012345678",
        "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
        "CP_GUTC_Id": "abc123gutc",
        "referrer": "https://app.example.com/dashboard"
      }
    }
  }
}
```

---

## PATH 4: Normal Query — Streaming (SSE) [Active Path]

### 4a. UI → WebSocket Server

```json
{
  "jsonrpc": "2.0",
  "method": "message/stream",
  "id": "req-7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d",
  "params": {
    "message": {
      "role": "user",
      "parts": [{ "kind": "text", "text": "What licensing options are available?" }],
      "messageId": "msg-4d5e6f7a-8b9c-0d1e-2f3a-4b5c6d7e8f9a",
      "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851"
    },
    "metadata": {
      "sessionId": "b7e8f9a0-1234-5678-9abc-def012345678",
      "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "CP_GUTC_Id": "abc123gutc",
      "referrer": "https://app.example.com/dashboard",
      "userAccessLevel": "admin",
      "region": "NA",
      "country": "US",
      "language": "en",
      "locale": "en-US"
    }
  }
}
```

### 4b. WebSocket Server → Orchestrator (HTTP POST)

**URL:** `POST {agent_base_url}/a2a/`
**Method:** `message/stream`

```json
{
  "jsonrpc": "2.0",
  "id": "req-7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d",
  "method": "message/stream",
  "params": {
    "message": {
      "role": "user",
      "parts": [{ "kind": "text", "text": "What licensing options are available?" }],
      "messageId": "msg-4d5e6f7a-8b9c-0d1e-2f3a-4b5c6d7e8f9a",
      "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "metadata": {
        "conversation_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
        "session_id": "b7e8f9a0-1234-5678-9abc-def012345678",
        "request_id": "req-7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d",
        "cp_gutc_id": "abc123gutc",
        "referrer": "https://app.example.com/dashboard",
        "user_access_level": "admin",
        "region": "NA",
        "country": "US",
        "language": "en",
        "locale": "en-US"
      }
    },
    "configuration": {
      "acceptedOutputModes": ["text"]
    }
  }
}
```

**HTTP Headers:**

```
Content-Type: application/json
X-User-Token: eyJhbGciOi...
X-User-Email: user@example.com
X-User-ID: CCOID12345
```

### 4c. Orchestrator → WebSocket Server (SSE stream on same connection)

The orchestrator responds with `Content-Type: text/event-stream`. Multiple SSE events arrive:

**Event 1 — status-update (working):**
```
data: {"jsonrpc":"2.0","id":"req-7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d","result":{"kind":"status-update","status":{"state":"working","message":{"role":"agent","parts":[{"kind":"text","text":"Processing your request..."}]}},"final":false}}
```

**Event 2 — artifact-update (partial text):**
```
data: {"jsonrpc":"2.0","id":"req-7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d","result":{"kind":"artifact-update","artifact":{"artifactId":"art-001","parts":[{"kind":"text","text":"Cisco offers several licensing options including..."}]},"final":false}}
```

**Event 3 — task (completed, final):**
```
data: {"jsonrpc":"2.0","id":"req-7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d","result":{"kind":"task","status":{"state":"completed"},"artifacts":[{"artifactId":"art-001","parts":[{"kind":"text","text":"Cisco offers several licensing options including..."}]}],"final":true}}
```

**Frontend behavior:** Only the **first content-bearing event** is accumulated. The final event's text is skipped if content was already received (prevents doubling). Only one response is sent to the UI.

### 4d. WebSocket Server → UI (final response)

```json
{
  "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "response": "Cisco offers several licensing options including...",
  "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "error": {},
  "status": "success",
  "a2aResponse": {
    "id": "req-7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d",
    "jsonrpc": "2.0",
    "result": {
      "artifacts": [
        {
          "artifactId": "e1f2a3b4-c5d6-7890-abcd-ef1234567890",
          "name": "agent_response",
          "parts": [{ "kind": "text", "text": "Cisco offers several licensing options including..." }]
        }
      ],
      "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "history": [
        {
          "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
          "kind": "message",
          "messageId": "a1b2c3d4e5f67890abcdef1234567890",
          "parts": [{ "kind": "text", "text": "What licensing options are available?" }],
          "role": "user",
          "taskId": "t-9a8b7c6d-5e4f-3a2b-1c0d-ef9876543210"
        },
        {
          "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
          "kind": "message",
          "messageId": "f9e8d7c6-b5a4-3210-fedc-ba9876543210",
          "parts": [{ "kind": "text", "text": "Processing your request..." }],
          "role": "agent",
          "taskId": "t-9a8b7c6d-5e4f-3a2b-1c0d-ef9876543210"
        }
      ],
      "id": "t-9a8b7c6d-5e4f-3a2b-1c0d-ef9876543210",
      "kind": "task",
      "status": { "state": "completed", "timestamp": "2026-03-23T17:30:00.000000Z" }
    },
    "metadata": {
      "session_expiration_time": "2026-03-24T01:30:00.000000Z",
      "sessionId": "b7e8f9a0-1234-5678-9abc-def012345678",
      "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "CP_GUTC_Id": "abc123gutc",
      "referrer": "https://app.example.com/dashboard"
    }
  }
}
```

---

## PATH 5: Normal Query — Async Webhook [Fallback Path]

Triggered by the **orchestrator** when `live_agent_mode` is active or SSE times out.
The frontend's outbound payload to the orchestrator is identical to Path 4b above.

### 5a. UI → WebSocket Server

Same as [Path 4a](#4a-ui--websocket-server).

### 5b. WebSocket Server → Orchestrator (HTTP POST)

Same payload as [Path 4b](#4b-websocket-server--orchestrator-http-post).

The frontend also stores a **correlation entry** in Redis:

```
Key:   "req-7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d"
Value: {
  "connection_id": "ws-conn-abc123",
  "session_id": "b7e8f9a0-1234-5678-9abc-def012345678",
  "context_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "conversation_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "cp_gutc_id": "abc123gutc",
  "referrer": "https://app.example.com/dashboard",
  "query_text": "What licensing options are available?"
}
```

### 5c. Orchestrator → WebSocket Server (Webhook callback)

**URL:** `POST {frontend_url}/ciscoua/api/v1/ws/async/response`

**Wrapped format:**
```json
{
  "body": {
    "requestId": "req-7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d",
    "content": "Cisco offers several licensing options including...",
    "sessionId": "b7e8f9a0-1234-5678-9abc-def012345678",
    "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
    "CP_GUTC_Id": "abc123gutc",
    "referrer": "https://app.example.com/dashboard"
  }
}
```

**Unwrapped format (also accepted):**
```json
{
  "requestId": "req-7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d",
  "content": "Cisco offers several licensing options including...",
  "sessionId": "b7e8f9a0-1234-5678-9abc-def012345678",
  "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "CP_GUTC_Id": "abc123gutc",
  "referrer": "https://app.example.com/dashboard"
}
```

### 5d. WebSocket Server → UI (final response)

Same structure as [Path 4d](#4d-websocket-server--ui-final-response).

The webhook handler:
1. Extracts `requestId` from the callback
2. Looks up the correlation store → gets `connection_id`
3. Builds a `UIResponse` via `build_a2a_response_from_content()`
4. Sends it down the correct WebSocket connection

---

## PATH 6: Error Responses

### 6a. Missing or empty query (no uaRequestType)

```json
{
  "jsonrpc": "2.0",
  "id": "req-7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d",
  "error": {
    "code": -32602,
    "message": "Missing or empty query in params.message.parts"
  }
}
```

### 6b. Session expired or not found

```json
{
  "jsonrpc": "2.0",
  "id": "req-7a8b9c0d-1e2f-3a4b-5c6d-7e8f9a0b1c2d",
  "error": {
    "code": -32404,
    "message": "Session expired or not found. Start a new session."
  }
}
```

### 6c. No active session to extend

```json
{
  "jsonrpc": "2.0",
  "id": "e83bd2c1-4fa7-42e1-9c3a-8b5d6f7e8a90",
  "error": {
    "code": -32000,
    "message": "No active session to extend. Start a new session."
  }
}
```

### 6d. Rate limit exceeded

```json
{
  "jsonrpc": "2.0",
  "id": null,
  "error": {
    "code": -32429,
    "message": "Rate limit exceeded. Try again later."
  }
}
```

---

## PATH 7: Webhook Endpoint Responses (Orchestrator ← Frontend)

Responses the frontend sends back to the orchestrator's webhook POST:

| Scenario | HTTP Status | Body |
|----------|-------------|------|
| Delivered successfully | `200` | `{"status": "delivered"}` |
| requestId expired (TTL) | `200` | `{"status": "expired"}` |
| Missing requestId | `400` | `{"error": "requestId required in body"}` |
| Connection not found / send failed | `503` | `{"error": "connection not found or send failed"}` |

---

## Field Reference

### Inbound fields (UI → WebSocket Server)

| Field | Location | Required | Description |
|-------|----------|----------|-------------|
| `uaRequestType` | `params.metadata` | No | `"welcome"`, `"extend_session"`, `"end_session"`, or omit for normal query |
| `sessionId` | `params.metadata` | No | Existing session ID (omit on first connect) |
| `conversationId` | `params.metadata` | No | Conversation thread ID |
| `CP_GUTC_Id` | `params.metadata` | No | Client tracking ID |
| `referrer` | `params.metadata` | No | Referring page URL |
| `userAccessLevel` | `params.metadata` | No | User's access level |
| `region` | `params.metadata` | No | User's region |
| `country` | `params.metadata` | No | User's country |
| `language` | `params.metadata` | No | User's language |
| `locale` | `params.metadata` | No | User's locale |
| `messageId` | `params.message` | No | Client message ID (auto-generated if missing) |
| `contextId` | `params.message` | No | Conversation context (fallback for `conversationId`) |
| `parts[].text` | `params.message` | Yes* | Query text (*required for normal queries, empty for welcome/extend/end) |

### Outbound fields (WebSocket Server → UI)

| Field | Location | Description |
|-------|----------|-------------|
| `contextId` | root | Conversation context ID |
| `response` | root | Plain text response content |
| `conversationId` | root | Conversation thread ID (echoed) |
| `status` | root | `"success"` or `"error"` |
| `error` | root | Empty `{}` on success |
| `a2aResponse.id` | nested | Echoed request ID |
| `a2aResponse.result.artifacts[].parts[].text` | nested | Rich response text |
| `a2aResponse.result.contextId` | nested | Context ID |
| `a2aResponse.result.history` | nested | User + agent message history |
| `a2aResponse.metadata.session_expiration_time` | nested | ISO 8601 session expiry (sliding window) |
| `a2aResponse.metadata.sessionId` | nested | Session ID |
| `a2aResponse.metadata.conversationId` | nested | Conversation ID (echoed) |
| `a2aResponse.metadata.CP_GUTC_Id` | nested | Tracking ID (echoed) |
| `a2aResponse.metadata.referrer` | nested | Referrer (echoed) |

### Forwarded fields (WebSocket Server → Orchestrator, inside `params.message.metadata`)

| Field | Description |
|-------|-------------|
| `conversation_id` | Conversation ID from UI |
| `session_id` | Session ID (created or existing) |
| `request_id` | Request correlation ID |
| `cp_gutc_id` | Tracking ID from UI |
| `referrer` | Referrer URL from UI |
| `user_access_level` | Access level from UI |
| `region` | Region from UI |
| `country` | Country from UI |
| `language` | Language from UI |
| `locale` | Locale from UI |

### WebSocket Connection Headers (UI → WebSocket Server)

| Header | Description |
|--------|-------------|
| `user_token` | Authentication token |
| `email_address` | User's email |
| `ccoid` | User's CCOID |

### Forwarded HTTP Headers (WebSocket Server → Orchestrator)

| Header | Source | Description |
|--------|--------|-------------|
| `X-User-Token` | `user_token` from WS header | Auth token (omitted if empty) |
| `X-User-Email` | `email_address` from WS header | Email (omitted if empty) |
| `X-User-ID` | `ccoid` from WS header | CCOID (omitted if empty) |

---

## Code Locations

| Component | File | Key Lines |
|-----------|------|-----------|
| WebSocket endpoint | `app/api/websocket.py` | Header extraction ~85, message loop ~141 |
| Message routing | `app/services/message_handler.py` | `_handle_a2a_request` ~207, streaming flow ~366 |
| Outbound payload build | `app/services/agent_client.py` | `send_streaming()` ~126, `send_async()` ~44 |
| Outbound models | `app/models/webhook_requests.py` | `WebhookOutgoingBody`, `OutgoingMessageMetadata` |
| Inbound A2A models | `app/models/a2a_requests.py` | `A2ASendMessageRequest`, `A2ARequestMetadata` |
| Response builders | `app/services/a2a_handler.py` | `build_welcome_response` ~323, `_build_a2a_response` ~557 |
| Webhook endpoint | `app/api/webhooks.py` | `POST /ws/async/response` ~79 |
| Webhook inbound models | `app/models/webhook_requests.py` | `WebhookIncomingBody`, `WebhookIncomingInner` |
| Correlation store | `app/core/correlation_store.py` | Redis-backed request-to-connection mapping |
| Session store | `app/core/session_store.py` | Redis-backed session with sliding TTL |
| Response models | `app/models/responses.py` | `UIResponse`, `A2AErrorResponse` |
