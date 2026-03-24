"""LLM-based query routing to registered sub-agents."""

import asyncio
import logging
import httpx
from typing import Optional, Dict, List, TYPE_CHECKING
from dataclasses import dataclass
from a2a.client import A2ACardResolver
from a2a.types import AgentCard
from .llm import get_llm

if TYPE_CHECKING:
    from .agent_registry_client import AgentRegistryClient

logger = logging.getLogger(__name__)


@dataclass
class SubAgentConfig:
    """
    Configuration for a sub-agent discovered via A2A protocol.
    Skills are extracted from the agent's card after discovery.
    """
    name: str  # Logical name/slug for identification and registry key
    url: str  # Base URL where agent card is published (/.well-known/agent.json)
    agent_card: Optional[AgentCard] = None
    requires_auth: bool = True  # Whether OAuth2 auth is required
    display_name: Optional[str] = None  # Human-readable name (e.g. from registry "name" field)
    push_relay_url: Optional[str] = None  # If set, sub-agent sends push to this URL (e.g. Server A); relay then forwards to orchestration

    @property
    def display_name_or_name(self) -> str:
        """Human-readable name for prompts; falls back to name if no display_name."""
        return self.display_name or self.name

    @property
    def skills(self) -> List[str]:
        """Extract skill IDs from agent card."""
        if not self.agent_card or not self.agent_card.skills:
            return []
        return [skill.id for skill in self.agent_card.skills]

    @property
    def skill_names(self) -> List[str]:
        """Extract skill names from agent card."""
        if not self.agent_card or not self.agent_card.skills:
            return []
        return [skill.name for skill in self.agent_card.skills]

    @property
    def skill_descriptions(self) -> List[str]:
        """Get skill descriptions for routing (keyed by name, not UUID)."""
        if not self.agent_card or not self.agent_card.skills:
            return []
        return [f"{skill.name}: {skill.description or ''}" for skill in self.agent_card.skills]


class AgentRegistry:
    """
    Manages sub-agent discovery via A2A protocol or external agent registry.
    When using the registry, cards are loaded from the registry API; otherwise
    cards are discovered from /.well-known/agent.json at each agent URL.
    """
    
    def __init__(self, httpx_client: httpx.AsyncClient):
        self.httpx_client = httpx_client
        self.agents: Dict[str, SubAgentConfig] = {}
        self._registry_client: Optional["AgentRegistryClient"] = None
        self._registry_categories: Optional[List[str]] = None
    
    def register_agent(self, config: SubAgentConfig) -> None:
        """
        Register a sub-agent configuration.
        Agent card will be fetched lazily on first use via fetch_agent_card().
        
        Args:
            config: SubAgentConfig with name and URL
        """
        self.agents[config.name] = config
        logger.info("Registered agent: %s at %s (card will be discovered on first use)", config.name, config.url)
    
    async def fetch_agent_card(self, agent_config: SubAgentConfig) -> Optional[AgentCard]:
        """
        Return cached card or fetch via A2A discovery from /.well-known/agent.json.
        Cards are pre-filled when agents are loaded from the registry; this A2A
        discovery path is used for periodic card refresh and as a fallback.
        """
        if agent_config.agent_card:
            return agent_config.agent_card

        max_attempts = 3
        base_delay = 2.0

        for attempt in range(1, max_attempts + 1):
            try:
                logger.info("Discovering agent card via A2A from %s (attempt %d/%d)", agent_config.url, attempt, max_attempts)
                card_resolver = A2ACardResolver(
                    httpx_client=self.httpx_client,
                    base_url=agent_config.url
                )
                agent_card = await card_resolver.get_agent_card()
                agent_config.agent_card = agent_card

                skills = agent_config.skills
                logger.info(
                    "Successfully discovered agent card for %s. Skills: %s, Capabilities: %s",
                    agent_config.name, skills, agent_card.capabilities,
                )
                return agent_card
            except Exception as e:
                if attempt < max_attempts:
                    delay = base_delay * attempt
                    logger.warning(
                        "Agent card discovery failed for %s (attempt %d/%d): %s. Retrying in %.0fs...",
                        agent_config.name, attempt, max_attempts, e, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Failed to discover agent card for %s at %s: %s",
                        agent_config.name, agent_config.url, e,
                    )
                    return None
        return None
    
    
    async def load_from_registry(
        self,
        registry_client: "AgentRegistryClient",
        categories: List[str],
    ) -> int:
        """
        Load sub-agents from the agent registry by category.
        Replaces currently registered agents only when the registry returns
        results; keeps the previous set if the registry returns empty
        (avoids wiping agents on transient failures).
        Returns the number of agents registered.
        """
        configs = await registry_client.fetch_sub_agent_configs(categories)
        self._registry_client = registry_client
        self._registry_categories = list(categories)
        if not configs and self.agents:
            logger.warning(
                "Registry returned 0 agents; keeping %d existing agents (categories: %s)",
                len(self.agents),
                categories,
            )
            return len(self.agents)
        self.agents.clear()
        for config in configs:
            self.agents[config.name] = config
            logger.info(
                "Registered agent from registry: %s at %s (card pre-filled)",
                config.name,
                config.url,
            )
        logger.info("Loaded %d agents from registry (categories: %s)", len(configs), categories)
        return len(configs)
    
    async def refresh_all_cards(self) -> None:
        """Refresh agent cards from the registry (main flow always uses registry)."""
        if self._registry_client and self._registry_categories:
            count = await self.load_from_registry(
                self._registry_client,
                self._registry_categories,
            )
            logger.info("Refreshed %d agents from registry", count)
            return
        # Fallback: A2A discovery per URL when registry is not available
        for agent_config in self.agents.values():
            agent_config.agent_card = None
            await self.fetch_agent_card(agent_config)
    
    def get_agent(self, name: str) -> Optional[SubAgentConfig]:
        """Get an agent configuration by name."""
        return self.agents.get(name)
    
    def list_agents(self) -> List[SubAgentConfig]:
        """List all registered agents."""
        return list(self.agents.values())


class RoutingDecisionMaker:
    """Makes routing decisions using LLM analysis."""
    
    def __init__(self, agent_registry: AgentRegistry):
        self.registry = agent_registry
    
    async def route(
        self,
        query: str,
        history: Optional[List] = None
    ) -> Optional[SubAgentConfig]:
        """
        Analyze query with conversation context and select appropriate sub-agent.
        
        Args:
            query: Current user query
            history: Previous conversation messages (LangChain format)
        
        Returns:
            Selected SubAgentConfig or None if no match
        """
        agents = self.registry.list_agents()

        logger.info(
            "🧭 Routing started: query='%s' registered_agents=%d",
            query[:100] + ("..." if len(query) > 100 else ""),
            len(agents),
        )

        if not agents:
            logger.warning("No agents registered for routing")
            return None
        
        # Ensure agent cards are discovered (lazy A2A discovery), in parallel
        missing = [a for a in agents if not a.agent_card]
        if missing:
            logger.info("Discovering cards for %d agents without cached cards", len(missing))
            await asyncio.gather(*[self.registry.fetch_agent_card(a) for a in missing])
        
        # Build agent descriptions from discovered agent cards (use display name in prompt)
        agent_descriptions = []
        agent_name_list = []
        for agent in agents:
            label = agent.display_name_or_name
            agent_name_list.append(label)
            if agent.agent_card and agent.skill_names:
                skills_str = ", ".join(agent.skill_names)
                descriptions = agent.skill_descriptions
                desc_text = " | ".join(descriptions) if descriptions else ""
                agent_descriptions.append(
                    f"- {label}: Skills: {skills_str}. {desc_text}"
                )
            else:
                agent_descriptions.append(
                    f"- {label}: (card not yet discovered)"
                )

        for agent in agents:
            logger.info(
                "📋 Agent available: name=%s display_name=%s url=%s skills=%s",
                agent.name,
                agent.display_name,
                agent.url,
                agent.skill_names or "(no card)",
            )

        from .chat_summarizer import format_history_for_prompt
        from .properties import RECENT_TURNS
        history_text, _ = format_history_for_prompt(
            history or [],
            max_messages=RECENT_TURNS,
            max_content_chars=200,
        )

        # Build context-aware routing prompt
        agent_names_formatted = ", ".join(f'"{n}"' for n in agent_name_list)

        routing_prompt = f"""You are an intelligent routing system that analyzes user queries and conversation history to determine intent and route to the most appropriate agent.

### Available Agents:
{chr(10).join(agent_descriptions)}

### Conversation History:
{history_text if history_text else "(No previous conversation)"}

### Current User Query:
"{query}"

### Routing Instructions:

1. **Analyze Context**: Consider the conversation history and how the current query relates to previous messages.

2. **Determine Intent**: Identify the user's intent:
   - Is this a continuation of a previous topic?
   - Is this a new question requiring a different agent?
   - What domain does this query belong to?

3. **Select Agent**: Choose the agent whose skills best match the user's intent based on:
   - Direct skill match with the query
   - Conversation flow and context
   - Explicit user guidance or preferences

### Context-Awareness Rules:

- **Preserve Flow**: If the previous message was about a topic and the current query naturally follows, consider routing to the same domain unless intent has clearly shifted.

- **Detect Intent Changes**: Look for explicit signals that the user is changing topics:
  - "Now let me ask about..."
  - "Switching to..."
  - "Different question:"
  - Complete topic change

### Output Format:
Respond with ONLY valid JSON in this exact format:
{{"agent_name": "<agent_name>", "reason": "<brief explanation in 1 sentence>"}}

IMPORTANT: The "agent_name" field MUST be one of these exact agent names: {agent_names_formatted}.
Do NOT return a skill name or skill ID — return the parent agent name that owns the matching skill.

Now analyze and route:"""

        try:
            llm = get_llm()
            
            chat_messages = [
                {"role": "system", "content": "You are a routing assistant. Analyze the conversation context and user intent to select the most appropriate agent. Respond with only valid JSON: {\"agent_name\": \"name\", \"reason\": \"explanation\"}"},
                {"role": "user", "content": routing_prompt}
            ]
            
            response = ""
            for chunk in llm.stream(chat_messages, stream=True):
                chunk_content = ""
                if hasattr(chunk, 'content'):
                    if isinstance(chunk.content, str):
                        chunk_content = chunk.content
                    elif isinstance(chunk.content, list):
                        chunk_content = " ".join(str(item) for item in chunk.content)
                    else:
                        chunk_content = str(chunk.content)
                else:
                    chunk_content = str(chunk)
                
                response += chunk_content
            
            # Parse JSON response
            import json
            response = response.strip()

            logger.info("🤖 LLM raw response: %s", response)

            # Try to extract JSON
            try:
                if '{' in response:
                    json_start = response.index('{')
                    json_end = response.rindex('}') + 1
                    json_str = response[json_start:json_end]
                    result = json.loads(json_str)
                    agent_name = result.get('agent_name', '').lower()
                    reason = result.get('reason', 'No reason provided')
                else:
                    # Fallback to plain text parsing
                    agent_name = response.lower()
                    reason = "Direct response"
                    for prefix in ["agent:", "route to:", "selected:", "answer:"]:
                        if agent_name.startswith(prefix):
                            agent_name = agent_name[len(prefix):].strip()
                    logger.warning("LLM response had no JSON; parsed as plain text: agent_name='%s'", agent_name)
            except json.JSONDecodeError:
                logger.warning("Failed to parse JSON from LLM response: %s", response)
                agent_name = response.lower()
                reason = "Fallback parsing"

            logger.info("🔍 Parsed routing decision: agent_name='%s' reason='%s'", agent_name, reason)
            
            # Phase 1: Try to find matching agent by name/slug or display_name
            logger.info("🔎 Phase 1: Matching '%s' against agent names/display_names", agent_name)
            for agent in agents:
                name_match = (
                    agent.name.lower() == agent_name or agent_name in agent.name.lower()
                )
                display_match = False
                if agent.display_name:
                    display_match = (
                        agent.display_name.lower() == agent_name
                        or agent_name in agent.display_name.lower()
                    )
                logger.debug(
                    "  Comparing: slug='%s' display='%s' → name_match=%s display_match=%s",
                    agent.name, agent.display_name, name_match, display_match,
                )
                if name_match or display_match:
                    logger.info(
                        "✅ Routing resolved (phase 1 — agent name match): agent=%s reason='%s' query='%s'",
                        agent.name,
                        reason,
                        query[:100] + ("..." if len(query) > 100 else ""),
                    )
                    return agent

            # Phase 2: Match on skill ID or skill name (LLM may return a skill
            # identifier instead of an agent name)
            logger.info("🔎 Phase 2: Matching '%s' against skill IDs/names", agent_name)
            for agent in agents:
                if not agent.agent_card or not agent.agent_card.skills:
                    continue
                for skill in agent.agent_card.skills:
                    skill_id_match = skill.id.lower() == agent_name
                    skill_name_match = (
                        skill.name.lower() == agent_name
                        or agent_name in skill.name.lower()
                    )
                    if skill_id_match or skill_name_match:
                        logger.info(
                            "✅ Routing resolved (phase 2 — skill match): skill='%s' (id=%s) → agent=%s reason='%s' query='%s'",
                            skill.name,
                            skill.id,
                            agent.name,
                            reason,
                            query[:100] + ("..." if len(query) > 100 else ""),
                        )
                        return agent

            # Phase 3: Keyword fallback
            logger.warning(
                "⚠️ Phases 1-2 failed for LLM response '%s'; falling back to keyword matching",
                agent_name,
            )
            return self._keyword_fallback(query, agents)
            
        except Exception as e:
            from .properties import CIRCUIT_LLM_API_ENDPOINT, CIRCUIT_LLM_API_MODEL_NAME, CIRCUIT_LLM_API_VERSION
            error_msg = str(e)
            logger.error("LLM routing failed. Service response/error: %s", error_msg)
            logger.error(
                "LLM config: endpoint=%s deployment=%s api_version=%s (using keyword fallback)",
                CIRCUIT_LLM_API_ENDPOINT,
                CIRCUIT_LLM_API_MODEL_NAME,
                CIRCUIT_LLM_API_VERSION,
            )
            if "404" in error_msg:
                logger.info(
                    "LLM 404 usually means deployment name or API version is wrong for this service. "
                    "Check CIRCUIT_LLM_API_MODEL_NAME and CIRCUIT_LLM_API_VERSION against the LLM service docs."
                )
            return self._keyword_fallback(query, agents)
    
    def _keyword_fallback(self, query: str, agents: List[SubAgentConfig]) -> Optional[SubAgentConfig]:
        """Fallback routing using keyword matching."""
        logger.info(
            "🔎 Phase 3: Keyword fallback for query='%s' across %d agents",
            query[:100] + ("..." if len(query) > 100 else ""),
            len(agents),
        )
        query_lower = query.lower()
        query_words = query_lower.split()

        for agent in agents:
            label = agent.display_name_or_name.lower()
            if label in query_lower:
                logger.info(
                    "✅ Routing resolved (phase 3 — keyword name match): agent=%s matched_label='%s'",
                    agent.name, agent.display_name_or_name,
                )
                return agent

            if not agent.agent_card:
                continue

            agent_skills_lower = [s.lower() for s in agent.skills]
            for skill in agent_skills_lower:
                if any(word in skill or skill in word for word in query_words):
                    logger.info(
                        "✅ Routing resolved (phase 3 — keyword skill match): agent=%s matched_skill_id='%s'",
                        agent.name, skill,
                    )
                    return agent

            for skill_desc in agent.skill_descriptions:
                if any(word in skill_desc.lower() for word in query_words):
                    logger.info(
                        "✅ Routing resolved (phase 3 — keyword description match): agent=%s",
                        agent.name,
                    )
                    return agent
        
        if agents:
            logger.warning(
                "❌ No match in any phase; defaulting to first agent: %s",
                agents[0].name,
            )
            return agents[0]
        
        logger.warning("❌ No agents available for query: %s", query[:100])
        return None
