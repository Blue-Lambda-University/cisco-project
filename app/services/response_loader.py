"""Loads and caches canned responses from JSON configuration."""

import json
from pathlib import Path
from typing import Any

from app.logging.setup import get_logger

logger = get_logger()


class ResponseLoader:
    """
    Loads and manages canned responses from JSON configuration.
    
    Features:
    - Lazy loading of responses
    - Caching for performance
    - Support for response reloading
    - Validation of response structure
    """

    def __init__(self, responses_path: str) -> None:
        """
        Initialize the response loader.
        
        Args:
            responses_path: Path to the canned responses JSON file.
        """
        self._responses_path = Path(responses_path)
        self._responses: dict[str, Any] | None = None
        self._logger = logger.bind(component="response_loader")

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
            "loading_responses",
            path=str(self._responses_path),
        )

        if not self._responses_path.exists():
            self._logger.error(
                "responses_file_not_found",
                path=str(self._responses_path),
            )
            raise FileNotFoundError(
                f"Canned responses file not found: {self._responses_path}"
            )

        with open(self._responses_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Validate structure
        if not isinstance(data, dict):
            raise ValueError("Responses file must contain a JSON object")

        if "responses" not in data:
            raise ValueError("Responses file must contain a 'responses' key")

        self._responses = data
        
        response_types = list(data.get("responses", {}).keys())
        self._logger.info(
            "responses_loaded",
            version=data.get("version", "unknown"),
            response_types=response_types,
            count=len(response_types),
        )

    def reload(self) -> None:
        """Reload responses from the file."""
        self._responses = None
        self.load()

    def get_response_config(self, message_type: str) -> dict[str, Any] | None:
        """
        Get the response configuration for a message type.
        
        Args:
            message_type: The message type to get response for.
            
        Returns:
            Response configuration dict or None if not found.
        """
        if not self.is_loaded:
            self.load()

        responses = self._responses.get("responses", {})
        
        # Try exact match first
        if message_type in responses:
            return responses[message_type]
        
        # Fall back to default
        if "default" in responses:
            self._logger.debug(
                "using_default_response",
                message_type=message_type,
            )
            return responses["default"]
        
        return None

    def get_all_response_types(self) -> list[str]:
        """
        Get all supported response types.
        
        Returns:
            List of message types with configured responses.
        """
        if not self.is_loaded:
            self.load()

        return list(self._responses.get("responses", {}).keys())

    def get_version(self) -> str:
        """
        Get the responses configuration version.
        
        Returns:
            Version string.
        """
        if not self.is_loaded:
            self.load()

        return self._responses.get("version", "unknown")

    def get_latency_override(self, message_type: str) -> dict[str, int] | None:
        """
        Get latency override for a message type.
        
        Args:
            message_type: The message type.
            
        Returns:
            Latency override dict or None.
        """
        config = self.get_response_config(message_type)
        if config:
            return config.get("latency_override")
        return None
