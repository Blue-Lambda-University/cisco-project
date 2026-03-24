"""Client for the external chat history service."""

from typing import List, Optional, Literal
import httpx
import logging

logger = logging.getLogger(__name__)

from .properties import CHAT_HISTORY_URL

ChatRole = Literal['user', 'assistant']


class ChatTurn(dict):
    """Simple wire model: { role: 'user'|'assistant', content: str }"""

    @property
    def role(self) -> ChatRole:
        return self.get('role')  # type: ignore[return-value]

    @property
    def content(self) -> str:
        return self.get('content', '')


class ChatHistoryService:
    """Async client for the centralized chat-history service."""

    APP_ID = "CDC-Orchestration-Agent"

    def __init__(self, url: Optional[str] = None):
        self.url = url or CHAT_HISTORY_URL

    async def get_history(
        self,
        conversation_id: str,
        user_id: str,
    ) -> List[ChatTurn]:
        payload = {
            "app_id": self.APP_ID,
            "user_id": user_id,
            "chat_conversation_id": conversation_id,
            "operation": "History",
        }
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.url, json=payload, headers=headers, timeout=15.0)
                resp = response.json()

            logger.info("📖 Chat History READ response: %s", resp)

            if "data" not in resp or not resp["data"] or "user_history" not in resp["data"]:
                logger.info("📚 No history found for conversation_id %s...", conversation_id[:8])
                return []

            data = resp["data"]["user_history"][0]["chat_history"]
            logger.info("📚 Chat History entries retrieved: %d", len(data) if isinstance(data, list) else 0)
            if isinstance(data, list):
                out: List[ChatTurn] = []
                for item in data:
                    role = item.get("role")
                    content = item.get("content")
                    if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                        out.append(ChatTurn(role=role, content=content))
                logger.info("📊 Returning %d valid turns", len(out))
                return out
            return []
        except Exception as e:
            logger.error("Chat History Read Error: %s", e)
            return []

    async def append_turn(
        self,
        conversation_id: str,
        content: str,
        user_id: str,
        query: str,
        chat_history_metadata=None,
        agent_type: str = "chatbot",
    ) -> httpx.Response:
        """Append a single turn (user query + assistant response) to history."""
        metadata = dict(chat_history_metadata) if chat_history_metadata else {}
        metadata.update({
            "type": "CDC Orchestration Agent",
            "data_source": "CIRCUIT Orchestration Agent",
            "engine": "",
            "agent_type": agent_type,
        })

        logger.info(
            "💾 Writing to history: conversation_id=%s, user_id=%s, query=%s",
            conversation_id[:16], user_id, (query[:50] if query else "N/A"),
        )

        payload = {
            "app_id": self.APP_ID,
            "user_id": user_id,
            "chat_conversation_id": conversation_id,
            "operation": "Add",
            "gen_title": True,
            "query": query,
            "response": content,
            "response_citations": [],
            "data_source": "CIRCUIT Orchestration Agent",
            "metadata": metadata,
        }
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.url, json=payload, headers=headers, timeout=15.0)
            if resp.status_code != 200:
                logger.error(
                    "Chat History Write failed: HTTP %d — %s",
                    resp.status_code, resp.text[:200],
                )
                raise httpx.HTTPStatusError(
                    f"History write returned {resp.status_code}",
                    request=resp.request, response=resp,
                )
            return resp
        except httpx.HTTPStatusError:
            raise
        except Exception as e:
            logger.error("Chat History Write Error: %s", e)
            raise
