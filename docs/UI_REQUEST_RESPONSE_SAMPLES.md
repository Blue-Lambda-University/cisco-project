# UI Request and Response – Sample Payloads

Copy-paste samples for the WebSocket UI contract. For full field definitions (required/optional) see **`UI_REQUEST_RESPONSE_SPEC.md`**. Shown in pretty-printed and inline format.

---

## 1. Request – First turn

**Pretty-printed:**

```json
{
  "jsonrpc": "2.0",
  "id": "req-a1b2c3d4",
  "params": {
    "message": {
      "role": "user",
      "parts": [
        { "kind": "text", "text": "get cases for test@cisco.com" }
      ],
      "messageId": "msg-001"
    },
    "metadata": {
      "sessionId": null,
      "conversationId": "conv-uuid-1111-2222-3333",
      "CP_GUTC_Id": "gutc-abc123",
      "referrer": "https://support.example.com",
      "isFirstChat": true
    }
  }
}
```

**Inline:**

```json
{"jsonrpc":"2.0","id":"req-a1b2c3d4","params":{"message":{"role":"user","parts":[{"kind":"text","text":"get cases for test@cisco.com"}],"messageId":"msg-001"},"metadata":{"sessionId":null,"conversationId":"conv-uuid-1111-2222-3333","CP_GUTC_Id":"gutc-abc123","referrer":"https://support.example.com","isFirstChat":true}}}
```

---

## 2. Request – Follow-up

Use `sessionId` and `conversationId` from the previous response. Send the same `conversationId` in `params.metadata.conversationId` and `params.message.contextId`.

**Pretty-printed:**

```json
{
  "jsonrpc": "2.0",
  "id": "req-e5f6g7h8",
  "params": {
    "message": {
      "role": "user",
      "contextId": "conv-uuid-1111-2222-3333",
      "parts": [
        { "kind": "text", "text": "show me the first one" }
      ],
      "messageId": "msg-002"
    },
    "metadata": {
      "sessionId": "39HARr8dJYEUEeFDYheE4d3-q3EsSlPO7CBHyd_4YSI",
      "conversationId": "conv-uuid-1111-2222-3333",
      "CP_GUTC_Id": "gutc-abc123",
      "referrer": "https://support.example.com",
      "isFirstChat": false
    }
  }
}
```

**Inline:**

```json
{"jsonrpc":"2.0","id":"req-e5f6g7h8","params":{"message":{"role":"user","contextId":"conv-uuid-1111-2222-3333","parts":[{"kind":"text","text":"show me the first one"}],"messageId":"msg-002"},"metadata":{"sessionId":"39HARr8dJYEUEeFDYheE4d3-q3EsSlPO7CBHyd_4YSI","conversationId":"conv-uuid-1111-2222-3333","CP_GUTC_Id":"gutc-abc123","referrer":"https://support.example.com","isFirstChat":false}}}
```

---

## 3. Response – Success

**Pretty-printed:**

```json
{
  "jsonrpc": "2.0",
  "id": "req-a1b2c3d4",
  "result": {
    "kind": "task",
    "id": "task_xyz-789",
    "contextId": "conv-uuid-1111-2222-3333",
    "status": {
      "state": "completed",
      "message": null,
      "timestamp": "2025-02-18T12:00:00.000000+00:00"
    },
    "artifacts": [
      {
        "artifactId": "art-001",
        "name": "agent_response",
        "parts": [
          { "kind": "text", "text": "Here are your cases for test@cisco.com..." }
        ]
      }
    ],
    "role": "assistant",
    "metadata": {
      "timestamp": "2025-02-18T12:00:00.000000+00:00",
      "sessionId": "39HARr8dJYEUEeFDYheE4d3-q3EsSlPO7CBHyd_4YSI",
      "conversationId": "conv-uuid-1111-2222-3333",
      "CP_GUTC_Id": "gutc-abc123",
      "referrer": "https://support.example.com"
    }
  }
}
```

**Inline:**

```json
{"jsonrpc":"2.0","id":"req-a1b2c3d4","result":{"kind":"task","id":"task_xyz-789","contextId":"conv-uuid-1111-2222-3333","status":{"state":"completed","message":null,"timestamp":"2025-02-18T12:00:00.000000+00:00"},"artifacts":[{"artifactId":"art-001","name":"agent_response","parts":[{"kind":"text","text":"Here are your cases for test@cisco.com..."}]}],"role":"assistant","metadata":{"timestamp":"2025-02-18T12:00:00.000000+00:00","sessionId":"39HARr8dJYEUEeFDYheE4d3-q3EsSlPO7CBHyd_4YSI","conversationId":"conv-uuid-1111-2222-3333","CP_GUTC_Id":"gutc-abc123","referrer":"https://support.example.com"}}}
```

---

## 4. Response – Error (invalid params)

**Pretty-printed:**

```json
{
  "jsonrpc": "2.0",
  "id": "req-a1b2c3d4",
  "error": {
    "code": -32602,
    "message": "Invalid params: expected params.message with role and parts (e.g. parts[].text)."
  }
}
```

**Inline:**

```json
{"jsonrpc":"2.0","id":"req-a1b2c3d4","error":{"code":-32602,"message":"Invalid params: expected params.message with role and parts (e.g. parts[].text)."}}
```

---

## 5. Response – Error (session expired)

**Pretty-printed:**

```json
{
  "jsonrpc": "2.0",
  "id": "req-e5f6g7h8",
  "error": {
    "code": -32000,
    "message": "Session expired or not found."
  }
}
```

**Inline:**

```json
{"jsonrpc":"2.0","id":"req-e5f6g7h8","error":{"code":-32000,"message":"Session expired or not found."}}
```

---

## 6. Response – In progress

Backend may send this when the final result will be sent later on the same WebSocket.

**Pretty-printed:**

```json
{
  "jsonrpc": "2.0",
  "id": "req-a1b2c3d4",
  "result": {
    "kind": "task",
    "id": "task-pending-abc",
    "status": {
      "state": "in_progress",
      "message": "Processing; final result will follow."
    }
  }
}
```

**Inline:**

```json
{"jsonrpc":"2.0","id":"req-a1b2c3d4","result":{"kind":"task","id":"task-pending-abc","status":{"state":"in_progress","message":"Processing; final result will follow."}}}
```
