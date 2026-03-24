# Webhook Multi-Message Investigation

## Problem

Only the **first** webhook message from the orchestrator is forwarded to the UI via WebSocket. The 2nd and 3rd messages are lost.

## How it works today

1. When the UI sends a message, we store a `PendingAsyncRequest` in the correlation store keyed by `requestId`.
2. When the orchestrator POSTs to our webhook (`/ws/async/response`), we call `get_and_remove(requestId)` to look up the pending entry.
3. If found, we deliver the response to the WebSocket and **remove the entry** from the store.
4. If not found, we return `503` ("requestId not found or already consumed").

## Why only the 1st message gets through

The correlation store is a **1:1 map** — one entry per `requestId`. If subsequent webhook messages arrive with the **same `requestId`**, the first one consumes the entry and all following ones fail the lookup.

| Webhook # | `requestId` | `get_and_remove` result | Outcome |
|---|---|---|---|
| 1st | `abc-123` | Found, **consumed** | Delivered to UI |
| 2nd | `abc-123` | `None` (already consumed) | 503 — lost |
| 3rd | `abc-123` | `None` (already consumed) | 503 — lost |

## Per our spec, this should work

Per the documented payload contract, the orchestrator sends back:

```json
{
  "body": {
    "requestId": "b7e1c5a3-9f2d-4e8b-a6c4-1d3f5e7a9b0c",
    "contextId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
    "sessionId": "...",
    "content": "...",
    ...
  }
}
```

Where:

| Field | Purpose | Expected value |
|---|---|---|
| `requestId` | Correlation key to match response to request | **Unique per message** — should be the same ID we sent in our outgoing request |
| `contextId` | Conversation identifier (`conversationId`) | **Same across all messages** in a conversation |

If the orchestrator echoes back a **unique `requestId` per message**, the current 1:1 lookup works fine. Each webhook has a different key, each finds its own entry.

## Questions for the team

1. **Is the orchestrator echoing back the `requestId` we send in our outgoing payload?**
   - We send a unique `requestId` per message. If the orchestrator echoes it back, the lookup should work.

2. **Or is the orchestrator generating its own `requestId`?**
   - If so, what value is it using? Is it the `contextId`/`conversationId`? Something else?

3. **Can we get the actual webhook payloads from the orchestrator logs?**
   - Specifically, we need to see the `requestId` and `contextId` values across multiple webhook calls within the same conversation.
   - Are they the same or different?

4. **Example scenario to verify:**
   - UI sends 3 messages in one conversation. Each outgoing request has a unique `requestId` (`req-1`, `req-2`, `req-3`) and the same `contextId` (`conv-ABC`).
   - When the orchestrator calls our webhook 3 times, what does each payload look like?

   | Webhook call | Expected `requestId` | Expected `contextId` |
   |---|---|---|
   | Response to msg 1 | `req-1` | `conv-ABC` |
   | Response to msg 2 | `req-2` | `conv-ABC` |
   | Response to msg 3 | `req-3` | `conv-ABC` |

   **Is this what's actually happening?** Or are all three using the same `requestId`?

## What we need to determine

- If `requestId` is **unique per message** → current code should work, bug is elsewhere.
- If `requestId` is **reused** (same as `contextId`) → we need to change our correlation strategy (e.g., FIFO queue keyed by `contextId`).
