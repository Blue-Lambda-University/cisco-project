"""A2A SDK executor backed by the LangGraph orchestration workflow."""

import logging
from typing import Optional
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    InternalError,
    InvalidParamsError,
    Message,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
    TextPart,
)
from a2a.utils import (
    new_agent_text_message,
    new_task,
)
from a2a.utils.errors import ServerError

from .a2a_response_utils import build_text_response_parts
from .orchestration_graph import get_orchestration_graph
from .orchestration_state import OrchestrationState
from .push_notification_handler import PushNotificationRouter

logger = logging.getLogger(__name__)


def a2a_object_to_dict(obj) -> dict:
    """
    Universal utility function to convert A2A objects to dictionaries for logging.
    """
    try:
        if hasattr(obj, 'model_dump') and callable(getattr(obj, 'model_dump')):
            return obj.model_dump(mode="json")
    except Exception as e:
        return {
            'conversion_error': str(e),
            'object_type': str(type(obj)),
            'error_type': str(type(e)),
        }
    if isinstance(obj, dict):
        return obj
    return {'raw': str(obj)}


def _message_to_dict(message) -> dict:
    """Convert A2A Message object to dictionary for logging purposes."""
    return a2a_object_to_dict(message)


_EXECUTOR_FINAL_STATES = frozenset({
    TaskState.completed,
    TaskState.failed,
    TaskState.canceled,
    TaskState.rejected,
    TaskState.input_required,
})


def _unwrap_streaming_response(raw_result) -> Task | Message | TaskStatusUpdateEvent | TaskArtifactUpdateEvent | None:
    """Unwrap SendStreamingMessageResponse to its inner A2A event."""
    inner = raw_result
    if hasattr(raw_result, "root") and hasattr(raw_result.root, "result"):
        inner = raw_result.root.result
    return inner


class OrchestrationAgentExecutor(AgentExecutor):
    """
    A2A executor for the orchestration agent (LangGraph workflow).

    Handles A2A ``message/send`` (batch) and ``message/stream`` (SSE) requests.
    Both share the same LangGraph: load_history -> route -> call_subagent ->
    save_history.

    For A2A streaming, the executor sets ``stream_forward_callback`` on the
    graph state so every sub-agent event is forwarded to the caller in
    real time via ``event_queue.enqueue_event()``.  For A2A batch
    (``message/send``), the A2A SDK's ``DefaultRequestHandler`` buffers
    events internally and returns the final result; the executor still sets
    the callback so the unified ``call_subagent_node`` can collect all events
    regardless of transport.
    """
    
    def __init__(
        self,
        push_notification_router: PushNotificationRouter = None,
        frontend_async_push_url: Optional[str] = None,
    ):
        """
        Initialize the executor with LangGraph.
        
        Args:
            push_notification_router: Optional router for push notifications
            frontend_async_push_url: Configured URL for async push delivery to the WebSocket server
        """
        self.graph = get_orchestration_graph()
        self.push_router = push_notification_router
        self.frontend_async_push_url = frontend_async_push_url
    
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """
        Execute orchestration workflow using LangGraph.
        
        This method:
        1. Extracts request parameters
        2. Builds initial state for LangGraph
        3. Runs the workflow (load_history → route → call_subagent → save_history)
        4. Sends results back to client
        
        Args:
            context: Request context from A2A SDK
            event_queue: Event queue for task updates
        """
        logger.info("🚀 Executing OrchestrationAgentExecutor with LangGraph")
        
        agent_request = _message_to_dict(context.message)
        user_id = agent_request.get('metadata', {}).get('user_id', 'unknown')
        
        # ========== Extract Query ==========
        query = context.get_user_input('query')
        if not query:
            msg = getattr(context, 'message', None)
            if msg and getattr(msg, 'parts', None):
                for p in msg.parts:
                    try:
                        if hasattr(p, 'root') and isinstance(p.root, TextPart):
                            query = p.root.text
                            break
                    except Exception:
                        pass
                    if isinstance(p, TextPart):
                        query = p.text
                        break
        
        if not query or (isinstance(query, str) and query.strip() == ""):
            raise InvalidParamsError("Missing user query. Provide a 'query' field or a text message part.")
        
        logger.info("📝 Query: %s...", query[:100])

        # ========== Get or Create Task ==========
        msg = getattr(context, 'message', None)
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)
        
        # ========== Extract conversation_id, session_id, request_id (client's conversation) ==========
        # A2A SDK gives task.id per message. We need the client's conversation_id for history.
        conversation_id = task.context_id  # default (A2A task context)
        session_id = ""
        request_id = task.id  # fallback for A2A when client does not send request_id
        # Live agent mode: only from our stored per-conversation state (set when trigger phrase said)
        live_agent_mode = False
        if msg and hasattr(msg, 'metadata') and isinstance(msg.metadata, dict):
            meta = msg.metadata
            conversation_id = meta.get('conversation_id') or meta.get('client_context_id') or task.context_id
            session_id = (meta.get('session_id') or "").strip()
            req_from_meta = (meta.get('request_id') or "").strip()
            if req_from_meta:
                request_id = req_from_meta
            logger.info("📌 Using conversation_id: %s...", conversation_id[:16])
        if self.push_router and conversation_id:
            live_agent_mode = await self.push_router.get_live_agent_mode(conversation_id)
            if live_agent_mode:
                logger.info("📡 Using stored live_agent_mode for conversation")
        
        # ========== Stream forward (A2A in / A2A out) ==========
        # Sub-agent events carry the sub-agent's task ID. The A2A SDK
        # event queue is bound to the orchestrator's task ID, so we
        # re-emit each event through TaskUpdater — preserving content
        # parts exactly, only remapping task/context IDs.
        #
        # Event type mapping (per A2A spec):
        #   TaskArtifactUpdateEvent  → updater.add_artifact()
        #   TaskStatusUpdateEvent    → updater.update_status()
        #   Task snapshot / Message  → updater.update_status() / start_work()
        #
        # Final states (completed/failed/canceled/rejected/input-required)
        # are skipped here; the executor sends them after the graph finishes.
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        async def forward_subagent_event(chunk: dict) -> None:
            if chunk.get("error"):
                err_msg = new_agent_text_message(
                    f"Sub-agent stream error: {chunk['error']}",
                    task.context_id,
                    task.id,
                )
                await event_queue.enqueue_event(err_msg)
                return

            r = chunk.get("result")
            if r is None:
                return

            inner = _unwrap_streaming_response(r)
            if inner is None:
                return

            try:
                if isinstance(inner, TaskArtifactUpdateEvent):
                    artifact = inner.artifact
                    await updater.add_artifact(
                        parts=artifact.parts,
                        artifact_id=artifact.artifact_id,
                        name=artifact.name,
                        metadata=artifact.metadata,
                        append=inner.append,
                        last_chunk=inner.last_chunk,
                    )

                elif isinstance(inner, TaskStatusUpdateEvent):
                    if inner.status.state in _EXECUTOR_FINAL_STATES:
                        return
                    msg = None
                    if inner.status.message and getattr(inner.status.message, "parts", None):
                        msg = updater.new_agent_message(
                            inner.status.message.parts,
                            metadata=inner.status.message.metadata,
                        )
                    await updater.update_status(
                        inner.status.state,
                        message=msg,
                        metadata=inner.metadata,
                    )

                elif isinstance(inner, Task):
                    if inner.status and inner.status.state not in _EXECUTOR_FINAL_STATES:
                        msg = None
                        if inner.status.message and getattr(inner.status.message, "parts", None):
                            msg = updater.new_agent_message(
                                inner.status.message.parts,
                                metadata=inner.status.message.metadata,
                            )
                        await updater.update_status(
                            inner.status.state,
                            message=msg,
                            metadata=inner.metadata,
                        )

                elif isinstance(inner, Message):
                    if getattr(inner, "parts", None):
                        msg = updater.new_agent_message(
                            inner.parts,
                            metadata=inner.metadata,
                        )
                        await updater.start_work(message=msg)

            except Exception as e:
                logger.warning("Error forwarding sub-agent event: %s", e)

        # ========== Build Initial State for LangGraph ==========
        initial_state: OrchestrationState = {
            "query": query,
            "conversation_id": conversation_id,
            "session_id": session_id,
            "request_id": request_id,
            "task_id": task.id,
            "user_id": user_id,
            "frontend_async_push_url": self.frontend_async_push_url,
            "history": [],
            "routed_agent": None,
            "routing_reason": None,
            "live_agent_mode": live_agent_mode,
            "response_chunks": [],
            "final_response": "",
            "sub_agent_task_id": None,
            "sub_agent_status": None,
            "resume_task_id": None,
            "resume_context_id": None,
            "stream_forward_callback": forward_subagent_event,
            "metadata": {
                "source": "orchestration_agent",
                "user_id": user_id
            }
        }
        
        logger.info("🎬 Initial state prepared: conversation_id=%s..., query=%s...", conversation_id[:16], query[:50])
        
        # ========== Eager conversation registration ==========
        if self.push_router and conversation_id:
            await self.push_router.register_conversation(
                conversation_id=conversation_id,
                orchestration_task_id=task.id,
                frontend_async_push_url=self.frontend_async_push_url,
                session_id=session_id,
                request_id=request_id,
            )

        try:
            # ========== Run LangGraph Workflow ==========
            logger.info("▶️ Invoking LangGraph orchestration workflow")
            
            # Execute the graph: load_history → route_agent → call_subagent → save_history
            final_state = await self.graph.ainvoke(initial_state)
            
            logger.info("✅ LangGraph workflow completed")
            logger.info("   - Routed agent: %s", final_state.get('routed_agent'))
            logger.info("   - Routing reason: %s", final_state.get('routing_reason'))
            logger.info("   - Response length: %d", len(final_state.get('final_response', '')))
            
            # ========== Extract Results ==========
            final_response = final_state.get('final_response', '')
            routed_agent = final_state.get('routed_agent', 'unknown')
            sub_agent_task_id = final_state.get('sub_agent_task_id')
            
            # Persist live agent mode so next message in this conversation gets relay URL without caller sending flag
            if final_state.get('live_agent_mode') and self.push_router and conversation_id:
                await self.push_router.set_live_agent_mode(conversation_id, True)
            
            # Update conversation with selected agent; register task reverse index
            if self.push_router and conversation_id:
                await self.push_router.register_conversation(
                    conversation_id=conversation_id,
                    orchestration_task_id=task.id,
                    frontend_async_push_url=self.frontend_async_push_url,
                    routed_agent=routed_agent,
                    session_id=session_id or final_state.get("session_id", ""),
                    request_id=request_id,
                )
            if sub_agent_task_id and self.push_router:
                await self.push_router.register_task(
                    sub_agent_task_id=sub_agent_task_id,
                    conversation_id=conversation_id,
                    orchestration_task_id=task.id,
                    routed_agent=routed_agent,
                )
                logger.info("🔗 Registered task index: orch=%s... → sub=%s...", task.id[:8], sub_agent_task_id[:8])
            
            # ========== Send Task Status (A2A format) ==========
            sa_status = final_state.get("sub_agent_status") or "completed"
            status_msg = None
            if final_response:
                status_msg = updater.new_agent_message(
                    build_text_response_parts(final_response)
                )

            if sa_status == "input-required":
                await updater.update_status(
                    TaskState.input_required,
                    message=status_msg,
                )
                logger.info("⏸️ Task paused (input-required) — awaiting user reply")
            else:
                await updater.complete(message=status_msg)
                logger.info("✅ Task completed successfully")
        
        except Exception as e:
            logger.error("❌ Error in LangGraph orchestration: %s", e, exc_info=True)
            await updater.update_status(
                TaskState.failed,
                new_agent_text_message(
                    f"An error occurred during execution: {str(e)}",
                    task.context_id,
                    task.id,
                ),
            )
            raise ServerError(error=InternalError()) from e
    
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> Task:
        """
        Cancel a task.
        
        Args:
            context: Request context
            event_queue: Event queue
            
        Returns:
            Cancelled task
        """
        task = context.current_task
        if task:
            updater = TaskUpdater(event_queue, task.id, task.context_id)
            await updater.update_status(
                TaskState.canceled,
                new_agent_text_message(
                    "Task has been cancelled.",
                    task.context_id,
                    task.id,
                ),
            )
            return task
        
        raise InvalidParamsError("No current task to cancel.")
