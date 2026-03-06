"""Handles plain text queries and returns A2A (Agent-to-Agent) responses."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.latency_simulator import LatencySimulator
from app.logging.setup import get_logger
from app.models.responses import (
    A2AArtifact,
    A2AArtifactPart,
    A2AResponse,
    A2AResultMetadata,
    A2ATaskResult,
    A2ATaskStatus,
)

logger = get_logger()

# First-chat welcome message (UI replaces {user_name}); lines match screenshot action buttons.
WELCOME_MESSAGE_FIRST_CHAT = """Welcome {user_name}! I am Cisco Uber Assistant. How can I help you today?
Book a demo or trial
Chat with Sales
Get Support
Licensing
Get Cisco Certified
Velocity Hub"""


class A2AResponseLoader:
    """
    Loads and manages A2A canned responses from JSON configuration.
    
    Features:
    - Lazy loading of responses
    - Caching for performance
    - Contains-based pattern matching
    """

    def __init__(self, responses_path: str) -> None:
        """
        Initialize the A2A response loader.
        
        Args:
            responses_path: Path to the A2A responses JSON file.
        """
        self._responses_path = Path(responses_path)
        self._responses: dict[str, Any] | None = None
        self._logger = logger.bind(component="a2a_response_loader")

    @property
    def is_loaded(self) -> bool:
        """Check if responses have been loaded."""
        return self._responses is not None

    def load(self) -> None:
        """
        Load responses from the JSON file.
        
        Raises:
            FileNotFoundError: If the responses file doesn't exist.
            json.JSONDecodeError: If the file contains invalid JSON.
            ValueError: If the response structure is invalid.
        """
        self._logger.info(
            "loading_a2a_responses",
            path=str(self._responses_path),
        )

        if not self._responses_path.exists():
            self._logger.error(
                "a2a_responses_file_not_found",
                path=str(self._responses_path),
            )
            raise FileNotFoundError(
                f"A2A responses file not found: {self._responses_path}"
            )

        with open(self._responses_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Validate structure
        if not isinstance(data, dict):
            raise ValueError("A2A responses file must contain a JSON object")

        if "responses" not in data:
            raise ValueError("A2A responses file must contain a 'responses' key")

        self._responses = data
        
        response_types = list(data.get("responses", {}).keys())
        self._logger.info(
            "a2a_responses_loaded",
            version=data.get("version", "unknown"),
            response_types=response_types,
            count=len(response_types),
        )

    def get_responses_data(self) -> dict[str, Any]:
        """Get the full responses data."""
        if not self.is_loaded:
            self.load()
        return self._responses

    def get_matching_rules(self) -> dict[str, Any]:
        """Get the matching rules configuration."""
        if not self.is_loaded:
            self.load()
        return self._responses.get("matching_rules", {})

    def get_response_config(self, response_key: str) -> dict[str, Any] | None:
        """Get a specific response configuration."""
        if not self.is_loaded:
            self.load()
        return self._responses.get("responses", {}).get(response_key)

    def get_priority_order(self) -> list[str]:
        """Get the priority order for matching."""
        rules = self.get_matching_rules()
        return rules.get("priority_order", [])


class PlainTextMatcher:
    """
    Matches plain text input against configured patterns.
    
    Uses contains-based matching with priority order.
    """

    def __init__(self, loader: A2AResponseLoader) -> None:
        """
        Initialize the plain text matcher.
        
        Args:
            loader: A2A response loader instance.
        """
        self._loader = loader
        self._logger = logger.bind(component="plain_text_matcher")

    def match(self, input_text: str) -> str:
        """
        Match input text against configured patterns.
        
        Args:
            input_text: The plain text input to match.
            
        Returns:
            The key of the matched response (e.g., 'welcome', 'licencing_configuration').
            Returns 'default' if no match is found.
        """
        # Normalize input (lowercase, strip whitespace)
        normalized_input = input_text.lower().strip()
        
        self._logger.debug(
            "matching_input",
            original=input_text,
            normalized=normalized_input,
        )

        # Get priority order
        priority_order = self._loader.get_priority_order()
        
        # Check each response type in priority order
        for response_key in priority_order:
            response_config = self._loader.get_response_config(response_key)
            if not response_config:
                continue
            
            match_patterns = response_config.get("match_patterns", [])
            
            for pattern in match_patterns:
                if pattern.lower() in normalized_input:
                    self._logger.info(
                        "pattern_matched",
                        input=input_text,
                        pattern=pattern,
                        response_key=response_key,
                    )
                    return response_key
        
        # No match found - return default
        self._logger.info(
            "no_pattern_matched",
            input=input_text,
            using_default=True,
        )
        return "default"


class A2AHandler:
    """
    Handles plain text queries and returns A2A (Agent-to-Agent) responses.
    
    Responsibilities:
    - Accept plain text input
    - Match against configured patterns
    - Return A2A JSON-RPC 2.0 formatted responses using Pydantic models
    """

    def __init__(
        self,
        loader: A2AResponseLoader,
        latency_simulator: LatencySimulator,
    ) -> None:
        """
        Initialize the A2A handler.
        
        Args:
            loader: A2A response loader instance.
            latency_simulator: Latency simulator for delays.
        """
        self._loader = loader
        self._matcher = PlainTextMatcher(loader)
        self._latency_simulator = latency_simulator
        self._logger = logger.bind(component="a2a_handler")

    async def handle(self, plain_text: str) -> A2AResponse:
        """
        Handle a plain text query and return an A2A response.
        
        Args:
            plain_text: The plain text query.
            
        Returns:
            A2AResponse Pydantic model with JSON-RPC 2.0 structure.
        """
        start_time = datetime.utcnow()
        
        # Match input to response key
        response_key = self._matcher.match(plain_text)
        
        # Get response configuration
        response_config = self._loader.get_response_config(response_key)
        
        if not response_config:
            # Fallback to default
            response_config = self._loader.get_response_config("default")
        
        # Simulate latency
        latency_override = response_config.get("latency_override")
        if latency_override:
            min_ms = latency_override.get("min_ms", 50)
            max_ms = latency_override.get("max_ms", 150)
            await self._latency_simulator.simulate_range(min_ms, max_ms)
        
        # Extract the text content from the response template
        text_content = self._extract_text_content(response_config)
        
        # Build the A2A response using Pydantic models (plain text path: no request/session/context ids)
        a2a_response = self._build_a2a_response(
            text_content,
            session_id=None,
            request_id=None,
            context_id=None,
        )
        
        processing_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        self._logger.info(
            "a2a_response_generated",
            input=plain_text,
            response_key=response_key,
            processing_time_ms=round(processing_time_ms, 2),
        )
        
        return a2a_response

    def _extract_text_content(self, response_config: dict[str, Any]) -> str:
        """
        Extract the text content from a response configuration.
        
        Args:
            response_config: The response configuration dict.
            
        Returns:
            The text content string.
        """
        try:
            response = response_config.get("response", {})
            result = response.get("result", {})
            artifacts = result.get("artifacts", [])
            if artifacts:
                parts = artifacts[0].get("parts", [])
                if parts:
                    return parts[0].get("text", "No response available.")
        except (KeyError, IndexError, TypeError):
            pass
        
        return "No response available."

    async def handle_a2a_request(
        self,
        query: str,
        session_id: str | None,
        request_id: str | None,
        conversation_id: str | None,
        cp_gutc_id: str | None = None,
        referrer: str | None = None,
    ) -> A2AResponse:
        """
        Handle an A2A JSON request (agent/sendMessage): match query, build response with ids.

        Args:
            query: User query text from params.message.parts.
            session_id: Current session id (set in result.sessionId).
            request_id: Request id from client (echoed in response id).
            conversation_id: Conversation/context id (echoed in result.contextId).
            cp_gutc_id: CP GUTC Id from UI (echoed in result.metadata).
            referrer: Referrer from UI (echoed in result.metadata).

        Returns:
            A2AResponse with result.sessionId, result.contextId, result.metadata, id set.
        """
        start_time = datetime.utcnow()
        response_key = self._matcher.match(query)
        response_config = self._loader.get_response_config(response_key)
        if not response_config:
            response_config = self._loader.get_response_config("default")
        latency_override = response_config.get("latency_override")
        if latency_override:
            min_ms = latency_override.get("min_ms", 50)
            max_ms = latency_override.get("max_ms", 150)
            await self._latency_simulator.simulate_range(min_ms, max_ms)
        text_content = self._extract_text_content(response_config)
        context_id = conversation_id
        a2a_response = self._build_a2a_response(
            text_content,
            session_id=session_id,
            request_id=request_id,
            context_id=context_id,
            cp_gutc_id=cp_gutc_id,
            referrer=referrer,
        )
        processing_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self._logger.info(
            "a2a_response_generated",
            input=query,
            response_key=response_key,
            processing_time_ms=round(processing_time_ms, 2),
        )
        return a2a_response

    def build_welcome_response(
        self,
        session_id: str | None = None,
        request_id: str | int | None = None,
        context_id: str | None = None,
        cp_gutc_id: str | None = None,
        referrer: str | None = None,
    ) -> A2AResponse:
        """Build A2A response with first-chat welcome message (contains {user_name} for UI to replace)."""
        return self.build_a2a_response_from_content(
            text_content=WELCOME_MESSAGE_FIRST_CHAT,
            session_id=session_id,
            request_id=request_id,
            context_id=context_id,
            cp_gutc_id=cp_gutc_id,
            referrer=referrer,
        )

    def build_a2a_response_from_content(
        self,
        text_content: str,
        session_id: str | None = None,
        request_id: str | int | None = None,
        context_id: str | None = None,
        cp_gutc_id: str | None = None,
        referrer: str | None = None,
    ) -> A2AResponse:
        """
        Build an A2A response from raw content (e.g. from webhook/orchestrator callback).
        Use this when the webhook receives the orchestrator response: pass content and
        metadata (including CP_GUTC_Id, referrer from WebhookIncomingBody) so the
        response to the frontend has the correct result.metadata.
        """
        return self._build_a2a_response(
            text_content=text_content,
            session_id=session_id,
            request_id=request_id,
            context_id=context_id,
            cp_gutc_id=cp_gutc_id,
            referrer=referrer,
        )

    def _build_a2a_response(
        self,
        text_content: str,
        session_id: str | None = None,
        request_id: str | int | None = None,
        context_id: str | None = None,
        cp_gutc_id: str | None = None,
        referrer: str | None = None,
    ) -> A2AResponse:
        """
        Build an A2A response using Pydantic models.

        Args:
            text_content: The text content to include in the response.
            session_id: Session id to return in result.sessionId.
            request_id: Request id to echo in response id.
            context_id: Context/conversation id for result.contextId.
            cp_gutc_id: CP GUTC Id from UI (echoed in result.metadata).
            referrer: Referrer from UI (echoed in result.metadata).

        Returns:
            A2AResponse Pydantic model.
        """
        now = datetime.utcnow()
        timestamp_str = now.isoformat() + "Z"
        resolved_context_id = context_id
        response_id = str(request_id) if request_id is not None else None

        artifact_part = A2AArtifactPart(kind="text", text=text_content)
        artifact = A2AArtifact(
            artifactId=f"art_{uuid.uuid4()}",
            name="Response from orchestration",
            parts=[artifact_part],
        )
        task_status = A2ATaskStatus(
            state="completed",
            message=None,
            timestamp=timestamp_str,
        )
        result_metadata = A2AResultMetadata(
            timestamp=timestamp_str,
            sessionId=session_id,
            conversationId=resolved_context_id,
            cp_gutc_id=cp_gutc_id,
            referrer=referrer,
        )
        task_result = A2ATaskResult(
            kind="task",
            id=f"task_{uuid.uuid4()}",
            contextId=resolved_context_id,
            status=task_status,
            artifacts=[artifact],
            role="assistant",
            metadata=result_metadata,
        )
        a2a_response = A2AResponse(
            jsonrpc="2.0",
            id=response_id,
            result=task_result,
        )
        return a2a_response
