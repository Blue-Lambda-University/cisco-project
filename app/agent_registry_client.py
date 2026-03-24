"""
Client for the external agent registry service.
Fetches agent definitions by category and maps them to AgentCard and SubAgentConfig.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from .agent_router import SubAgentConfig


logger = logging.getLogger(__name__)

# Default content types when registry omits them
DEFAULT_INPUT_MODES = ["application/json", "text/plain"]
DEFAULT_OUTPUT_MODES = ["application/json", "text/plain"]


def _slugify(name: str, max_length: int = 64) -> str:
    """Produce a stable, URL-friendly identifier from a display name."""
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return slug[:max_length] if slug else "agent"


def _unique_slug(slug: str, existing: set, agent_id: str) -> str:
    """Ensure slug is unique by appending short agent_id suffix if needed."""
    if slug not in existing:
        existing.add(slug)
        return slug
    suffix = agent_id.replace("-", "")[:8] if agent_id else ""
    candidate = f"{slug}-{suffix}" if suffix else f"{slug}-1"
    while candidate in existing:
        candidate = f"{candidate}-"
    existing.add(candidate)
    return candidate


def _registry_agent_to_agent_card(payload: Dict[str, Any]) -> AgentCard:
    """Map a single agent object from the registry API to an AgentCard."""
    caps = payload.get("capabilities") or {}
    capabilities = AgentCapabilities(
        streaming=bool(caps.get("streaming", False)),
        push_notifications=bool(caps.get("pushNotifications", False)),
    )
    skills = []
    for s in payload.get("skills") or []:
        skills.append(
            AgentSkill(
                id=str(s.get("id", "")),
                name=str(s.get("name", "")),
                description=str(s.get("description", "")),
                tags=list(s.get("tags") or []),
                examples=list(s.get("examples") or []),
            )
        )
    url = (payload.get("url") or "").rstrip("/")
    if url and not url.endswith("/"):
        url = f"{url}/"
    return AgentCard(
        name=payload.get("name") or "Unnamed Agent",
        description=payload.get("description") or "",
        url=url or "/",
        version=str(payload.get("version") or "1.0"),
        protocol_version="0.3.0",
        default_input_modes=payload.get("defaultInputModes") or DEFAULT_INPUT_MODES,
        default_output_modes=payload.get("defaultOutputModes") or DEFAULT_OUTPUT_MODES,
        capabilities=capabilities,
        skills=skills,
    )


def _registry_agent_to_sub_agent_config(
    payload: Dict[str, Any],
    used_slugs: set,
) -> SubAgentConfig:
    """Map a single agent from the registry API to SubAgentConfig with card pre-filled."""
    agent_id = payload.get("agent_id") or ""
    display_name = payload.get("name") or "Unnamed Agent"
    slug = _unique_slug(_slugify(display_name), used_slugs, agent_id)
    url = (payload.get("url") or "").strip()
    if url and not url.endswith("/"):
        url = f"{url}/"
    agent_card = _registry_agent_to_agent_card(payload)
    push_relay_url = (
        (payload.get("pushRelayUrl") or payload.get("push_relay_url") or "").strip()
        or None
    )
    if not push_relay_url:
        env_key = f"{slug.upper().replace('-', '_')}_PUSH_RELAY_URL"
        push_relay_url = os.environ.get(env_key, "").strip() or None
    return SubAgentConfig(
        name=slug,
        url=url or "/",
        agent_card=agent_card,
        display_name=display_name,
        push_relay_url=push_relay_url,
    )


class AgentRegistryClient:
    """
    Client for the external agent registry API.
    POST /api/external/agent/agents_by_category with appId, requestType, category.
    """

    def __init__(
        self,
        httpx_client: httpx.AsyncClient,
        base_url: str,
        app_id: str = "circuit-external-agent",
        request_type: str = "api",
    ):
        self.httpx_client = httpx_client
        self.base_url = base_url.rstrip("/")
        self.app_id = app_id
        self.request_type = request_type

    def _url(self) -> str:
        return f"{self.base_url}/api/external/agent/agents_by_category"

    async def fetch_agents_by_category(
        self,
        categories: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Fetch agents for the given categories.
        Returns list of raw agent dicts from the registry (Agents array).
        """
        payload = {
            "appId": self.app_id,
            "requestType": self.request_type,
            "category": list(categories),
        }
        try:
            resp = await self.httpx_client.post(
                self._url(),
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "success" or data.get("code") != 200:
                logger.warning(
                    "Agent registry returned status=%s code=%s",
                    data.get("status"),
                    data.get("code"),
                )
            agents = data.get("Agents") or data.get("agents") or []
            logger.info(
                "Agent registry returned %d agents for categories %s",
                len(agents),
                categories,
            )
            return agents
        except httpx.HTTPError as e:
            logger.error("Agent registry request failed: %s", e)
            return []
        except Exception as e:
            logger.error("Agent registry parse/error: %s", e, exc_info=True)
            return []

    async def fetch_sub_agent_configs(
        self,
        categories: List[str],
    ) -> List[SubAgentConfig]:
        """
        Fetch agents by category and return SubAgentConfig list with cards pre-filled.
        Only includes agents with status 'activated' and a non-empty url.
        """
        raw = await self.fetch_agents_by_category(categories)
        used_slugs: set = set()
        configs: List[SubAgentConfig] = []
        for item in raw:
            status = (item.get("status") or "").lower()
            if status != "activated":
                logger.debug("Skipping agent %s (status=%s)", item.get("name"), status)
                continue
            url = (item.get("url") or "").strip()
            if not url:
                logger.debug("Skipping agent %s (no url)", item.get("name"))
                continue
            config = _registry_agent_to_sub_agent_config(item, used_slugs)
            configs.append(config)
        return configs
