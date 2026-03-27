**Uber Assistant Frontend (WebSocket Server) — Update (Mar 10–23)**

**Streaming & Deployment**
- Migrated orchestrator communication from webhook-based async to SSE streaming — resolves the multi-pod routing issue
- Fixed Redis production issues (port config, backend toggle, missing dependency)
- Switched Redis client to async (`redis.asyncio`) with backward-compatible commands

**Request Types**
- Replaced `isFirstChat` boolean with `uaRequestType` string field supporting: `welcome`, `extend_session`, `end_session`, `history`
- Each type has defined request/response payloads in the updated UI Data Contract spec

**Session Management**
- Session max lifetime set to 8 hours with sliding idle TTL (30 min)
- Added `session_expiration_time` to every response metadata (replaces `timestamp`)
- TTL refreshed on both inbound message and orchestrator response
- Proactive early expiry when session nears max lifetime after idle period

**Header Forwarding**
- Extract `user_token`, `email_address`, `ccoid` from WebSocket headers
- Forward to orchestrator as `X-User-Token`, `X-User-Email`, `X-User-ID`
- Stored in Redis session for persistence

**Metadata Changes**
- Removed `userId` and `email` from payload metadata (now headers)
- Added optional fields: `userAccessLevel`, `region`, `country`, `language`, `locale`

**Collaboration & Meetings**
- Reviewed orchestrator codebase with team to map out streaming vs async webhook decision logic (`live_agent_mode`, SSE timeout fallback) — confirmed both paths must remain active
- Coordinated with UI developer on `uaRequestType` values replacing `isFirstChat`, `session_expiration_time` replacing `timestamp`, and new optional metadata context fields
- Aligned header naming (`X-User-Token`, `X-User-Email`, `X-User-ID`) with orchestrator team based on their `agent_client.py` implementation
- Updated and distributed the UI Request & Response Data Contract spec (V2) to stakeholders

**Docs**
- Updated UI Request & Response Data Contract (V2 — Word doc)
- Created end-to-end payload reference, flow diagrams, architecture doc

**Next**
- Implement `history` request type
- End-to-end testing with live-agent mode (async webhook path)
- PR the current changes
