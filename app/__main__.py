"""FastAPI application: REST and A2A endpoints for the orchestration agent."""

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Tuple
import click
import httpx
import uvicorn
from typing import Optional, Dict, Any, List
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import PlainTextResponse
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
)
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)

# Setup logging first before using logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# LangSmith Configuration (Observability & Tracing)
# ============================================================================
# LangSmith provides distributed tracing, token tracking, and debugging
# for LangChain/LangGraph applications.
#
# Setup:
# 1. Set environment variables (see below)
# 2. Visit https://smith.langchain.com to view traces
#
# Environment Variables:
#   LANGCHAIN_TRACING_V2=true          # Enable tracing
#   LANGCHAIN_API_KEY=lsv2_pt_xxx      # Your LangSmith API key
#   LANGCHAIN_PROJECT=orchestration    # Project name in dashboard
#   LANGCHAIN_ENDPOINT=https://api.smith.langchain.com  # Optional, default endpoint
#
# For enterprise/on-premises LangSmith (e.g., Cisco):
#   LANGCHAIN_ENDPOINT=https://circuit-stg.cisco.com/ls/api/v1
#
# What gets traced:
# - All LLM calls (routing decisions, token usage, latency)
# - LangGraph workflow execution (node-by-node timing)
# - Sub-agent calls (A2A requests/responses)
# - Errors and exceptions
# ============================================================================

LANGSMITH_ENABLED = os.getenv('LANGCHAIN_TRACING_V2', 'false').lower() == 'true'
LANGSMITH_PROJECT = os.getenv('LANGCHAIN_PROJECT', 'orchestration-agent')
LANGSMITH_ENDPOINT = os.getenv('LANGCHAIN_ENDPOINT', 'https://api.smith.langchain.com')

if LANGSMITH_ENABLED:
    logger.info("📊 LangSmith tracing enabled")
    logger.info("   Project: %s", LANGSMITH_PROJECT)
    
    # Detect custom endpoint (enterprise/on-prem)
    if LANGSMITH_ENDPOINT != 'https://api.smith.langchain.com':
        # Custom endpoint - likely enterprise installation
        dashboard_url = LANGSMITH_ENDPOINT.replace('/api/v1', '').replace('/api', '')
        logger.info("   Endpoint: %s (enterprise)", LANGSMITH_ENDPOINT)
        logger.info("   Dashboard: %s", dashboard_url)
    else:
        # Public cloud
        logger.info("   Dashboard: https://smith.langchain.com")
    
    if not os.getenv('LANGCHAIN_API_KEY'):
        logger.warning("⚠️  LANGCHAIN_API_KEY not set - tracing will fail!")
else:
    logger.info("📊 LangSmith tracing disabled (set LANGCHAIN_TRACING_V2=true to enable)")

# Supported content types for orchestration agent (used for agent card)
SUPPORTED_CONTENT_TYPES = ['text', 'text/plain']

from .agent_executors_langgraph import OrchestrationAgentExecutor
from .push_notification_handler import ForwardResult, PushNotificationRouter
from .redis_client import init_redis, close_redis
from .oauth2_middleware import OAuth2Middleware
from .properties import (
    AGENT_CARD_REFRESH_INTERVAL_SECONDS,
    AGENT_REGISTRY_APP_ID,
    AGENT_REGISTRY_CATEGORIES,
    AGENT_REGISTRY_INITIAL_RETRIES,
    AGENT_REGISTRY_INITIAL_RETRY_BACKOFF,
    AGENT_REGISTRY_INITIAL_RETRY_DELAY_SECONDS,
    AGENT_REGISTRY_REQUEST_TYPE,
    AGENT_REGISTRY_URL,
    CIRCUIT_LLM_API_APP_KEY,
    CIRCUIT_LLM_API_CLIENT_ID,
    CIRCUIT_LLM_API_ENDPOINT,
    CIRCUIT_LLM_API_MODEL_NAME,
    CIRCUIT_LLM_API_VERSION,
    FRONTEND_ASYNC_PUSH_URL,
    JWKS_URI,
    AUDIENCE,
    ISSUER,
    CIRCUIT_CLIENT_ID,
)

os.environ["CIRCUIT_LLM_API_APP_KEY"] = CIRCUIT_LLM_API_APP_KEY
os.environ["CIRCUIT_LLM_API_CLIENT_ID"] = CIRCUIT_LLM_API_CLIENT_ID
#os.environ["CIRCUIT_LLM_API_CLIENT_SECRET"] = CIRCUIT_LLM_API_CLIENT_SECRET
os.environ["CIRCUIT_LLM_API_ENDPOINT"] = CIRCUIT_LLM_API_ENDPOINT
os.environ["CIRCUIT_LLM_API_MODEL_NAME"] = CIRCUIT_LLM_API_MODEL_NAME
os.environ["CIRCUIT_LLM_API_VERSION"] = CIRCUIT_LLM_API_VERSION
os.environ["JWKS_URI"] = JWKS_URI
os.environ["AUDIENCE"] = AUDIENCE
os.environ["ISSUER"] = ISSUER
os.environ["CIRCUIT_CLIENT_ID"] = CIRCUIT_CLIENT_ID


class MissingAPPKeyError(Exception):
    """Exception for missing APP key."""


class MissingCredentialsError(Exception):
    """Exception for missing Credentials key."""


# ============================================================================
# REST API Models
# ============================================================================
#
# The orchestrator provides two API surfaces:
#   1. REST  (POST /api/chat, POST /api/chat/stream) -- for web/mobile clients
#   2. A2A   (message/send, message/stream at /a2a)  -- for agent-to-agent
#
# Both use the same LangGraph workflow under the hood.
#
# Async push delivery uses the server-configured FRONTEND_ASYNC_PUSH_URL
# (the WebSocket server endpoint).  No per-request webhook URL is needed.
#
# Optional request fields:
#   metadata     -> Accepted but not used by orchestration today.
# ============================================================================


class ChatRequest(BaseModel):
    """Request model for chat endpoint. conversation_id is required (caller must provide it)."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "Generate 5 random numbers between 1 and 100",
                "user_id": "user-123",
                "conversation_id": "conversation-abc",
                "session_id": "session-xyz",
                "request_id": "req-abc-123",
                "metadata": {}
            }
        }
    )
    query: str = Field(..., description="User's query/message")
    user_id: str = Field(..., description="User identifier (required)")
    conversation_id: str = Field(..., description="Conversation ID (required; must be provided by the caller; orchestration does not generate it)")
    session_id: str = Field(..., min_length=1, description="Session id (required); stored in history")
    request_id: str = Field(..., min_length=1, description="Request id from client (required); stored in history and echoed in response")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Reserved for future use; not used by orchestration today")


class ChatResponse(BaseModel):
    """Response model for chat endpoint. Uses conversation_id (single id from client request)."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "conversation_id": "conversation-abc",
                "session_id": "session-xyz",
                "request_id": "req-abc-123",
                "task_id": "task-123",
                "response": "Here are your random numbers: [42, 17, 89, 3, 56]",
                "status": "completed",
                "metadata": {"routed_agent": "random-agent"}
            }
        }
    )
    conversation_id: str = Field(..., description="Conversation ID (echoed from client request)")
    session_id: str = Field(..., description="Session id (echoed from request); stored in history")
    request_id: str = Field(..., description="Request id (echoed from client request); stored in history")
    task_id: str = Field(..., description="Task ID for tracking this request; stored in history")
    response: str = Field(..., description="Agent's response")
    status: str = Field(..., description="Task status (completed, in_progress, etc.)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional response metadata")
    sub_agent_a2a_response: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Raw A2A response events from the sub-agent (events list); present when a sub-agent was called",
    )



class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service health status")
    service: str = Field(..., description="Service name")
    version: str = Field(default="1.0.0", description="Service version")


# ---------------------------------------------------------------------------
# Async webhook (load-management server -> orchestration)
# Payload is flexible; common fields are optional for documentation.
# ---------------------------------------------------------------------------
class AsyncWebhookPayload(BaseModel):
    """Payload from load-management server forwarding subagent async responses."""
    model_config = ConfigDict(extra="allow")
    task_id: Optional[str] = Field(default=None, description="Task or message identifier")
    conversation_id: Optional[str] = Field(default=None, description="Conversation context")
    source: Optional[str] = Field(default=None, description="Subagent or source identifier")
    output: Optional[Any] = Field(default=None, description="Sub-agent result dict, forwarded as-is to frontend content field")


# Response model and status->HTTP mapping (lightweight module for unit tests)
from .webhook_outcomes import AsyncWebhookAcknowledgement, WEBHOOK_STATUS_TO_HTTP


# ============================================================================
# A2A Application Builder
# ============================================================================


def build_a2a_app(host: Optional[str] = None, port: Optional[int] = None) -> Tuple[Any, Any, AgentCard]:
    """Build and return the A2A Starlette application."""
    if os.getenv('CIRCUIT_LLM_API_APP_KEY') is None:
        raise MissingAPPKeyError('CIRCUIT_LLM_API_APP_KEY environment variable not set.')
    if os.getenv('CIRCUIT_LLM_API_CLIENT_ID') is None:
        raise MissingCredentialsError('CIRCUIT_LLM_API_CLIENT_ID environment variable not set.')
    if os.getenv('CIRCUIT_LLM_API_ENDPOINT') is None:
        raise MissingCredentialsError('CIRCUIT_LLM_API_ENDPOINT environment variables not set.')

    # Derive a public URL for the agent card if host/port provided, else use env or fallback
    public_host = host or os.getenv('PUBLIC_HOST') or 'localhost'
    public_port = port or int(os.getenv('PUBLIC_PORT', '8006'))
    public_scheme = os.getenv('PUBLIC_SCHEME', 'http')
    agent_base_url = f'{public_scheme}://{public_host}:{public_port}/'

    # In-cluster A2A calls need time to connect and for SSE streams (avoid "All connection attempts failed")
    httpx_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0))
    push_config_store = InMemoryPushNotificationConfigStore()
    push_sender = BasePushNotificationSender(httpx_client=httpx_client, config_store=push_config_store)

    logger.info("Building orchestration agent application")
    
    # Use the singleton agent registry from app/__init__.py
    # This ensures nodes and main app share the same registry
    from . import get_agent_registry
    agent_registry = get_agent_registry()
    
    # Sub-agents are loaded from the agent registry at startup (lifespan); no static URLs in main flow
    logger.info(
        "Agents will be loaded from registry %s (categories: %s) at startup",
        AGENT_REGISTRY_URL,
        AGENT_REGISTRY_CATEGORIES,
    )
    
    push_notification_router = PushNotificationRouter(
        httpx_client=httpx_client,
        frontend_async_push_url=FRONTEND_ASYNC_PUSH_URL or None,
    )

    from . import set_push_notification_router
    set_push_notification_router(push_notification_router)
    
    agent_executor = OrchestrationAgentExecutor(
        push_notification_router=push_notification_router,
        frontend_async_push_url=FRONTEND_ASYNC_PUSH_URL or None,
    )

    # Create orchestration agent card
    # A2A v0.3.0 uses SSE for streaming (not WebSockets)
    capabilities = AgentCapabilities(streaming=True, push_notifications=True)
    skills = [
        AgentSkill(
            id='licensing-queries',
            name='Licensing Support',
            description='Routes licensing-related questions to Licensing Agent',
            tags=['licensing', 'license management'],
            examples=['Check my license status', 'How do I activate my license?', 'Upgrade to Enterprise'],
        ),
        AgentSkill(
            id='product-information',
            name='Product Information',
            description='Routes product questions to Product Information Agent',
            tags=['product', 'specifications', 'features'],
            examples=['What are the features of product X?', 'Product specs for Y', 'System requirements'],
        ),
        AgentSkill(
            id='poc-test',
            name='POC Test Agent',
            description='Test routing with random number generator',
            tags=['test', 'poc'],
            examples=['Generate random number', 'Test agent'],
        ),
    ]
    
    agent_card = AgentCard(
        name='CIRCUIT Orchestration Agent',
        description='Routes requests to specialized sub-agents (Licensing, Product Information, POC)',
        url=agent_base_url,
        version='1.0.0',
        protocol_version='0.3.0',
        default_input_modes=SUPPORTED_CONTENT_TYPES,
        default_output_modes=SUPPORTED_CONTENT_TYPES,
        capabilities=capabilities,
        skills=skills,
    )

    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor,
        task_store=InMemoryTaskStore(),
        push_config_store=push_config_store,
        push_sender=push_sender,
    )
    server = A2AStarletteApplication(agent_card=agent_card, http_handler=request_handler)
    a2a_app = server.build()
    a2a_app.add_middleware(
        OAuth2Middleware,
        agent_card=agent_card,
        public_paths=['/.well-known/agent.json', '/.well-known/agent-card.json'],
    )
    
    # Simple health endpoints for platform probes
    async def _ok(_request):
        return PlainTextResponse('ok')
    a2a_app.add_route('/healthz', _ok, methods=['GET'])
    a2a_app.add_route('/readyz', _ok, methods=['GET'])
    
    return a2a_app, agent_executor, agent_card


def build_fastapi_app(host: Optional[str] = None, port: Optional[int] = None) -> FastAPI:
    """Build FastAPI application with REST endpoints and A2A sub-application."""
    
    # Build A2A application (for agent-to-agent communication)
    a2a_app, agent_executor, agent_card = build_a2a_app(host=host, port=port)
    
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Initialise Redis for shared state (task mappings, live-agent flags).
        # Non-blocking: falls back to in-memory if Redis is unreachable.
        await init_redis()

        # Load agents from agent registry (sole source of agent cards).
        # Retry with backoff so temporary unavailability (e.g. K8s startup order)
        # does not require waiting for the full refresh interval (default 5 min).
        from . import get_agent_registry
        from .agent_registry_client import AgentRegistryClient
        registry = get_agent_registry()
        client = AgentRegistryClient(
            registry.httpx_client,
            base_url=AGENT_REGISTRY_URL,
            app_id=AGENT_REGISTRY_APP_ID,
            request_type=AGENT_REGISTRY_REQUEST_TYPE,
        )
        delay = AGENT_REGISTRY_INITIAL_RETRY_DELAY_SECONDS
        last_error = None
        for attempt in range(1, AGENT_REGISTRY_INITIAL_RETRIES + 1):
            try:
                count = await registry.load_from_registry(client, AGENT_REGISTRY_CATEGORIES)
                if count > 0:
                    logger.info("Loaded %d agents from agent registry (attempt %d)", count, attempt)
                    break
                if attempt < AGENT_REGISTRY_INITIAL_RETRIES:
                    logger.warning(
                        "Agent registry returned 0 agents (attempt %d/%d, retry in %.1fs)",
                        attempt, AGENT_REGISTRY_INITIAL_RETRIES, delay,
                    )
                    await asyncio.sleep(delay)
                    delay *= AGENT_REGISTRY_INITIAL_RETRY_BACKOFF
                else:
                    logger.warning(
                        "Agent registry returned 0 agents after %d attempts (will retry on refresh)",
                        AGENT_REGISTRY_INITIAL_RETRIES,
                    )
            except Exception as e:
                last_error = e
                if attempt < AGENT_REGISTRY_INITIAL_RETRIES:
                    logger.warning(
                        "Agent registry load failed (attempt %d/%d, retry in %.1fs): %s",
                        attempt, AGENT_REGISTRY_INITIAL_RETRIES, delay, e,
                    )
                    await asyncio.sleep(delay)
                    delay *= AGENT_REGISTRY_INITIAL_RETRY_BACKOFF
                else:
                    logger.warning(
                        "Agent registry load failed after %d attempts (will retry on refresh): %s",
                        AGENT_REGISTRY_INITIAL_RETRIES, e,
                    )

        refresh_interval = AGENT_CARD_REFRESH_INTERVAL_SECONDS
        refresh_task = None

        async def _agent_card_refresh_loop() -> None:
            from . import get_agent_registry, get_a2a_client_handler
            registry = get_agent_registry()
            handler = get_a2a_client_handler()
            # When agents are empty (initial load failed), retry quickly instead
            # of waiting the full refresh interval.
            fast_retry_delay = AGENT_REGISTRY_INITIAL_RETRY_DELAY_SECONDS
            while True:
                has_agents = bool(registry.list_agents())
                wait = refresh_interval if has_agents else fast_retry_delay
                if not has_agents:
                    logger.info(
                        "No agents registered; retrying registry in %.0fs (fast retry)", wait
                    )
                await asyncio.sleep(wait)
                try:
                    await registry.refresh_all_cards()
                    handler.clear_agent_clients()
                    logger.info("Refreshed all sub-agent cards and cleared A2A client cache")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("Agent card refresh failed (will retry next interval): %s", e)

        if refresh_interval > 0:
            refresh_task = asyncio.create_task(_agent_card_refresh_loop())
            logger.info(
                "Agent card refresh enabled: every %s seconds (set AGENT_CARD_REFRESH_INTERVAL_SECONDS=0 to disable)",
                refresh_interval,
            )
        else:
            logger.info("Agent card refresh disabled (AGENT_CARD_REFRESH_INTERVAL_SECONDS=0)")
        yield
        await close_redis()
        if refresh_task is not None:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass

    # Create main FastAPI app (for client-facing REST API)
    app = FastAPI(
        title="CIRCUIT Orchestration Agent API",
        description="Client-facing REST API and Agent-to-Agent (A2A) communication",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    
    # ========================================================================
    # REST API Endpoints (for WebSocket, mobile, REST clients)
    # ========================================================================
    
    # ------------------------------------------------------------------
    # Helper: build initial OrchestrationState from a ChatRequest
    # ------------------------------------------------------------------
    async def _build_rest_state(request: ChatRequest, conversation_id: str, task_id: str,
                                session_id: str, request_id: str, callback=None):
        from .orchestration_state import OrchestrationState
        _live = False
        if agent_executor and agent_executor.push_router:
            _live = await agent_executor.push_router.get_live_agent_mode(conversation_id)
        state: OrchestrationState = {
            "query": request.query,
            "conversation_id": conversation_id,
            "session_id": session_id,
            "request_id": request_id,
            "task_id": task_id,
            "user_id": request.user_id,
            "frontend_async_push_url": FRONTEND_ASYNC_PUSH_URL,
            "history": [],
            "routed_agent": None,
            "routing_reason": None,
            "live_agent_mode": _live,
            "response_chunks": [],
            "final_response": "",
            "sub_agent_task_id": None,
            "sub_agent_status": None,
            "resume_task_id": None,
            "resume_context_id": None,
            "stream_forward_callback": callback,
            "metadata": {"source": "rest_api"},
        }
        return state

    async def _eager_register_conversation(conversation_id: str, task_id: str,
                                              session_id: str = "",
                                              request_id: str = ""):
        """Register conversation delivery config before the graph runs."""
        if agent_executor and agent_executor.push_router and conversation_id:
            await agent_executor.push_router.register_conversation(
                conversation_id=conversation_id,
                orchestration_task_id=task_id,
                frontend_async_push_url=FRONTEND_ASYNC_PUSH_URL,
                session_id=session_id,
                request_id=request_id,
            )

    async def _post_graph_housekeeping(final_state: dict, conversation_id: str,
                                       task_id: str, session_id: str = "",
                                       request_id: str = ""):
        """Persist live agent mode, update conversation, and register task index."""
        push_router = agent_executor.push_router if agent_executor else None
        if not push_router:
            return
        if final_state.get("live_agent_mode") and conversation_id:
            await push_router.set_live_agent_mode(conversation_id, True)
        routed_agent = final_state.get("routed_agent", "unknown")
        if conversation_id:
            await push_router.register_conversation(
                conversation_id=conversation_id,
                orchestration_task_id=task_id,
                frontend_async_push_url=FRONTEND_ASYNC_PUSH_URL,
                routed_agent=routed_agent,
                session_id=session_id or final_state.get("session_id", ""),
                request_id=request_id,
            )
        sub_agent_task_id = final_state.get("sub_agent_task_id")
        if sub_agent_task_id:
            await push_router.register_task(
                sub_agent_task_id=sub_agent_task_id,
                conversation_id=conversation_id,
                orchestration_task_id=task_id,
                routed_agent=routed_agent,
            )

    # ------------------------------------------------------------------
    # REST batch: POST /api/chat
    # ------------------------------------------------------------------
    @app.post("/api/chat", response_model=ChatResponse, tags=["Chat"])
    async def chat_endpoint(request: ChatRequest) -> ChatResponse:
        """
        Batch chat endpoint. Runs the full orchestration graph (load_history,
        route, call_subagent, save_history) and returns the complete response
        with all raw A2A events from the sub-agent.
        """
        try:
            conversation_id = (request.conversation_id or "").strip()
            if not conversation_id:
                raise HTTPException(
                    status_code=400,
                    detail="conversation_id is required.",
                )
            task_id = str(uuid4())
            session_id = request.session_id.strip()
            request_id = request.request_id.strip()

            logger.info(
                "📨 REST chat (batch): user=%s, conversation=%s, query=%s",
                request.user_id, conversation_id[:8], request.query[:50],
            )

            final_response = ""
            routed_agent = None
            status = "processing"
            sub_agent_task_id = None
            final_state: dict = {}

            try:
                await _eager_register_conversation(conversation_id, task_id, session_id,
                                                       request_id=request_id)
                from .orchestration_graph import get_orchestration_graph
                graph = get_orchestration_graph()
                state = await _build_rest_state(request, conversation_id, task_id,
                                                session_id, request_id)
                final_state = await graph.ainvoke(state)

                await _post_graph_housekeeping(final_state, conversation_id,
                                               task_id, session_id,
                                               request_id=request_id)

                final_response = final_state.get("final_response", "")
                routed_agent = final_state.get("routed_agent", "unknown")
                status = final_state.get("sub_agent_status") or "completed"
                sub_agent_task_id = final_state.get("sub_agent_task_id")

            except Exception as e:
                logger.error("Error in orchestration graph: %s", e, exc_info=True)
                status = "error"
                final_response = f"Error processing request: {str(e)}"

            metadata = {
                "routed_agent": routed_agent,
                "user_id": request.user_id,
                "live_agent_mode": final_state.get("live_agent_mode") or False,
            }
            if sub_agent_task_id is not None:
                metadata["sub_agent_task_id"] = sub_agent_task_id

            events = (final_state or {}).get("sub_agent_a2a_events") or []
            sub_agent_a2a_response = {"events": events} if events else None

            return ChatResponse(
                conversation_id=conversation_id,
                session_id=session_id,
                request_id=request_id,
                task_id=task_id,
                response=final_response,
                status=status,
                metadata=metadata,
                sub_agent_a2a_response=sub_agent_a2a_response,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error("Error in chat endpoint: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    # ------------------------------------------------------------------
    # REST stream: POST /api/chat/stream
    # ------------------------------------------------------------------
    @app.post("/api/chat/stream", tags=["Chat"])
    async def chat_stream_endpoint(request: ChatRequest) -> StreamingResponse:
        """
        Streaming chat endpoint. Runs the same orchestration graph as
        ``/api/chat`` but streams each raw A2A event to the client as
        Server-Sent Events (SSE) as they arrive from the sub-agent.

        The graph handles history load, routing, sub-agent call, and
        history save. Events are forwarded in real time via a callback
        that writes to an asyncio.Queue; the SSE generator reads from it.

        For long-running tasks the orchestrator forwards push notifications
        to the configured ``FRONTEND_ASYNC_PUSH_URL`` if the SSE stream times out.
        """
        conversation_id = (request.conversation_id or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id is required.")

        task_id = str(uuid4())
        session_id = request.session_id.strip()
        request_id = request.request_id.strip()

        logger.info(
            "📨 REST chat (stream): user=%s, conversation=%s, query=%s",
            request.user_id, conversation_id[:8], request.query[:50],
        )

        event_queue: asyncio.Queue = asyncio.Queue()

        async def _stream_callback(chunk: dict) -> None:
            await event_queue.put(chunk)

        await _eager_register_conversation(conversation_id, task_id, session_id,
                                               request_id=request_id)

        from .orchestration_graph import get_orchestration_graph
        from .orchestration_nodes import _a2a_result_to_dict

        graph = get_orchestration_graph()
        state = await _build_rest_state(request, conversation_id, task_id,
                                        session_id, request_id, callback=_stream_callback)

        async def _run_graph():
            try:
                final_state = await graph.ainvoke(state)
                await _post_graph_housekeeping(final_state, conversation_id,
                                               task_id, session_id,
                                               request_id=request_id)
                await event_queue.put({"_done": True, "_final_state": final_state})
            except Exception as exc:
                await event_queue.put({"_error": True, "error": str(exc)})

        async def _sse_generator():
            graph_task = asyncio.create_task(_run_graph())
            try:
                start_payload = {"type": "start", "task_id": task_id,
                                 "conversation_id": conversation_id}
                yield f"data: {json.dumps(start_payload)}\n\n"

                while True:
                    item = await event_queue.get()

                    if item.get("_done"):
                        fs = item["_final_state"]
                        end_payload = {
                            "type": "end",
                            "routed_agent": fs.get("routed_agent"),
                            "conversation_id": conversation_id,
                            "status": fs.get("sub_agent_status") or "completed",
                        }
                        yield f"data: {json.dumps(end_payload)}\n\n"
                        break

                    if item.get("_error"):
                        yield f"data: {json.dumps({'type': 'error', 'error': item['error']})}\n\n"
                        break

                    if "error" in item:
                        yield f"data: {json.dumps({'type': 'error', 'error': item['error']})}\n\n"
                        continue

                    result = item.get("result")
                    if result is not None:
                        try:
                            d = _a2a_result_to_dict(result)
                            yield f"data: {json.dumps(d)}\n\n"
                        except Exception as e:
                            logger.warning("Could not serialize A2A result for stream: %s", e)
            except Exception as e:
                logger.error("Error in chat stream SSE: %s", e, exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
            finally:
                if not graph_task.done():
                    graph_task.cancel()

        return StreamingResponse(
            _sse_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/health", response_model=HealthResponse, tags=["Health"])
    async def health_check() -> HealthResponse:
        """Health check endpoint for load balancers and monitoring."""
        return HealthResponse(
            status="healthy",
            service="orchestration-agent",
            version="1.0.0"
        )

    # Probe endpoints at root for Kubernetes readiness/liveness (deployment expects /healthz)
    @app.get("/healthz")
    @app.get("/readyz")
    async def _probe_ok(_request: Request):
        return PlainTextResponse("ok")

    @app.get("/api/agent-info", tags=["Info"])
    async def agent_info() -> Dict[str, Any]:
        """Get orchestration agent information and capabilities."""
        return {
            "name": agent_card.name,
            "description": agent_card.description,
            "version": agent_card.version,
            "protocol_version": agent_card.protocol_version,
            "capabilities": {
                "streaming": agent_card.capabilities.streaming,
                "push_notifications": agent_card.capabilities.push_notifications
            },
            "skills": [
                {
                    "id": skill.id,
                    "name": skill.name,
                    "description": skill.description,
                    "tags": skill.tags
                }
                for skill in agent_card.skills
            ]
        }

    # -------------------------------------------------------------------------
    # Async webhook: load-management server forwards subagent responses here.
    # We forward the payload to the original caller (external GCP WebSocket server)
    # so it can push to the appropriate conversation in the UI.
    # -------------------------------------------------------------------------
    @app.post(
        "/api/webhooks/async-response",
        tags=["Webhooks"],
    )
    async def async_response_webhook(payload: AsyncWebhookPayload):
        """
        Receive async subagent responses from the load-management relay.

        The relay receives responses from subagents and forwards them here.
        We delegate to ``PushNotificationRouter.forward_notification`` which
        resolves the delivery URL (conversation record or FRONTEND_ASYNC_PUSH_URL
        fallback) and POSTs the payload to the WebSocket server.

        Response status and body indicate the outcome so the caller can
        dequeue, retry, or alert (see AsyncWebhookAcknowledgement.status).
        """
        entry_id = str(uuid4())
        logger.info(
            "Async webhook received: id=%s task_id=%s conversation_id=%s source=%s",
            entry_id,
            payload.task_id,
            payload.conversation_id,
            payload.source,
        )

        push_router = getattr(agent_executor, "push_router", None)
        if push_router:
            result: ForwardResult = await push_router.forward_notification(
                payload.model_dump(mode="json"),
                sub_agent_task_id=payload.task_id,
                conversation_id=payload.conversation_id,
            )
            status = result.status
            detail = result.detail
        else:
            logger.warning("PushNotificationRouter not available; webhook not forwarded.")
            status = "unavailable"
            detail = "PushNotificationRouter not available"

        body = AsyncWebhookAcknowledgement(
            status=status,
            received=(status == "forwarded"),
            message=detail,
            id=entry_id,
        )
        return JSONResponse(
            content=body.model_dump(mode="json"),
            status_code=WEBHOOK_STATUS_TO_HTTP[status],
        )

    # ------------------------------------------------------------------
    # Debug introspection endpoints (conversation/task state + history)
    # ------------------------------------------------------------------

    @app.get("/api/debug/state/{conversation_id}", tags=["Debug"])
    async def debug_conversation_state(conversation_id: str):
        """Return conversation record, associated task records, and live-agent
        mode for a given conversation_id.  Reads from Redis (or in-memory
        fallback).  Intended for integration test verification."""
        push_router = getattr(agent_executor, "push_router", None)
        if not push_router:
            return JSONResponse({"error": "push_router not available"}, status_code=503)

        conv = await push_router.get_conversation(conversation_id)

        conv_dict = None
        if conv:
            conv_dict = {
                "conversation_id": conv.conversation_id,
                "orchestration_task_id": conv.orchestration_task_id,
                "request_id": conv.request_id,
                "session_id": conv.session_id,
                "frontend_async_push_url": conv.frontend_async_push_url,
                "routed_agent": conv.routed_agent,
                "live_agent_mode": conv.live_agent_mode,
                "pending_subagent_task_id": conv.pending_subagent_task_id,
                "created_at": conv.created_at.isoformat() if conv.created_at else None,
                "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
            }

        return {"conversation": conv_dict}

    @app.get("/api/debug/task/{sub_agent_task_id}", tags=["Debug"])
    async def debug_task_state(sub_agent_task_id: str):
        """Return task record for a given sub_agent_task_id."""
        push_router = getattr(agent_executor, "push_router", None)
        if not push_router:
            return JSONResponse({"error": "push_router not available"}, status_code=503)

        task = await push_router.get_task(sub_agent_task_id)
        task_dict = None
        if task:
            task_dict = {
                "sub_agent_task_id": task.sub_agent_task_id,
                "conversation_id": task.conversation_id,
                "orchestration_task_id": task.orchestration_task_id,
                "routed_agent": task.routed_agent,
                "created_at": task.created_at.isoformat() if task.created_at else None,
            }

        return {"task": task_dict}

    @app.get("/api/debug/history/{conversation_id}", tags=["Debug"])
    async def debug_history(conversation_id: str, user_id: str = "unknown"):
        """Query the chat-history service for a conversation and return
        the parsed turns plus the raw upstream response for debugging.
        Pass user_id as a query parameter."""
        from .history import ChatHistoryService

        svc = ChatHistoryService()
        payload = {
            "app_id": svc.APP_ID,
            "user_id": user_id,
            "chat_conversation_id": conversation_id,
            "operation": "History",
        }

        raw_response = None
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(svc.url, json=payload, headers={
                    "accept": "application/json",
                    "Content-Type": "application/json",
                }, timeout=15.0)
                raw_response = resp.json()
        except Exception as e:
            raw_response = {"error": str(e)}

        turns = await svc.get_history(conversation_id=conversation_id, user_id=user_id)
        return {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "history_service_url": svc.url,
            "turn_count": len(turns),
            "turns": [{"role": t.role, "content": t.content} for t in turns],
            "raw_upstream_response": raw_response,
        }

    # ========================================================================
    # Mount A2A Sub-Application (for agent-to-agent communication)
    # ========================================================================
    
    app.mount("/a2a", a2a_app)
    logger.info("🔌 Mounted A2A application at /a2a (for agent-to-agent communication)")
    logger.info("🔌 REST API available at /api/* (for client applications)")
    
    return app


# Expose module-level ASGI app for Gunicorn (UvicornWorker)
app = build_fastapi_app()


@click.command()
@click.option('--host', 'host', default='0.0.0.0')
@click.option('--port', 'port', default=8006)
def main(host: str, port: int) -> None:
    """Local runner for the orchestration agent server."""
    try:
        logger.info("=" * 80)
        logger.info("🚀 Starting CIRCUIT Orchestration Agent")
        logger.info("=" * 80)
        logger.info("📍 REST API: http://%s:%s/api/*", host, port)
        logger.info("📍 A2A Protocol: http://%s:%s/a2a/*", host, port)
        logger.info("📍 API Docs: http://%s:%s/docs", host, port)
        logger.info("📍 Health: http://%s:%s/api/health", host, port)
        logger.info("=" * 80)
        
        local_app = build_fastapi_app(host=host, port=port)
        uvicorn.run(local_app, host=host, port=port)
    except MissingAPPKeyError as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    except MissingCredentialsError as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.error("An error occurred during server startup: %s", e)
        sys.exit(1)


if __name__ == '__main__':
    main()