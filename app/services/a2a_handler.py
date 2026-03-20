"""Handles plain text queries and returns A2A (Agent-to-Agent) responses."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.latency_simulator import LatencySimulator
from app.logging.setup import get_logger
from app.models.responses import UIResponse

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

    async def handle(self, plain_text: str) -> UIResponse:
        """
        Handle a plain text query and return a UIResponse.
        
        Args:
            plain_text: The plain text query.
            
        Returns:
            UIResponse wrapping the A2A result.
        """
        start_time = datetime.utcnow()
        
        response_key = self._matcher.match(plain_text)
        response_config = self._loader.get_response_config(response_key)
        
        if not response_config:
            response_config = self._loader.get_response_config("default")
        
        latency_override = response_config.get("latency_override")
        if latency_override:
            min_ms = latency_override.get("min_ms", 50)
            max_ms = latency_override.get("max_ms", 150)
            await self._latency_simulator.simulate_range(min_ms, max_ms)
        
        text_content = self._extract_text_content(response_config)
        
        ui_response = self._build_a2a_response(
            text_content,
            query_text=plain_text,
        )
        
        processing_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        self._logger.info(
            "a2a_response_generated",
            input=plain_text,
            response_key=response_key,
            processing_time_ms=round(processing_time_ms, 2),
        )
        
        return ui_response

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
    ) -> UIResponse:
        """
        Handle an A2A JSON request (agent/sendMessage): match query, build response with ids.

        Returns:
            UIResponse wrapping the A2A result with metadata.
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
        ui_response = self._build_a2a_response(
            text_content,
            session_id=session_id,
            request_id=request_id,
            conversation_id=conversation_id,
            cp_gutc_id=cp_gutc_id,
            referrer=referrer,
            query_text=query,
        )
        processing_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self._logger.info(
            "a2a_response_generated",
            input=query,
            response_key=response_key,
            processing_time_ms=round(processing_time_ms, 2),
        )
        return ui_response

    def build_welcome_response(
        self,
        session_id: str | None = None,
        request_id: str | int | None = None,
        context_id: str | None = None,
        cp_gutc_id: str | None = None,
        referrer: str | None = None,
    ) -> UIResponse:
        """Build welcome UIResponse (first-chat). UI replaces {user_name}."""
        now = datetime.utcnow()
        timestamp_str = now.isoformat() + "Z"
        response_id = str(request_id) if request_id is not None else None

        a2a_inner: dict[str, Any] = {
            "id": response_id,
            "jsonrpc": "2.0",
            "result": {
                "contextId": context_id or "",
                "artifacts": [
                    {
                        "artifactId": "",
                        "name": "welcome_message",
                        "parts": [{"kind": "text", "text": WELCOME_MESSAGE_FIRST_CHAT}],
                    }
                ],
                "role": "assistant",
                "metadata": {
                    "timestamp": timestamp_str,
                    "sessionId": session_id,
                    "conversationId": context_id or "",
                    "CP_GUTC_Id": cp_gutc_id,
                    "referrer": referrer,
                },
            },
        }

        return UIResponse(
            context_id=context_id or "",
            response=WELCOME_MESSAGE_FIRST_CHAT,
            conversation_id=context_id or "",
            a2a_response=a2a_inner,
        )

    @staticmethod
    def extract_text_from_sse_event(event: dict) -> tuple[str, str, bool]:
        """
        Extract (text, state, is_final) from a raw orchestrator SSE event.

        Returns:
            text: extracted display text (empty string if none)
            state: task state ("working", "completed", etc.)
            is_final: whether this is the final event in the stream
        """
        result = event.get("result", {})
        kind = result.get("kind", "")
        text = ""
        state = "working"
        is_final = bool(result.get("final", False))

        if kind == "status-update":
            status = result.get("status", {})
            state = status.get("state", "working")
            message = status.get("message")
            if isinstance(message, dict):
                for part in message.get("parts", []):
                    if isinstance(part, dict) and part.get("kind") == "text":
                        text += part.get("text", "")

        elif kind == "artifact-update":
            artifact = result.get("artifact", {})
            for part in artifact.get("parts", []):
                if isinstance(part, dict) and part.get("kind") == "text":
                    text += part.get("text", "")

        elif kind == "task":
            status = result.get("status", {})
            state = status.get("state", "working")
            message = status.get("message")
            if isinstance(message, dict):
                for part in message.get("parts", []):
                    if isinstance(part, dict) and part.get("kind") == "text":
                        text += part.get("text", "")
            for artifact in result.get("artifacts", []):
                if isinstance(artifact, dict):
                    for part in artifact.get("parts", []):
                        if isinstance(part, dict) and part.get("kind") == "text":
                            text += part.get("text", "")

        return text, state, is_final

    @staticmethod
    def extract_text_from_content(content: Any) -> str:
        """
        Extract display text from orchestrator content which may be:
          - A plain string
          - A dict with {"status": ..., "artifacts": [{"text": "..."}]}
          - Any other type (serialised to str as fallback)
        """
        if content is None:
            return "(No content)"
        if isinstance(content, str):
            return content or "(No content)"
        if isinstance(content, dict):
            artifacts = content.get("artifacts")
            if isinstance(artifacts, list):
                texts = [
                    a.get("text", "") for a in artifacts
                    if isinstance(a, dict) and a.get("text")
                ]
                if texts:
                    return "\n\n".join(texts)
            text_field = content.get("text")
            if isinstance(text_field, str) and text_field:
                return text_field
        import json as _json
        try:
            return _json.dumps(content)
        except (TypeError, ValueError):
            return str(content)

    def build_a2a_response_from_content(
        self,
        content: Any,
        session_id: str | None = None,
        request_id: str | int | None = None,
        context_id: str | None = None,
        conversation_id: str | None = None,
        cp_gutc_id: str | None = None,
        referrer: str | None = None,
        query_text: str | None = None,
    ) -> UIResponse:
        """
        Build a UIResponse from orchestrator content (string or object).
        """
        text_content = self.extract_text_from_content(content)
        return self._build_a2a_response(
            text_content=text_content,
            session_id=session_id,
            request_id=request_id,
            context_id=context_id,
            conversation_id=conversation_id,
            cp_gutc_id=cp_gutc_id,
            referrer=referrer,
            query_text=query_text,
        )

    def _build_a2a_response(
        self,
        text_content: str,
        session_id: str | None = None,
        request_id: str | int | None = None,
        context_id: str | None = None,
        conversation_id: str | None = None,
        cp_gutc_id: str | None = None,
        referrer: str | None = None,
        query_text: str | None = None,
    ) -> UIResponse:
        """
        Build a UIResponse wrapping the A2A result (success / normal-query shape).

        ``contextId`` is the A2A backend context (generated when not supplied).
        ``conversationId`` is the UI thread id (echoed back).
        ``history`` contains user + agent messages per the spec.
        ``metadata`` lives at the ``a2aResponse`` level.
        """
        now = datetime.utcnow()
        timestamp_str = now.isoformat() + "Z"
        response_id = str(request_id) if request_id is not None else None
        resolved_context_id = context_id or str(uuid.uuid4())
        task_id = str(uuid.uuid4())

        history: list[dict[str, Any]] = []
        if query_text:
            history.append({
                "contextId": resolved_context_id,
                "kind": "message",
                "messageId": str(uuid.uuid4()).replace("-", ""),
                "parts": [{"kind": "text", "text": query_text}],
                "role": "user",
                "taskId": task_id,
            })
            history.append({
                "contextId": resolved_context_id,
                "kind": "message",
                "messageId": str(uuid.uuid4()),
                "parts": [{"kind": "text", "text": "Processing your request..."}],
                "role": "agent",
                "taskId": task_id,
            })

        a2a_inner: dict[str, Any] = {
            "id": response_id,
            "jsonrpc": "2.0",
            "result": {
                "artifacts": [
                    {
                        "artifactId": str(uuid.uuid4()),
                        "name": "agent_response",
                        "parts": [{"kind": "text", "text": text_content}],
                    }
                ],
                "contextId": resolved_context_id,
                "history": history,
                "id": task_id,
                "kind": "task",
                "status": {"state": "completed", "timestamp": timestamp_str},
            },
            "metadata": {
                "timestamp": timestamp_str,
                "sessionId": session_id,
                "conversationId": conversation_id or "",
                "CP_GUTC_Id": cp_gutc_id,
                "referrer": referrer,
            },
        }

        return UIResponse(
            context_id=resolved_context_id,
            response=text_content,
            conversation_id=conversation_id or "",
            a2a_response=a2a_inner,
            error={},
            status="success",
        )
