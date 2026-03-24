"""
LangGraph orchestration workflow definition.

This module builds and compiles the orchestration graph that defines
the workflow for routing and processing user queries.
"""

import logging
from typing import Any

from langgraph.graph import StateGraph, START, END

from .orchestration_state import OrchestrationState
from .orchestration_nodes import (
    load_history_node,
    route_agent_node,
    call_subagent_node,
    save_history_node,
)

logger = logging.getLogger(__name__)


def create_orchestration_graph() -> Any:
    """
    Create the LangGraph orchestration workflow.

    Graph structure:
        START → load_history → route_agent → call_subagent → save_history → END

    --- When query is PREDEFINED (e.g. "what hours are you open?") ---

        load_history
          │  _get_predefined_response(query) matches → return { history: [], predefined_response }
          │  No get_history, no card prefetch.
          ▼
        route_agent  →  sees predefined_response in state, returns routed_agent + predefined_response
        call_subagent  →  sees predefined_response, returns final_response (no A2A call)
        save_history  →  append_turn as usual

    --- Normal flow ---

        load_history
          │  1. get_history(conversation_id, user_id)  →  prior turns
          │  2. _prefetch_agent_cards()  (so route_agent skips card fetch)
          │  3. history = last 15 turns as Human/AI messages
          │
          ▼
        route_agent
          │  (predefined check → else) router.route(query, history)
          │  Cards already present from prefetch → LLM routing only
          ▼
        call_subagent
          │  A2A send_message_streaming(query, conversation_history=history)
          ▼
        save_history
          │  append_turn(conversation_id, query, final_response)
          ▼
        END

    Summarization is handled by the history API. When the history service
    provides a summary, it can be included in the prompt context.

    This linear workflow ensures:
    1. Recent context is loaded before routing
    2. Routing and subagent see the last 15 turns of conversation
    3. Sub-agent is called with routed agent
    4. History is saved after successful completion

    Returns:
        Compiled StateGraph ready for execution
    """
    logger.info("🏗️ Building orchestration graph")
    
    # Create state graph with our state schema
    builder = StateGraph(OrchestrationState)
    
    # Add all nodes to the graph
    builder.add_node("load_history", load_history_node)
    builder.add_node("route_agent", route_agent_node)
    builder.add_node("call_subagent", call_subagent_node)
    builder.add_node("save_history", save_history_node)
    
    # Define the linear workflow edges
    builder.add_edge(START, "load_history")
    builder.add_edge("load_history", "route_agent")
    builder.add_edge("route_agent", "call_subagent")
    builder.add_edge("call_subagent", "save_history")
    builder.add_edge("save_history", END)
    
    # Compile the graph
    # Note: We're not using checkpointing for now (stateless execution)
    graph = builder.compile()
    
    logger.info("✅ Orchestration graph compiled successfully")
    
    return graph


# Singleton instance for performance
# The graph is compiled once and reused across requests
_orchestration_graph = None


def get_orchestration_graph() -> Any:
    """
    Get or create the orchestration graph singleton.
    
    This ensures the graph is only compiled once, improving performance
    for subsequent requests.
    
    Returns:
        Compiled orchestration graph
    """
    global _orchestration_graph
    if _orchestration_graph is None:
        _orchestration_graph = create_orchestration_graph()
    return _orchestration_graph


