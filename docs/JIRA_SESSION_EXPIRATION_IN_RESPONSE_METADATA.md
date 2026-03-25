# JIRA Ticket: Return Session Expiration Time in Response Metadata

Copy the sections below into a new JIRA ticket (Story).

---

## Summary

Replace the `timestamp` field in `a2aResponse.metadata` with the session's expiration time (`expires_at`) so the UI knows when the session will expire and can proactively prompt the user to refresh or start a new session.

---

## Description

**Context:** The WebSocket server (`cdcai-microsvc-uber-assistant-frontend`) returns an `a2aResponse.metadata.timestamp` field in every response sent to the UI. Currently this is set to `datetime.utcnow()` — the time the response was generated. This value is not actionable for the UI.

### Current behavior

```json
"metadata": {
  "timestamp": "2026-03-24T22:21:11.000000Z",
  "sessionId": "c-8hs4PWC8JptsDtcPZtiadcmgMElDDUevkiaG0n47w",
  "conversationId": "024a2d42-4145-413c-9595-162008c9308c",
  "CP_GUTC_Id": "8526b8c4-803c-49ff-a40f-defddc3976a0",
  "referrer": "https://www.cisco.com"
}
```

The `timestamp` value is the server wall-clock time when the response was built — not useful for the UI.

### Desired behavior

```json
"metadata": {
  "timestamp": "2026-03-24T22:51:11.000000Z",
  "sessionId": "c-8hs4PWC8JptsDtcPZtiadcmgMElDDUevkiaG0n47w",
  "conversationId": "024a2d42-4145-413c-9595-162008c9308c",
  "CP_GUTC_Id": "8526b8c4-803c-49ff-a40f-defddc3976a0",
  "referrer": "https://www.cisco.com"
}
```

The `timestamp` value is the session's `expires_at` — the point at which the session will expire if no further activity occurs. The UI can use this to:

- Display a countdown or warning banner ("Session expires in 5 minutes")
- Proactively prompt the user to send a message before expiry
- Prevent confusing "session expired" errors on the next request

### Why not add a new field?

Reusing `timestamp` keeps the payload contract stable (no new fields for the UI to adopt). If the team prefers a separate field (e.g., `sessionExpiresAt`), that is also acceptable — but requires UI coordination.

---

## Acceptance Criteria

- [ ] `a2aResponse.metadata.timestamp` contains the session's `expires_at` value (ISO 8601 with `Z` suffix) in all response paths:
  - Welcome response (`isFirstChat: true`)
  - Orchestrator streaming response (normal message flow)
  - Canned/fallback response (when orchestrator is unavailable)
- [ ] The value reflects the **post-extend** expiration (i.e., after `extend_ttl` has been called for the current request)
- [ ] If session lookup fails or session is newly created, `expires_at` from the freshly created session is used
- [ ] No change to the field name or payload structure — existing UI integration continues to work

---

## Implementation Notes

### Files to change

| File | Change |
|------|--------|
| `app/services/message_handler.py` | After `extend_ttl` or `create`, read back the session's `expires_at` and pass it through to response builders |
| `app/services/a2a_handler.py` | Accept optional `session_expires_at: datetime` parameter in `build_welcome_response`, `build_a2a_response_from_content`, `handle_a2a_request`, and `_build_a2a_response`; use it for `metadata.timestamp` |

### Data flow

```
message_handler._handle_a2a_request()
  → await self._session_store.extend_ttl(session_id)  # slides the window
  → session = await self._session_store.get(session_id)
  → session.expires_at                                 # this is the value we need
  → pass to a2a_handler.build_a2a_response_from_content(..., session_expires_at=session.expires_at)
    → _build_a2a_response(..., session_expires_at=...)
      → timestamp_str = session_expires_at.isoformat() + "Z"
```

### Edge cases

- **First chat (new session):** Session is created inline → `expires_at` is `now + idle_ttl_seconds` — use that
- **Session resolved from conversation map:** `extend_ttl` is called → re-fetch session to get updated `expires_at`
- **Redis session store:** `expires_at` is stored as ISO 8601 in the Redis hash — no additional round-trip needed after `get()`

---

## Story Points

2 (small — threading a value through 2 files, no new logic)

---

## Labels

`frontend-ws`, `session-management`, `metadata`, `ui-contract`
