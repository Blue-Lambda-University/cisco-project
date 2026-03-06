# A2A Test Messages for wscat

Use these JSON messages to test the WebSocket A2A flow with `wscat -c ws://localhost:8000/ciscoua/api/v1/ws`.

---

## 1. First turn

Send this first. From the response, copy `result.sessionId` and `result.contextId` for the follow-up.

```json
{
  "jsonrpc": "2.0",
  "params": {
    "message": {
      "role": "user",
      "parts": [
        { "kind": "text", "text": "get cases for test@cisco.com" }
      ],
      "messageId": "msg-001"
    },
    "metadata": {
      "email": "test@cisco.com",
      "requestId": "req-001",
      "sessionId": null,
      "conversationId": null
    }
  },
  "id": 1
}
```

**Single line (for easy paste):**
```json
{"jsonrpc":"2.0","params":{"message":{"role":"user","parts":[{"kind":"text","text":"get cases for test@cisco.com"}],"messageId":"msg-001"},"metadata":{"email":"test@cisco.com","requestId":"req-001","sessionId":null,"conversationId":null}},"id":1}
```

---

## 2. Follow-up

Replace `SESSION_ID_FROM_RESPONSE` and `CONTEXT_ID_FROM_RESPONSE` with the values from the first response (`result.sessionId` and `result.contextId`).

```json
{
  "jsonrpc": "2.0",
  "params": {
    "message": {
      "role": "user",
      "contextId": "CONTEXT_ID_FROM_RESPONSE",
      "parts": [
        { "kind": "text", "text": "show me the first one" }
      ],
      "messageId": "msg-002"
    },
    "metadata": {
      "email": "test@cisco.com",
      "requestId": "req-002",
      "sessionId": "SESSION_ID_FROM_RESPONSE",
      "conversationId": "CONTEXT_ID_FROM_RESPONSE"
    }
  },
  "id": 2
}
```

**Single line (replace placeholders):**
```json
{"jsonrpc":"2.0","params":{"message":{"role":"user","contextId":"CONTEXT_ID_FROM_RESPONSE","parts":[{"kind":"text","text":"show me the first one"}],"messageId":"msg-002"},"metadata":{"email":"test@cisco.com","requestId":"req-002","sessionId":"SESSION_ID_FROM_RESPONSE","conversationId":"CONTEXT_ID_FROM_RESPONSE"}},"id":2}
```

---

## Example with real IDs

If the first response has:
- `result.sessionId` = `Abc123xyz...` (no prefix)
- `result.contextId` = `acb1e1b4-cd53-4e6e-b4d8-619bac79c025`

then the follow-up is:

```json
{"jsonrpc":"2.0","params":{"message":{"role":"user","contextId":"acb1e1b4-cd53-4e6e-b4d8-619bac79c025","parts":[{"kind":"text","text":"show me the first one"}],"messageId":"msg-002"},"metadata":{"email":"test@cisco.com","requestId":"req-002","sessionId":"Abc123xyz...","conversationId":"acb1e1b4-cd53-4e6e-b4d8-619bac79c025"}},"id":2}
```

(Use the full `sessionId` string from your actual response.)
