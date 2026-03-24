"""A2A protocol client for streaming messages to sub-agents."""

import logging
import httpx
from typing import Optional, AsyncIterator, List, Any
from uuid import uuid4
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    Message,
    TextPart,
    MessageSendParams,
    MessageSendConfiguration,
    SendStreamingMessageRequest,
    PushNotificationConfig,
    PushNotificationAuthenticationInfo,
)
from .agent_router import SubAgentConfig
from .properties import get_push_notification_auth

logger = logging.getLogger(__name__)

MAX_SUBAGENT_HISTORY_CONTENT_CHARS = 500


def _format_conversation_history_for_subagent(
    history: List[Any],
    max_messages: int | None = None,
    max_content_chars: int = MAX_SUBAGENT_HISTORY_CONTENT_CHARS,
) -> tuple[str, list[dict[str, str]]]:
    """
    Format conversation history for inclusion in the subagent request.

    Returns:
        (context_string, structured_list)
        - context_string: Human-readable block to prepend to the user query so the
          subagent sees prior context in the message body (e.g. project info before
          a licensing question).
        - structured_list: List of {"role": "user"|"assistant", "content": "..."}
          for message.metadata so subagents can use it programmatically.
    """
    from .chat_summarizer import format_history_for_prompt
    from .properties import RECENT_TURNS

    formatted_text, structured = format_history_for_prompt(
        history or [],
        max_messages=max_messages if max_messages is not None else RECENT_TURNS,
        max_content_chars=max_content_chars,
    )
    context_string = "Previous conversation:\n" + formatted_text + "\n\n" if formatted_text else ""
    return context_string, structured


class A2AClientHandler:
    """Wrapper around A2A client for downstream sub-agent calls."""
    
    def __init__(self, httpx_client: Optional[httpx.AsyncClient] = None):
        # In-cluster calls need time to connect and for SSE streams to run.
        # Short timeouts caused "All connection attempts failed" / SSE stream ended.
        timeout = httpx.Timeout(30.0, read=120.0)  # 30s connect, 120s read for streaming
        self.httpx_client = httpx_client or httpx.AsyncClient(timeout=timeout)
        self.agent_clients: dict[str, A2AClient] = {}

    async def _get_agent_client(self, agent_config: SubAgentConfig) -> Optional[A2AClient]:
        """Get or create A2A client for an agent."""
        if agent_config.name in self.agent_clients:
            return self.agent_clients[agent_config.name]
        
        try:
            # Fetch agent card if not cached
            from .agent_router import AgentRegistry
            registry = AgentRegistry(self.httpx_client)
            registry.register_agent(agent_config)
            agent_card = await registry.fetch_agent_card(agent_config)
            
            if not agent_card:
                logger.error("Failed to fetch agent card for %s", agent_config.name)
                return None

            # Use our configured URL for requests. The card may advertise a different URL
            # (e.g. localhost or external) that is unreachable from this pod (causes "All connection attempts failed").
            base_url = agent_config.url.rstrip("/")
            card_for_client = agent_card.model_copy(update={"url": f"{base_url}/"})

            # Create A2A client
            client = A2AClient(
                httpx_client=self.httpx_client,
                agent_card=card_for_client
            )
            
            self.agent_clients[agent_config.name] = client
            logger.info("Created A2A client for %s", agent_config.name)
            return client
            
        except Exception as e:
            logger.error("Error creating A2A client for %s: %s", agent_config.name, e)
            return None
    
    def clear_agent_clients(self) -> None:
        """Clear cached A2A clients so next use re-fetches agent cards. Call after agent card refresh."""
        self.agent_clients.clear()
        logger.debug("Cleared A2A agent client cache")
    
    def _build_push_config(
        self,
        push_relay_url: Optional[str],
        metadata: dict,
    ) -> Optional[PushNotificationConfig]:
        """
        Build PushNotificationConfig for async push only.

        Sync: sub-agent replies on the open stream; no push URL needed.
        Async: sub-agent pushes to the relay only; we pass only push_relay_url.
        We do not send the orchestration webhook URL to the sub-agent.
        """
        if not push_relay_url:
            return None
        metadata["push_relay_url"] = push_relay_url
        auth = get_push_notification_auth()
        config_kw: dict = {"url": push_relay_url}
        if auth.get("id"):
            config_kw["id"] = auth["id"]
        if auth.get("token"):
            config_kw["token"] = auth["token"]
        if auth.get("credentials"):
            config_kw["authentication"] = PushNotificationAuthenticationInfo(
                schemes=["bearer"],
                credentials=auth["credentials"],
            )
        return PushNotificationConfig(**config_kw)

    async def send_message_streaming(
        self,
        agent_config: SubAgentConfig,
        query: str,
        context_id: str,
        task_id: Optional[str] = None,
        push_relay_url: Optional[str] = None,
        metadata: Optional[dict] = None,
        conversation_history: Optional[List[Any]] = None,
    ) -> AsyncIterator[dict]:
        """
        Send a streaming message to a sub-agent.
        Yields chunks as they arrive.

        Args:
            task_id: When resuming a paused (input-required) sub-agent task,
                pass the sub-agent's task ID so it can locate and continue
                the existing task.  None for new tasks.

        Sync: response comes on the stream; no push. Async: only relay URL is passed. Auth from env.
        """
        try:
            client = await self._get_agent_client(agent_config)
            if not client:
                return

            # Include conversation history so subagent has context
            body_text = query
            msg_metadata = dict(metadata or {})
            if conversation_history:
                context_string, structured = _format_conversation_history_for_subagent(conversation_history)
                if context_string:
                    body_text = context_string + "Current question: " + query
                    msg_metadata["conversation_history"] = structured
                    logger.debug("Including %d prior turns in message to %s", len(structured), agent_config.name)
            
            config = MessageSendConfiguration(accepted_output_modes=['text'])
            push_config = self._build_push_config(push_relay_url, msg_metadata)
            if push_config:
                config.push_notification_config = push_config
            
            message = Message(
                role='user',
                parts=[TextPart(text=body_text)],
                message_id=str(uuid4()),
                task_id=task_id,
                context_id=context_id,
                metadata=msg_metadata,
            )

            params = MessageSendParams(
                message=message,
                configuration=config,
                context_id=context_id  # Add context_id to params level
            )
            
            request = SendStreamingMessageRequest(
                id=str(uuid4()),
                params=params
            )
            
            # Stream response
            async for result in client.send_message_streaming(request):
                yield {
                    'result': result,
                    'agent': agent_config.name
                }
                
        except Exception as e:
            logger.warning("SSE stream ended for %s (likely timeout during async processing): %s", agent_config.name, e)
            yield {
                'error': str(e),
                'agent': agent_config.name
            }
    
