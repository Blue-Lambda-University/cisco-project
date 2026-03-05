# UI Request and Response Payload Samples

Sample A2A payloads for the WebSocket UI: first turn, follow-up, success response, error response, and async-accepted response. Shown in both **pretty-printed** and **inline** (single-line) format.

---

## 1. UI Request – First Turn

### Pretty-printed

```json
{
  "jsonrpc": "2.0",
  "method": "agent/sendMessage",
  "requestId": "req-a1b2c3d4",
  "id": 1,
  "params": {
    "message": {
      "role": "user",
      "parts": [
        {
          "kind": "text",
          "text": "get cases for test@cisco.com"
        }
      ],
      "messageId": "msg-001"
    },
    "metadata": {
      "email": "test@cisco.com",
      "requestId": "req-a1b2c3d4",
      "sessionId": null,
      "conversationId": "conv-uuid-1111-2222-3333",
      "CP_GUTC_Id": "gutc-abc123",
      "referrer": "https://support.example.com"
    }
  }
}
```

### Inline

```json
{"jsonrpc":"2.0","method":"agent/sendMessage","requestId":"req-a1b2c3d4","id":1,"params":{"message":{"role":"user","parts":[{"kind":"text","text":"get cases for test@cisco.com"}],"messageId":"msg-001"},"metadata":{"email":"test@cisco.com","requestId":"req-a1b2c3d4","sessionId":null,"conversationId":"conv-uuid-1111-2222-3333","CP_GUTC_Id":"gutc-abc123","referrer":"https://support.example.com"}}}
```

---

## 2. UI Request – Follow-up

### Pretty-printed

```json
{
  "jsonrpc": "2.0",
  "method": "agent/sendMessage",
  "requestId": "req-e5f6g7h8",
  "id": 2,
  "params": {
    "message": {
      "role": "user",
      "contextId": "conv-uuid-1111-2222-3333",
      "parts": [
        {
          "kind": "text",
          "text": "show me the first one"
        }
      ],
      "messageId": "msg-002"
    },
    "metadata": {
      "email": "test@cisco.com",
      "requestId": "req-e5f6g7h8",
      "sessionId": "sess-from-first-turn-response",
      "conversationId": "conv-uuid-1111-2222-3333",
      "CP_GUTC_Id": "gutc-abc123",
      "referrer": "https://support.example.com"
    }
  }
}
```

### Inline

```json
{"jsonrpc":"2.0","method":"agent/sendMessage","requestId":"req-e5f6g7h8","id":2,"params":{"message":{"role":"user","contextId":"conv-uuid-1111-2222-3333","parts":[{"kind":"text","text":"show me the first one"}],"messageId":"msg-002"},"metadata":{"email":"test@cisco.com","requestId":"req-e5f6g7h8","sessionId":"sess-from-first-turn-response","conversationId":"conv-uuid-1111-2222-3333","CP_GUTC_Id":"gutc-abc123","referrer":"https://support.example.com"}}}
```

---

## 3. UI Response – Success

### Pretty-printed

```json
{
  "jsonrpc": "2.0",
  "id": "req-a1b2c3d4",
  "requestId": "req-a1b2c3d4",
  "result": {
    "kind": "task",
    "id": "task_xyz-789",
    "contextId": "conv-uuid-1111-2222-3333",
    "status": {
      "state": "completed",
      "message": null,
      "timestamp": "2025-02-18T12:00:00.000000Z"
    },
    "artifacts": [
      {
        "artifactId": "art_abc-123",
        "name": "Response from orchestration",
        "parts": [
          {
            "kind": "text",
            "text": "Here are your cases for test@cisco.com..."
          }
        ]
      }
    ],
    "sessionId": "sess-from-first-turn-response",
    "role": "assistant",
    "metadata": {
      "requestId": "req-a1b2c3d4",
      "timestamp": "2025-02-18T12:00:00.000000Z",
      "sessionId": "sess-from-first-turn-response",
      "conversationId": "conv-uuid-1111-2222-3333",
      "CP_GUTC_Id": "gutc-abc123",
      "referrer": "https://support.example.com"
    }
  }
}
```

### Inline

```json
{"jsonrpc":"2.0","id":"req-a1b2c3d4","requestId":"req-a1b2c3d4","result":{"kind":"task","id":"task_xyz-789","contextId":"conv-uuid-1111-2222-3333","status":{"state":"completed","message":null,"timestamp":"2025-02-18T12:00:00.000000Z"},"artifacts":[{"artifactId":"art_abc-123","name":"Response from orchestration","parts":[{"kind":"text","text":"Here are your cases for test@cisco.com..."}]}],"sessionId":"sess-from-first-turn-response","role":"assistant","metadata":{"requestId":"req-a1b2c3d4","timestamp":"2025-02-18T12:00:00.000000Z","sessionId":"sess-from-first-turn-response","conversationId":"conv-uuid-1111-2222-3333","CP_GUTC_Id":"gutc-abc123","referrer":"https://support.example.com"}}}
```

---

## 4. UI Response – Error (e.g. session expired)

### Pretty-printed

```json
{
  "jsonrpc": "2.0",
  "id": "req-a1b2c3d4",
  "requestId": "req-a1b2c3d4",
  "error": {
    "code": -32000,
    "message": "Session expired or not found. Start a new session."
  }
}
```

### Inline

```json
{"jsonrpc":"2.0","id":"req-a1b2c3d4","requestId":"req-a1b2c3d4","error":{"code":-32000,"message":"Session expired or not found. Start a new session."}}
```

---

## 5. UI Response – Async accepted (in progress)

Returned when the request is forwarded to the orchestrator; full result is delivered later via webhook.

### Pretty-printed

```json
{
  "jsonrpc": "2.0",
  "id": "req-a1b2c3d4",
  "requestId": "req-a1b2c3d4",
  "result": {
    "kind": "task",
    "id": "correlation-uuid-from-server",
    "status": {
      "state": "in_progress",
      "message": "Forwarded to agent; response will follow via webhook."
    }
  }
}
```

### Inline

```json
{"jsonrpc":"2.0","id":"req-a1b2c3d4","requestId":"req-a1b2c3d4","result":{"kind":"task","id":"correlation-uuid-from-server","status":{"state":"in_progress","message":"Forwarded to agent; response will follow via webhook."}}}
```
