# Payload Contract: UI ↔ WebSocket Server ↔ Orchestrator

> All `id` values are real UUIDs. Fields marked **required** will cause validation errors if omitted.

---

## Flow Overview

```
UI  ──WebSocket──▶  Frontend WS Server  ──HTTP POST──▶  Orchestrator
UI  ◀──WebSocket──  Frontend WS Server  ◀──HTTP POST──  Orchestrator (webhook)
```

---

## 1. UI → WebSocket Server (First Chat)

```json
{
  "jsonrpc": "2.0",
  "id": "58e143b2-a9f3-412d-ad26-b1b3b024f97d",
  "method": "message/stream",
  "params": {
    "message": {
      "role": "user",
      "parts": [{ "kind": "text", "text": "" }],
      "messageId": "ccdc689e-e8b0-4444-acb2-91d22b9037d6",
      "contextId": "024a2d42-4145-413c-9595-162008c9308c"
    },
    "metadata": {
      "sessionId": null,
      "conversationId": "024a2d42-4145-413c-9595-162008c9308c",
      "CP_GUTC_Id": "8526b8c4-803c-49ff-a40f-defddc3976a0",
      "referrer": "https://www.cisco.com",
      "isFirstChat": true,
      "userId": "user-abc123",
      "email": "user@cisco.com"
    }
  }
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `id` | yes | JSON-RPC request id, echoed back in response |
| `params.message.messageId` | yes | Client-generated message id |
| `params.message.parts` | yes | Can be empty text for first chat |
| `params.metadata.isFirstChat` | yes | Must be `true` for welcome flow |
| `params.metadata.sessionId` | no | `null` on very first visit; server creates one |
| `params.metadata.conversationId` | no | Thread identifier |
| `params.metadata.userId` | no | Passed through to orchestrator |
| `params.metadata.email` | no | Passed through to orchestrator |

**No orchestrator call.** Server returns welcome immediately.

---

## 2. WebSocket Server → UI (Welcome Response)

```json
{
  "contextId": "024a2d42-4145-413c-9595-162008c9308c",
  "response": "Welcome {user_name}! I am Cisco Uber Assistant. How can I help you today?\nBook a demo or trial\nChat with Sales\nGet Support\nLicensing\nGet Cisco Certified\nVelocity Hub",
  "conversationId": "024a2d42-4145-413c-9595-162008c9308c",
  "a2aResponse": {
    "id": "58e143b2-a9f3-412d-ad26-b1b3b024f97d",
    "jsonrpc": "2.0",
    "result": {
      "contextId": "024a2d42-4145-413c-9595-162008c9308c",
      "artifacts": [
        {
          "artifactId": "",
          "name": "welcome_message",
          "parts": [{ "kind": "text", "text": "Welcome {user_name}! I am Cisco Uber Assistant. How can I help you today?\nBook a demo or trial\nChat with Sales\nGet Support\nLicensing\nGet Cisco Certified\nVelocity Hub" }]
        }
      ],
      "role": "assistant",
      "metadata": {
        "timestamp": "2026-03-24T19:00:00.000000Z",
        "sessionId": "5498bdb2-d13a-4dd9-ad60-8295d895eec5",
        "conversationId": "024a2d42-4145-413c-9595-162008c9308c",
        "CP_GUTC_Id": "8526b8c4-803c-49ff-a40f-defddc3976a0",
        "referrer": "https://www.cisco.com"
      }
    }
  },
  "error": {},
  "status": "success"
}
```

| Field | Notes |
|-------|-------|
| `a2aResponse.id` | Echoes the JSON-RPC `id` from the request |
| `a2aResponse.result.metadata.sessionId` | Server-created session id — **UI must store and send this back on subsequent requests** |

---

## 3. UI → WebSocket Server (Normal Message)

```json
{
  "jsonrpc": "2.0",
  "id": "58e143b2-a9f3-412d-ad26-b1b3b024f97d",
  "method": "message/stream",
  "params": {
    "message": {
      "role": "user",
      "parts": [{ "kind": "text", "text": "get my licensing cases" }],
      "messageId": "ccdc689e-e8b0-4444-acb2-91d22b9037d6",
      "contextId": "024a2d42-4145-413c-9595-162008c9308c"
    },
    "metadata": {
      "sessionId": "5498bdb2-d13a-4dd9-ad60-8295d895eec5",
      "conversationId": "024a2d42-4145-413c-9595-162008c9308c",
      "CP_GUTC_Id": "8526b8c4-803c-49ff-a40f-defddc3976a0",
      "referrer": "https://www.cisco.com",
      "isFirstChat": false,
      "userId": "user-abc123",
      "email": "user@cisco.com"
    }
  }
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `params.message.parts[0].text` | yes | Must be non-empty for normal messages |
| `params.metadata.sessionId` | yes | From welcome response — server validates it exists |
| `params.metadata.isFirstChat` | yes | Must be `false` |

---

## 4. WebSocket Server → Orchestrator

`POST http://{agent_base_url}/a2a/`

The WebSocket server transforms the UI payload into the format the orchestrator's a2a-sdk expects:

```json
{
  "jsonrpc": "2.0",
  "id": "58e143b2-a9f3-412d-ad26-b1b3b024f97d",
  "method": "message/stream",
  "params": {
    "message": {
      "role": "user",
      "parts": [{ "kind": "text", "text": "get my licensing cases" }],
      "messageId": "ccdc689e-e8b0-4444-acb2-91d22b9037d6",
      "contextId": "024a2d42-4145-413c-9595-162008c9308c",
      "metadata": {
        "user_id": "user-abc123",
        "email": "user@cisco.com",
        "conversation_id": "024a2d42-4145-413c-9595-162008c9308c",
        "session_id": "5498bdb2-d13a-4dd9-ad60-8295d895eec5",
        "request_id": "58e143b2-a9f3-412d-ad26-b1b3b024f97d",
        "cp_gutc_id": "8526b8c4-803c-49ff-a40f-defddc3976a0",
        "referrer": "https://www.cisco.com"
      }
    },
    "configuration": {
      "acceptedOutputModes": ["text"]
    }
  }
}
```

### Field mapping: UI (camelCase) → Orchestrator (snake_case in metadata)

| UI field | Orchestrator field | Required by orchestrator |
|----------|-------------------|--------------------------|
| `id` (top-level) | `id` (top-level) + `metadata.request_id` | **yes** (JSON-RPC id) |
| `params.message.messageId` | `params.message.messageId` | **yes** (a2a-sdk validation) |
| `params.message.parts` | `params.message.parts` | **yes** |
| `params.message.contextId` | `params.message.contextId` | no |
| `params.metadata.conversationId` | `metadata.conversation_id` | no (falls back to `contextId`) |
| `params.metadata.sessionId` | `metadata.session_id` | no |
| `params.metadata.CP_GUTC_Id` | `metadata.cp_gutc_id` | no |
| `params.metadata.referrer` | `metadata.referrer` | no |
| `params.metadata.userId` | `metadata.user_id` | no (defaults to `'unknown'`) |
| `params.metadata.email` | `metadata.email` | no |

### What the orchestrator does with these fields

| Field | Orchestrator behavior |
|-------|----------------------|
| `metadata.request_id` | Stored in `ConversationRecord.request_id` — **echoed back as `requestId` in webhook** |
| `metadata.conversation_id` | Used as conversation key for routing and state |
| `metadata.session_id` | Stored in `ConversationRecord.session_id` — echoed back in webhook |
| `metadata.user_id` | Used for agent routing logic |
| `messageId` | Required by a2a-sdk validation but **not used** for correlation or routing |

### Not sent to orchestrator

| UI field | Reason |
|----------|--------|
| `isFirstChat` | Handled locally — welcome response returned without orchestrator call |

---

## 5. Orchestrator → WebSocket Server (Webhook)

`POST http://{frontend_url}/ciscoua/api/v1/ws/async/response`

The orchestrator calls our webhook when the sub-agent response is ready:

```json
{
  "body": {
    "requestId": "58e143b2-a9f3-412d-ad26-b1b3b024f97d",
    "content": "Hi, here are your current cases:\n\n| Case # | Status | Subject |\n|--------|--------|---------|\n| SR-001 | Open | License renewal |\n| SR-002 | Closed | Activation issue |",
    "sessionId": "5498bdb2-d13a-4dd9-ad60-8295d895eec5",
    "contextId": "024a2d42-4145-413c-9595-162008c9308c",
    "CP_GUTC_Id": "",
    "referrer": ""
  }
}
```

| Field | Value | Notes |
|-------|-------|-------|
| `requestId` | Our `metadata.request_id` | **Correlation key** — must match what we stored |
| `content` | String or object | Sub-agent response (can be plain text or `{"status": "completed", "artifacts": [...]}`) |
| `sessionId` | Our `metadata.session_id` | Echoed back |
| `contextId` | Our `metadata.conversation_id` | Echoed back (= `conversationId`) |
| `CP_GUTC_Id` | Always `""` | **Not round-tripped** — orchestrator hardcodes empty |
| `referrer` | Always `""` | **Not round-tripped** — orchestrator hardcodes empty |

### Content formats

**String content:**
```json
"content": "Hi, here are your current cases:\n<table>...</table>"
```

**Object content:**
```json
"content": {
  "status": "completed",
  "artifacts": [
    { "text": "Hi, here are your current cases:\n<table>...</table>" }
  ]
}
```

Both formats are supported. The WebSocket server extracts display text from either.

### Webhook also accepts unwrapped format

```json
{
  "requestId": "58e143b2-a9f3-412d-ad26-b1b3b024f97d",
  "content": "...",
  "sessionId": "...",
  "contextId": "...",
  "CP_GUTC_Id": "",
  "referrer": ""
}
```

---

## 6. WebSocket Server → UI (Final Response)

```json
{
  "contextId": "024a2d42-4145-413c-9595-162008c9308c",
  "response": "Hi, here are your current cases:\n\n| Case # | Status | Subject |\n|--------|--------|---------|\n| SR-001 | Open | License renewal |\n| SR-002 | Closed | Activation issue |",
  "conversationId": "024a2d42-4145-413c-9595-162008c9308c",
  "a2aResponse": {
    "id": "58e143b2-a9f3-412d-ad26-b1b3b024f97d",
    "jsonrpc": "2.0",
    "result": {
      "artifacts": [
        {
          "artifactId": "cf080b3d-c774-4ee1-a269-176dd7dcc77e",
          "name": "agent_response",
          "parts": [{ "kind": "text", "text": "Hi, here are your current cases:\n\n| Case # | Status | Subject |\n|--------|--------|---------|\n| SR-001 | Open | License renewal |\n| SR-002 | Closed | Activation issue |" }]
        }
      ],
      "contextId": "024a2d42-4145-413c-9595-162008c9308c",
      "history": [
        {
          "contextId": "024a2d42-4145-413c-9595-162008c9308c",
          "kind": "message",
          "messageId": "f95d89e0-55c7-4f82-b845-f01ce09345d0",
          "parts": [{ "kind": "text", "text": "get my licensing cases" }],
          "role": "user",
          "taskId": "33b2fbfa-2da8-40b2-b894-01113ba663bb"
        },
        {
          "contextId": "024a2d42-4145-413c-9595-162008c9308c",
          "kind": "message",
          "messageId": "e4549f45-36c8-4b9c-a25c-ee156eaadd24",
          "parts": [{ "kind": "text", "text": "Processing your request..." }],
          "role": "agent",
          "taskId": "33b2fbfa-2da8-40b2-b894-01113ba663bb"
        }
      ],
      "id": "33b2fbfa-2da8-40b2-b894-01113ba663bb",
      "kind": "task",
      "status": {
        "state": "completed",
        "timestamp": "2026-03-24T19:33:47.743584Z"
      }
    },
    "metadata": {
      "timestamp": "2026-03-24T19:33:47.743584Z",
      "sessionId": "5498bdb2-d13a-4dd9-ad60-8295d895eec5",
      "conversationId": "024a2d42-4145-413c-9595-162008c9308c",
      "CP_GUTC_Id": "8526b8c4-803c-49ff-a40f-defddc3976a0",
      "referrer": "https://www.cisco.com"
    }
  },
  "error": {},
  "status": "success"
}
```

| Field | Notes |
|-------|-------|
| `contextId` | Same as `conversationId` |
| `response` | Extracted text for easy UI display |
| `a2aResponse.id` | Echoes the original JSON-RPC `id` |
| `a2aResponse.metadata.CP_GUTC_Id` | Restored from correlation store (not from webhook) |
| `a2aResponse.metadata.referrer` | Restored from correlation store (not from webhook) |

---

## 7. Error Responses (WebSocket Server → UI)

**Rate limited:**
```json
{
  "jsonrpc": "2.0",
  "id": null,
  "error": {
    "code": -32429,
    "message": "Rate limit exceeded",
    "data": { "retryAfterMs": 4500 }
  }
}
```

**Session expired:**
```json
{
  "jsonrpc": "2.0",
  "id": "58e143b2-a9f3-412d-ad26-b1b3b024f97d",
  "error": {
    "code": -32000,
    "message": "Session expired or not found. Start a new session."
  }
}
```

**Orchestrator timeout (no webhook response within 30 min):**
```json
{
  "jsonrpc": "2.0",
  "id": "58e143b2-a9f3-412d-ad26-b1b3b024f97d",
  "error": {
    "code": -32408,
    "message": "Request timed out waiting for orchestrator response",
    "data": { "timeoutSeconds": 1800 }
  }
}
```

**Missing query text:**
```json
{
  "jsonrpc": "2.0",
  "id": "58e143b2-a9f3-412d-ad26-b1b3b024f97d",
  "error": {
    "code": -32602,
    "message": "Missing or empty query in params.message.parts"
  }
}
```

---

## 8. ID Lifecycle Summary

| ID | Generated by | Lifecycle |
|----|-------------|-----------|
| `id` (JSON-RPC) | UI | Sent in request → used as `request_id` → stored in correlation store → echoed back in webhook as `requestId` → returned to UI in response |
| `conversationId` | UI | Shared across all messages in a conversation → sent as `contextId` on message + `conversation_id` in metadata → returned as `contextId` in webhook |
| `sessionId` | WebSocket Server | Created on first chat → returned to UI → UI sends back on every subsequent message → validated on each request |
| `messageId` | UI (or server-generated UUID) | Sent on each message → required by orchestrator a2a-sdk → not echoed in webhook |
| `CP_GUTC_Id` | UI | Passed through to orchestrator → **not** echoed in webhook (hardcoded empty) → restored from correlation store for UI response |
| `referrer` | UI | Same as `CP_GUTC_Id` |

---

## 9. Configuration Required

### WebSocket Server (frontend)

| Env var | Value | Purpose |
|---------|-------|---------|
| `UA_WS_ASYNC_FLOW_ENABLED` | `"true"` | Enable forwarding to orchestrator |
| `UA_WS_AGENT_BASE_URL` | `http://{orchestrator-svc}:8006` | Orchestrator URL |
| `UA_WS_SESSION_PERSISTENCE_BACKEND` | `"redis"` | Required for multi-pod |
| `UA_WS_REDIS_HOST` | `10.68.81.4` | Redis host |
| `UA_WS_REDIS_PORT` | `6379` | Redis port |

### Orchestrator

| Env var | Value | Purpose |
|---------|-------|---------|
| `FRONTEND_ASYNC_PUSH_URL` | `http://{frontend-svc}:8006/ciscoua/api/v1/ws/async/response` | Webhook callback URL |
| `REDIS_HOST` | `10.68.81.4` | Redis host (shared state) |
| `REDIS_PORT` | `6379` | Redis port |
