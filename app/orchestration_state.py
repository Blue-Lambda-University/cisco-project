"""
State schema for LangGraph orchestration workflow.

This module defines the state that flows through the orchestration graph,
carrying information from node to node.

The orchestrator exposes both REST and A2A surfaces. Both share this state
and the same LangGraph workflow.

Internal flow (IDs):
- conversation_id: From the client (WebSocket/REST). Stable for the whole
  conversation; used for history and multi-turn.
- task_id: Per-request id (orchestration task or A2A task.id). Used for webhook
  routing and when calling the sub-agent for this request.
- Graph: load_history(conversation_id) → route_agent → call_subagent(task_id)
  → save_history(conversation_id).
- stream_forward_callback: When set (A2A message/stream), each sub-agent result
  is forwarded to the caller immediately so the caller sees the same stream.
"""

from typing import TypedDict, Optional, List, Dict, Any, Callable, Awaitable
from langchain_core.messages import BaseMessage


# Type for optional stream-forward callback: async (chunk: dict) -> None
# When set by the A2A executor, each sub-agent SSE result is forwarded to the caller in real time.
StreamForwardCallback = Optional[Callable[[Dict[str, Any]], Awaitable[None]]]


class OrchestrationState(TypedDict):
    """
    State that flows through the orchestration graph.
    
    This state is passed between nodes and accumulates information
    as the workflow progresses. Each node can read from and write to
    specific fields in the state.
    """
    
    # ========== Input Fields (from client request) ==========
    query: str
    """User's query string"""
    
    conversation_id: str
    """Client's conversation id (stable across turns). From request; used for history and multi-turn."""
    
    session_id: str
    """Session id from client (required); stored in history for traceability."""
    
    request_id: str
    """Request id from client (required); stored in history and echoed in response."""
    
    task_id: str
    """Per-request task ID (orchestration or A2A task.id). Webhook routing and sub-agent call."""
    
    user_id: str
    """User identifier"""
    
    frontend_async_push_url: Optional[str]
    """WebSocket server URL for async push delivery (from FRONTEND_ASYNC_PUSH_URL). Stored in conversation record for webhook forwarding. Never sent to sub-agent."""

    # ========== Intermediate State (computed during workflow) ==========
    history: List[BaseMessage]
    """
    Conversation history as LangChain messages.
    Loaded by load_history_node, used by route_agent_node.
    """
    
    routed_agent: Optional[str]
    """
    Name of the sub-agent routed to for this query.
    Set by route_agent_node, used by call_subagent_node.
    """
    
    routing_reason: Optional[str]
    """
    Brief explanation of why this agent was selected.
    Set by route_agent_node for debugging/logging.
    """

    predefined_response: Optional[str]
    """
    When set, the answer is a predefined response (e.g. hours, FAQ).
    call_subagent_node uses this as final_response and does not call a sub-agent.
    Response is still sent in A2A format via the same artifact path.
    """

    live_agent_requested: Optional[bool]
    """
    True when the user's query matches the live-agent trigger phrase
    (e.g. "I want to talk to a human"). Set by route_agent_node.
    """

    live_agent_mode: Optional[bool]
    """
    True when the conversation is in live agent (async) mode: either the current
    message matched the trigger phrase or we have it stored for this conversation_id.
    When True, we send the relay URL to the sub-agent for push; when False, we do not (sync only).
    We persist this per conversation_id so subsequent messages keep the relay without caller input.
    """

    # ========== Output Fields (results from sub-agent) ==========
    response_chunks: List[str]
    """
    Individual response chunks received from sub-agent.
    Accumulated by call_subagent_node during streaming.
    """
    
    final_response: str
    """
    Complete response text (concatenated chunks).
    Set by call_subagent_node, saved by save_history_node.
    """
    
    sub_agent_task_id: Optional[str]
    """
    Sub-agent's task ID (extracted from first response).
    Used for webhook routing in async scenarios.
    """

    sub_agent_status: Optional[str]
    """
    Terminal task state from the sub-agent ('completed', 'input-required', etc.).
    Set by call_subagent_node; relayed to callers via REST/A2A response.
    """

    resume_task_id: Optional[str]
    """
    When resuming a paused sub-agent task, this carries the sub-agent's task ID.
    Set before call_subagent_node when a pending interrupt exists; passed as
    Message.task_id so the sub-agent can locate the paused task.
    """

    resume_context_id: Optional[str]
    """
    The original context_id used in the first call to the paused sub-agent.
    Set alongside resume_task_id; used as Message.context_id on resume instead
    of the current request's task_id.
    """

    sub_agent_a2a_events: Optional[List[Dict[str, Any]]]
    """
    Raw A2A response events from the sub-agent (serialized to dicts).
    Included in REST response as sub_agent_a2a_response for debugging/integration.
    """

    stream_forward_callback: StreamForwardCallback
    """
    Optional async callable(chunk_dict) for real-time forwarding.
    When set (A2A stream or REST SSE), each sub-agent result chunk is forwarded
    to the caller immediately so the caller gets a live stream.
    """

    # ========== Metadata ==========
    metadata: Dict[str, Any]
    """
    Additional context and metadata for tracking.
    Can include source, timestamps, etc.
    """
