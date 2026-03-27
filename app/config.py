"""Application configuration via Pydantic BaseSettings."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    All settings can be overridden via environment variables prefixed with UA_WS_.
    Example: UA_WS_PORT=9000 overrides the port setting.
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
        default=["circuit.v1", "circuit.v2", "cdca2a"],
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

    # Session configuration (sliding-window TTL)
    session_idle_ttl_seconds: int = Field(
        default=1800,
        ge=60,
        description="Session idle TTL in seconds (e.g. 30 min). Extended on each request."
    )
    session_max_lifetime_seconds: int | None = Field(
        default=28800,
        ge=60,
        description="Max session lifetime in seconds (8h). None to allow unbounded extension."
    )
    session_renewal_idle_threshold_seconds: int = Field(
        default=900,
        ge=60,
        description="Minimum idle duration (seconds) to trigger early expiry in the renewal zone (default 15 min)."
    )

    # Redis configuration (session persistence)
    redis_host: str = Field(
        default="localhost",
        description="Redis host for session persistence",
    )
    redis_port: int = Field(
        default=6379,
        ge=1,
        le=65535,
        description="Redis port",
    )
    redis_db: int = Field(
        default=0,
        ge=0,
        description="Redis database number",
    )
    session_persistence_backend: Literal["memory", "redis"] = Field(
        default="memory",
        description="Session store backend: 'memory' (in-memory) or 'redis' (persist in Redis)",
    )

    # Async flow (webhook / orchestrator)
    async_flow_enabled: bool = Field(
        default=False,
        description="When True, forward A2A requests to orchestrator and respond via webhook",
    )
    agent_base_url: str | None = Field(
        default="http://cdcai-microsvc-uber-assistant-orchestration-agent-svc.ns-qry-aiml-stg-api.svc.cluster.local:8006",
        description="Base URL of the orchestrator/agent",
    )
    webhook_base_url: str = Field(
        default="",
        description="Our base URL for webhook callback (e.g. https://{webhook_base_url}.com)",
    )
    webhook_async_path: str = Field(
        default="ws/async/response",
        description="Path for async response webhook (appended to webhook_base_url)",
    )

    # WebSocket heartbeat
    heartbeat_interval_seconds: int = Field(
        default=20,
        ge=5,
        description="Seconds between server-sent ping messages per connection",
    )
    heartbeat_timeout_seconds: int = Field(
        default=10,
        ge=2,
        description="Seconds to wait for pong before closing the connection",
    )

    # Async response timeout
    async_response_timeout_seconds: int = Field(
        default=1800,
        ge=10,
        description="Max seconds to wait for orchestrator webhook callback before sending timeout error to UI (fixed, not sliding)",
    )

    # Connection idle timeout
    connection_idle_timeout_seconds: int = Field(
        default=1800,
        ge=60,
        description="Close WebSocket connections idle for longer than this (seconds). Default 1800 = 30 min.",
    )

    # Rate limiting (per connection)
    rate_limit_messages_per_minute: int = Field(
        default=10,
        ge=1,
        description="Max messages per minute per WebSocket connection (average rate)",
    )
    rate_limit_burst_size: int = Field(
        default=5,
        ge=1,
        description="Max burst of messages allowed before throttling kicks in",
    )

    # Logging configuration
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    model_config = {
        "env_prefix": "UA_WS_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }
