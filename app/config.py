"""Application configuration via Pydantic BaseSettings."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    All settings can be overridden via environment variables prefixed with MOCK_WS_.
    Example: MOCK_WS_PORT=9000 overrides the port setting.
    """

    # Server configuration
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8000, description="Server bind port")
    environment: Literal["development", "production"] = Field(
        default="development",
        description="Runtime environment"
    )

    # WebSocket configuration
    max_connections: int = Field(
        default=1000,
        ge=1,
        description="Maximum concurrent WebSocket connections"
    )
    supported_subprotocols: list[str] = Field(
        default=["circuit.v1", "circuit.v2"],
        description="Supported WebSocket subprotocols"
    )

    # Latency simulation configuration
    latency_enabled: bool = Field(
        default=True,
        description="Enable latency simulation for mock responses"
    )
    latency_min_ms: int = Field(
        default=50,
        ge=0,
        description="Minimum simulated latency in milliseconds"
    )
    latency_max_ms: int = Field(
        default=300,
        ge=0,
        description="Maximum simulated latency in milliseconds"
    )
    latency_spike_probability: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Probability of latency spike (0.0 to 1.0)"
    )
    latency_spike_min_ms: int = Field(
        default=500,
        ge=0,
        description="Minimum spike latency in milliseconds"
    )
    latency_spike_max_ms: int = Field(
        default=2000,
        ge=0,
        description="Maximum spike latency in milliseconds"
    )

    # Response configuration
    canned_responses_path: str = Field(
        default="app/responses/canned_responses.json",
        description="Path to canned responses JSON file"
    )
    a2a_responses_path: str = Field(
        default="app/responses/a2a_responses.json",
        description="Path to A2A canned responses JSON file for plain text queries"
    )

    # Logging configuration
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    model_config = {
        "env_prefix": "MOCK_WS_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }
