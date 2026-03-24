"""
LangGraph nodes for orchestration workflow.

Each node is an async function that:
1. Receives the current state as input
2. Performs a specific operation
3. Returns a dict with updated state fields
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from langchain_core.messages import HumanMessage, AIMessage

from .orchestration_state import OrchestrationState
from .history import ChatHistoryService
from .properties import RECENT_TURNS
from .agent_router import AgentRegistry, RoutingDecisionMaker
from .a2a_client_handler import A2AClientHandler
from .properties import LIVE_AGENT_TRIGGER_PHRASES, LIVE_AGENT_TARGET_AGENT, PREDEFINED_RESPONSES

logger = logging.getLogger(__name__)


def _a2a_result_to_dict(obj: Any) -> Any:
    """Recursively serialize A2A result (Pydantic/dataclass) to JSON-serializable dict."""
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "dict"):
        return obj.dict()
    if isinstance(obj, dict):
        return {k: _a2a_result_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_a2a_result_to_dict(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def _is_live_agent_trigger(query: str) -> bool:
    """Return True if the query matches the configured live-agent trigger phrase(s)."""
    if not query or not LIVE_AGENT_TRIGGER_PHRASES:
        return False
    q = query.strip().lower()
    return any(phrase in q for phrase in LIVE_AGENT_TRIGGER_PHRASES)


def _find_live_agent_target(registry: AgentRegistry) -> "SubAgentConfig | None":
    """Return the agent designated for live-agent mode, or None if not found."""
    if not LIVE_AGENT_TARGET_AGENT:
        return None
    for agent in registry.list_agents():
        if LIVE_AGENT_TARGET_AGENT in agent.name.lower():
            return agent
        if agent.display_name and LIVE_AGENT_TARGET_AGENT in agent.display_name.lower():
            return agent
    return None


def _get_predefined_response(query: str) -> str | None:
    """Return predefined answer if query matches a predefined Q&A; otherwise None."""
    if not query or not PREDEFINED_RESPONSES:
        return None
    q = query.strip().lower()
    for trigger_phrases, answer in PREDEFINED_RESPONSES:
        if any(phrase in q for phrase in trigger_phrases):
            return answer
    return None


async def _prefetch_agent_cards() -> None:
    """Fetch missing agent cards so route_agent_node can skip this step. No return value."""
    try:
        from . import get_agent_registry
        registry = get_agent_registry()
        agents = registry.list_agents()
        missing = [a for a in agents if not a.agent_card]
        if missing:
            await asyncio.gather(*[registry.fetch_agent_card(a) for a in missing])
    except Exception as e:
        logger.debug("Agent card prefetch failed (route_agent will retry): %s", e)


async def load_history_node(state: OrchestrationState) -> Dict[str, Any]:
    """
    Load conversation history from centralized history service.

    If the query matches a predefined response (e.g. "what hours are you open?"),
    returns immediately with empty history and predefined_response set—skipping
    get_history and agent card prefetch.

    Otherwise retrieves prior conversation messages for the same conversation_id
    and keeps the last RECENT_TURNS messages. Summarization is handled by the
    history API; the summary will be available in the prompt context once the
    history service provides it.

    Args:
        state: Current orchestration state

    Returns:
        Dict with 'history' and optionally 'predefined_response'
    """
    predefined = _get_predefined_response(state["query"])
    if predefined is not None:
        logger.info("📋 Predefined query, skipping history load: %s...", state['query'][:50])
        return {"history": [], "predefined_response": predefined}

    logger.info("📚 Loading history for conversation_id: %s...", state['conversation_id'][:16])

    history_service = ChatHistoryService()

    try:
        prior = await history_service.get_history(
            conversation_id=state['conversation_id'],
            user_id=state['user_id']
        )

        await _prefetch_agent_cards()

        history_messages: List[Any] = []
        if prior:
            recent_turns = prior[-RECENT_TURNS:] if len(prior) > RECENT_TURNS else prior
            for turn in recent_turns:
                if turn.role == "user":
                    history_messages.append(HumanMessage(content=turn.content))
                elif turn.role == "assistant":
                    history_messages.append(AIMessage(content=turn.content))

        total = len(prior) if prior else 0
        logger.info(
            "📖 Loaded %d history messages (last %d of %d total turns)",
            len(history_messages),
            RECENT_TURNS,
            total,
        )

        return {"history": history_messages}

    except Exception as e:
        logger.error("Error loading history: %s", e, exc_info=True)
        return {"history": []}


async def route_agent_node(state: OrchestrationState) -> Dict[str, Any]:
    """
    Route to appropriate sub-agent using LLM with conversation context.
    
    Checks for a pending interrupt first (sub-agent in input-required state).
    Then checks predefined responses (e.g. "what hours are you open?").
    If no predefined match, uses LLM routing with conversation history.
    
    Args:
        state: Current orchestration state with query and history
        
    Returns:
        Dict with 'routed_agent', 'routing_reason', and optionally 'predefined_response'
    """
    logger.info("🧭 Routing query: %s...", state['query'][:100])

    # Check for a pending interrupt (sub-agent paused in input-required state).
    # If found, skip all routing and resume the same sub-agent.
    conversation_id = state.get("conversation_id", "")
    if conversation_id:
        try:
            from . import get_push_notification_router
            push_router = get_push_notification_router()
            if push_router:
                pending = await push_router.get_pending_interrupt(conversation_id)
                if pending:
                    subagent_task_id, context_id, sub_agent_name = pending
                    logger.info(
                        "🔄 Resuming interrupted sub-agent task %s on %s",
                        subagent_task_id[:16], sub_agent_name,
                    )
                    return {
                        "routed_agent": sub_agent_name,
                        "routing_reason": "Resuming interrupted sub-agent task",
                        "resume_task_id": subagent_task_id,
                        "resume_context_id": context_id,
                        "live_agent_requested": False,
                        "live_agent_mode": bool(state.get("live_agent_mode")),
                    }
        except Exception as e:
            logger.warning("Pending interrupt check failed (proceeding with normal routing): %s", e)

    # Live agent mode: from caller (previous trigger) or current message is trigger
    caller_live_mode = bool(state.get("live_agent_mode"))

    # Predefined response: may already be set by load_history (so we skipped history work), or detect here
    predefined = state.get("predefined_response") or _get_predefined_response(state["query"])
    if predefined is not None:
        logger.info("📋 Predefined response matched: %s...", state['query'][:50])
        return {
            "routed_agent": "orchestration",
            "routing_reason": "Predefined response",
            "predefined_response": predefined,
            "live_agent_requested": False,
            "live_agent_mode": caller_live_mode,
        }
    
    try:
        from . import get_agent_registry, get_routing_decision_maker
        
        registry = get_agent_registry()

        # Check for live-agent trigger phrase (e.g. "I want to talk to a human")
        live_agent_requested = _is_live_agent_trigger(state["query"])
        live_agent_mode = caller_live_mode or live_agent_requested

        if live_agent_requested:
            logger.info(
                "🎯 Live agent trigger detected for query: %s...",
                state["query"][:60],
            )

        # When live agent mode is active, force-route to the designated agent
        # (e.g. licensing-agent) regardless of LLM intent analysis.
        if live_agent_mode:
            target = _find_live_agent_target(registry)
            if target:
                logger.info(
                    "📡 Live agent mode active — force-routing to %s (bypassing LLM routing)",
                    target.name,
                )
                return {
                    "routed_agent": target.name,
                    "routing_reason": "Live agent mode — forced to designated agent",
                    "live_agent_requested": live_agent_requested,
                    "live_agent_mode": True,
                }
            logger.warning(
                "📡 Live agent mode active but target agent '%s' not found in registry; "
                "falling back to LLM routing",
                LIVE_AGENT_TARGET_AGENT,
            )

        # Normal LLM-based routing
        router = get_routing_decision_maker()
        routed_agent = await router.route(
            query=state['query'],
            history=state.get('history', [])
        )
        
        if not routed_agent:
            logger.error("❌ No agent found for routing")
            return {
                "routed_agent": None,
                "routing_reason": "No suitable agent found",
                "live_agent_requested": False,
                "live_agent_mode": caller_live_mode,
            }

        if live_agent_mode:
            logger.info("📡 Live agent mode: will send relay URL to sub-agent for async push")
        
        logger.info("✅ Routed to agent: %s", routed_agent.name)
        
        return {
            "routed_agent": routed_agent.name,
            "routing_reason": (
                "User requested human agent" if live_agent_requested
                else "Best match for query intent based on context"
            ),
            "live_agent_requested": live_agent_requested,
            "live_agent_mode": live_agent_mode,
        }
    
    except Exception as e:
        logger.error("Error in routing: %s", e, exc_info=True)
        return {
            "routed_agent": None,
            "routing_reason": f"Routing error: {str(e)}",
            "live_agent_requested": False,
            "live_agent_mode": caller_live_mode,
        }


async def call_subagent_node(state: OrchestrationState) -> Dict[str, Any]:
    """
    Call selected sub-agent via A2A protocol.

    Unified node used by all consumer paths (REST batch, REST stream, A2A batch,
    A2A stream).  For every sub-agent SSE chunk it:

    1. Forwards the raw chunk via ``stream_forward_callback`` when present
       (enables real-time streaming for A2A and REST stream endpoints).
    2. Serializes the A2A result and appends it to ``sub_agent_a2a_events``
       (enables batch REST responses and debugging).
    3. Extracts text content into ``final_response`` (for history persistence).

    If state has ``predefined_response``, returns that without calling a
    sub-agent.
    """
    if state.get("predefined_response") is not None:
        predefined = state["predefined_response"]
        logger.info("📋 Using predefined response: %s...", predefined[:50])
        return {
            "response_chunks": [predefined],
            "final_response": predefined,
            "sub_agent_task_id": None,
            "sub_agent_a2a_events": [],
        }

    if not state.get("routed_agent"):
        logger.error("❌ No agent selected, cannot call sub-agent")
        return {
            "response_chunks": [],
            "final_response": "Error: No agent was selected for this query.",
            "sub_agent_task_id": None,
            "sub_agent_a2a_events": [],
        }

    logger.info("📞 Calling sub-agent: %s", state['routed_agent'])

    try:
        from . import get_agent_registry, get_a2a_client_handler

        registry = get_agent_registry()
        client_handler = get_a2a_client_handler()

        agent_config = registry.get_agent(state["routed_agent"])

        if not agent_config:
            logger.error("❌ Agent config not found: %s", state['routed_agent'])
            return {
                "response_chunks": [],
                "final_response": f"Error: Agent configuration not found for {state['routed_agent']}",
                "sub_agent_task_id": None,
                "sub_agent_a2a_events": [],
            }

        sub_agent_task_id: Optional[str] = None
        sub_agent_a2a_events: List[Dict[str, Any]] = []
        stream_cb = state.get("stream_forward_callback")
        push_relay_url = agent_config.push_relay_url if state.get("live_agent_mode") else None

        context_id = state.get("resume_context_id") or state["task_id"]
        resume_task_id = state.get("resume_task_id")

        async for chunk in client_handler.send_message_streaming(
            agent_config=agent_config,
            query=state["query"],
            context_id=context_id,
            task_id=resume_task_id,
            push_relay_url=push_relay_url,
            conversation_history=state.get("history") or [],
            metadata={
                "source": "orchestration_agent",
                "routed_to": agent_config.name,
                "orchestration_task_id": state["task_id"],
                "conversation_id": state["conversation_id"],
            },
        ):
            # --- errors ---
            if "error" in chunk:
                error_msg = chunk["error"]
                if stream_cb is not None:
                    try:
                        await stream_cb(chunk)
                    except Exception as e:
                        logger.warning("Stream forward (error) callback error: %s", e)
                if "timeout" in error_msg.lower() or "ReadTimeout" in error_msg:
                    logger.warning("⏱️ SSE timeout from %s, relying on webhook", agent_config.name)
                    break
                logger.warning("Sub-agent stream error: %s", error_msg)
                continue

            # --- results ---
            result = chunk.get("result")
            if result is None:
                continue

            if stream_cb is not None:
                try:
                    await stream_cb(chunk)
                except Exception as e:
                    logger.warning("Stream forward callback error: %s", e)

            _task_id = None
            if hasattr(result, "root") and hasattr(result.root, "result") and hasattr(result.root.result, "id"):
                _task_id = result.root.result.id
            if sub_agent_task_id is None and _task_id is not None:
                sub_agent_task_id = _task_id
                logger.info("🔖 Extracted sub-agent task ID: %s", sub_agent_task_id)

            try:
                sub_agent_a2a_events.append(_a2a_result_to_dict(result))
            except Exception as e:
                logger.warning("Could not serialize A2A result: %s", e)

        final_response = _extract_text_from_raw_events(sub_agent_a2a_events)

        if sub_agent_a2a_events:
            logger.info(
                "📥 Sub-agent raw response (%d events): %s",
                len(sub_agent_a2a_events),
                sub_agent_a2a_events[-1],
            )

        # Detect terminal task state from the last event
        sub_agent_status = _detect_terminal_state(sub_agent_a2a_events)

        # Persist or clear interrupt based on the sub-agent's terminal state
        conv_id = state.get("conversation_id", "")
        if conv_id:
            try:
                from . import get_push_notification_router
                push_router = get_push_notification_router()
                if push_router:
                    if sub_agent_status == "input-required" and sub_agent_task_id:
                        await push_router.set_pending_interrupt(conv_id, sub_agent_task_id)
                    elif sub_agent_status != "input-required":
                        await push_router.clear_pending_interrupt(conv_id)
            except Exception as e:
                logger.warning("Failed to update interrupt state: %s", e)

        logger.info(
            "✅ Sub-agent stream complete: %d events, response length %d, status=%s",
            len(sub_agent_a2a_events),
            len(final_response),
            sub_agent_status,
        )

        return {
            "response_chunks": [final_response] if final_response else [],
            "final_response": final_response,
            "sub_agent_task_id": sub_agent_task_id,
            "sub_agent_a2a_events": sub_agent_a2a_events,
            "sub_agent_status": sub_agent_status,
        }

    except Exception as e:
        logger.error("❌ Error calling sub-agent: %s", e, exc_info=True)
        return {
            "response_chunks": [],
            "final_response": f"Error communicating with {state['routed_agent']}: {str(e)}",
            "sub_agent_task_id": None,
            "sub_agent_a2a_events": [],
        }


def _detect_terminal_state(events: List[Dict[str, Any]]) -> str:
    """Return the terminal task state from serialized A2A events.

    Scans events in reverse for a ``status.state`` field.  Falls back
    to ``"completed"`` when no explicit state is found (e.g. the stream
    contained only artifact events).
    """
    for ev in reversed(events):
        result = ev.get("result") if isinstance(ev, dict) else None
        if not result:
            continue
        status = result.get("status")
        if isinstance(status, dict):
            state_val = status.get("state")
            if isinstance(state_val, str) and state_val:
                return state_val
    return "completed"


def _extract_text_from_raw_events(events: List[Dict[str, Any]]) -> str:
    """Extract concatenated agent text from serialized A2A events.

    Text may appear in status-update messages (status.message.parts) or in
    artifact-update events (artifact.parts).  Both locations are checked.
    """
    parts: List[str] = []
    for ev in events:
        result = ev.get("result") if isinstance(ev, dict) else None
        if not result:
            continue

        # Text from status-update messages
        status = result.get("status")
        if isinstance(status, dict) and status.get("message"):
            msg = status["message"]
            for p in (msg.get("parts") or []):
                if isinstance(p, dict) and p.get("kind") == "text" and p.get("text"):
                    parts.append(p["text"])

        # Text from artifact-update events
        artifact = result.get("artifact")
        if isinstance(artifact, dict):
            for p in (artifact.get("parts") or []):
                if isinstance(p, dict) and p.get("kind") == "text" and p.get("text"):
                    parts.append(p["text"])

    return "".join(parts)


# Retry config for save_history (reduces lost-turn risk if history service is briefly unavailable)
SAVE_HISTORY_MAX_RETRIES = 3
SAVE_HISTORY_INITIAL_DELAY_SEC = 0.5
SAVE_HISTORY_BACKOFF_FACTOR = 2.0


async def save_history_node(state: OrchestrationState) -> Dict[str, Any]:
    """
    Save the conversation turn to centralized history service.

    Retries on failure (with exponential backoff) to reduce the risk of
    losing a turn when the history service is briefly unavailable.

    Args:
        state: Current orchestration state with query and final_response

    Returns:
        Empty dict (state doesn't change, this is just a side effect)
    """
    logger.info("💾 Saving to history for conversation_id: %s...", state['conversation_id'][:16])

    history_service = ChatHistoryService()
    session_id = state["session_id"]
    request_id = state["request_id"]
    task_id = state["task_id"]
    last_error: Optional[Exception] = None
    delay = SAVE_HISTORY_INITIAL_DELAY_SEC

    for attempt in range(1, SAVE_HISTORY_MAX_RETRIES + 1):
        try:
            await history_service.append_turn(
                conversation_id=state["conversation_id"],
                content=state.get("final_response", ""),
                user_id=state["user_id"],
                query=state["query"],
                chat_history_metadata={"session_id": session_id, "request_id": request_id, "task_id": task_id},
                agent_type="live" if state.get("live_agent_mode") else "chatbot",
            )
            logger.info("✅ History saved successfully")
            return {}  # No state changes, just side effect
        except Exception as e:
            last_error = e
            logger.warning(
                "❌ History save attempt %d/%d failed: %s",
                attempt,
                SAVE_HISTORY_MAX_RETRIES,
                e,
            )
            if attempt < SAVE_HISTORY_MAX_RETRIES:
                logger.info("   Retrying in %.1fs...", delay)
                await asyncio.sleep(delay)
                delay *= SAVE_HISTORY_BACKOFF_FACTOR

    logger.error(
        "❌ History save failed after %d attempts; turn not persisted: %s",
        SAVE_HISTORY_MAX_RETRIES,
        last_error,
        exc_info=True,
    )
    # Don't raise — response was already streamed; workflow completes
    return {}
