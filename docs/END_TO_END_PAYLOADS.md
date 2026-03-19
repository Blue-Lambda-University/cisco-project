# End-to-End Payloads

> All `id` values are UUIDs. Fields marked *(optional)* are omitted from the payload when not provided by the sender.

---

## First Chat (Welcome Flow)

### Step 1: UI → WebSocket Server (First Chat / Welcome)

```json
{
  "jsonrpc": "2.0",
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "method": "agent/sendMessage",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": ""}],
      "messageId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
      "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851"
    },
    "metadata": {
      "sessionId": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "CP_GUTC_Id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "referrer": "https://www.cisco.com",
      "isFirstChat": true,
      "userId": "a8b9c0d1-e2f3-4a5b-6c7d-8e9f0a1b2c3d",
      "email": "user@cisco.com"
    }
  }
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `params.message.messageId` | optional | Client-generated message id |
| `params.metadata.sessionId` | optional | Omit on very first visit; server creates one |
| `params.metadata.conversationId` | optional | Omit on very first visit; server creates one |
| `params.metadata.userId` | optional | Passed through to orchestrator if provided |
| `params.metadata.email` | optional | Passed through to orchestrator if provided |
| `params.metadata.isFirstChat` | required | Must be `true` for welcome flow |

### Step 2: WebSocket Server → UI (Welcome Response)

No orchestrator call — returned immediately:

```json
{
  "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "response": "Welcome {user_name}! I am Cisco Uber Assistant. How can I help you today?\nBook a demo or trial\nChat with Sales\nGet Support\nLicensing\nGet Cisco Certified",
  "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "a2aResponse": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "jsonrpc": "2.0",
    "result": {
      "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "artifacts": [
        {
          "artifactId": "",
          "name": "welcome_message",
          "parts": [{"kind": "text", "text": "Welcome {user_name}! I am Cisco Uber Assistant. How can I help you today?\nBook a demo or trial\nChat with Sales\nGet Support\nLicensing\nGet Cisco Certified"}]
        }
      ],
      "role": "assistant",
      "metadata": {
        "timestamp": "2026-03-17T19:00:00.000000Z",
        "sessionId": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
        "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
        "CP_GUTC_Id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "referrer": "https://www.cisco.com"
      }
    }
  },
  "error": {},
  "status": "success"
}
```

---

## Normal Message Flow (via Orchestrator)

### Step 3: UI → WebSocket Server (Normal Message)

```json
{
  "jsonrpc": "2.0",
  "id": "b7e1c5a3-9f2d-4e8b-a6c4-1d3f5e7a9b0c",
  "method": "agent/sendMessage",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": "get my licensing cases"}],
      "messageId": "e4d3c2b1-a0f9-8e7d-6c5b-4a3928170615",
      "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851"
    },
    "metadata": {
      "sessionId": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "CP_GUTC_Id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "referrer": "https://www.cisco.com",
      "isFirstChat": false,
      "userId": "a8b9c0d1-e2f3-4a5b-6c7d-8e9f0a1b2c3d",
      "email": "user@cisco.com"
    }
  }
}
```

### Step 4: WebSocket Server → Orchestrator

HTTP `POST {agent_base_url}/a2a/`:

```json
{
  "jsonrpc": "2.0",
  "id": "b7e1c5a3-9f2d-4e8b-a6c4-1d3f5e7a9b0c",
  "method": "message/stream",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": "get my licensing cases"}],
      "messageId": "e4d3c2b1-a0f9-8e7d-6c5b-4a3928170615",
      "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "metadata": {
        "user_id": "a8b9c0d1-e2f3-4a5b-6c7d-8e9f0a1b2c3d",
        "email": "user@cisco.com",
        "conversation_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
        "session_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
        "request_id": "b7e1c5a3-9f2d-4e8b-a6c4-1d3f5e7a9b0c",
        "cp_gutc_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "referrer": "https://www.cisco.com"
      }
    },
    "configuration": {
      "acceptedOutputModes": ["text"]
    }
  }
}
```

| UI (camelCase) | Orchestrator (snake_case) | Notes |
|----------------|---------------------------|-------|
| `metadata.userId` | `metadata.user_id` | Optional — omitted if UI doesn't send it |
| `metadata.email` | `metadata.email` | Optional — omitted if UI doesn't send it |
| `metadata.sessionId` | `metadata.session_id` | |
| `metadata.conversationId` | `metadata.conversation_id` | |
| `metadata.CP_GUTC_Id` | `metadata.cp_gutc_id` | |
| `metadata.referrer` | `metadata.referrer` | |
| `message.messageId` | `message.messageId` | Same level as `contextId` |
| `id` (top-level) | `id` / `metadata.request_id` | Correlation key for webhook callback |

> **Note:** All metadata fields are optional. Any field the UI omits will not appear in the orchestrator payload (`exclude_none=True`).

### Step 5: Orchestrator → WebSocket Server (Webhook)

HTTP `POST /ciscoua/api/v1/ws/async/response`:

**String content:**

```json
{
  "body": {
    "requestId": "b7e1c5a3-9f2d-4e8b-a6c4-1d3f5e7a9b0c",
    "content": "Hi, here are your current cases:\n<table>...</table>",
    "sessionId": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
    "CP_GUTC_Id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "referrer": "https://www.cisco.com"
  }
}
```

**Object content:**

```json
{
  "body": {
    "requestId": "b7e1c5a3-9f2d-4e8b-a6c4-1d3f5e7a9b0c",
    "content": {
      "status": "completed",
      "artifacts": [
        {"text": "Hi, here are your current cases:\n<table>...</table>"}
      ]
    },
    "sessionId": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
    "CP_GUTC_Id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "referrer": "https://www.cisco.com"
  }
}
```

> The webhook accepts both wrapped (`{"body": {...}}`) and unwrapped formats. The `requestId` is used to look up the pending correlation entry and route the response to the correct WebSocket connection.

### Step 6: WebSocket Server → UI (Final Response)

```json
{
  "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "response": "Hi, here are your current cases:\n<table>...</table>",
  "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "a2aResponse": {
    "id": "b7e1c5a3-9f2d-4e8b-a6c4-1d3f5e7a9b0c",
    "jsonrpc": "2.0",
    "result": {
      "artifacts": [
        {
          "artifactId": "c8a7b6d5-e4f3-2a1b-9c8d-7e6f5a4b3c2d",
          "name": "agent_response",
          "parts": [{"kind": "text", "text": "Hi, here are your current cases:\n<table>...</table>"}]
        }
      ],
      "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "history": [
        {
          "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
          "kind": "message",
          "messageId": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d",
          "parts": [{"kind": "text", "text": "get my licensing cases"}],
          "role": "user",
          "taskId": "9f8e7d6c-5b4a-3928-1706-15a4b3c2d1e0"
        },
        {
          "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
          "kind": "message",
          "messageId": "2b3c4d5e-6f7a-8b9c-0d1e-2f3a4b5c6d7e",
          "parts": [{"kind": "text", "text": "Processing your request..."}],
          "role": "agent",
          "taskId": "9f8e7d6c-5b4a-3928-1706-15a4b3c2d1e0"
        }
      ],
      "id": "9f8e7d6c-5b4a-3928-1706-15a4b3c2d1e0",
      "kind": "task",
      "status": {
        "state": "completed",
        "timestamp": "2026-03-17T19:33:47.743584Z"
      }
    },
    "metadata": {
      "timestamp": "2026-03-17T19:33:47.743584Z",
      "sessionId": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "conversationId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
      "CP_GUTC_Id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "referrer": "https://www.cisco.com"
    }
  },
  "error": {},
  "status": "success"
}
```

---

## Error Responses (WebSocket Server → UI)

**Rate limited:**

```json
{
  "jsonrpc": "2.0",
  "id": null,
  "error": {
    "code": -32429,
    "message": "Rate limit exceeded",
    "data": {"retryAfterMs": 4500}
  }
}
```

**Orchestrator timeout:**

```json
{
  "jsonrpc": "2.0",
  "id": "b7e1c5a3-9f2d-4e8b-a6c4-1d3f5e7a9b0c",
  "error": {
    "code": -32408,
    "message": "Request timed out waiting for orchestrator response",
    "data": {"timeoutSeconds": 1800}
  }
}
```

**Session expired:**

```json
{
  "jsonrpc": "2.0",
  "id": "b7e1c5a3-9f2d-4e8b-a6c4-1d3f5e7a9b0c",
  "error": {
    "code": -32404,
    "message": "Session expired"
  }
}
```

**Orchestrator unavailable:**

```json
{
  "jsonrpc": "2.0",
  "id": "b7e1c5a3-9f2d-4e8b-a6c4-1d3f5e7a9b0c",
  "error": {
    "code": -32503,
    "message": "Orchestrator unavailable"
  }
}
```
