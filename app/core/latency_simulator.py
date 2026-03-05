"""Latency simulation for realistic mock responses."""

import asyncio
import random
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class LatencyConfig(BaseModel):
    """
    Configuration for latency simulation.
    
    Allows fine-grained control over simulated delays including
    random variation, occasional spikes, and per-message-type overrides.
    """

    enabled: bool = Field(
        default=True,
        description="Enable or disable latency simulation"
    )
    min_ms: int = Field(
        default=50,
        ge=0,
        description="Minimum latency in milliseconds"
    )
    max_ms: int = Field(
        default=300,
        ge=0,
        description="Maximum latency in milliseconds"
    )
    spike_probability: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Probability of a latency spike (0.0 to 1.0)"
    )
    spike_min_ms: int = Field(
        default=500,
        ge=0,
        description="Minimum spike latency in milliseconds"
    )
    spike_max_ms: int = Field(
        default=2000,
        ge=0,
        description="Maximum spike latency in milliseconds"
    )
    type_overrides: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="Per-message-type latency overrides"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "enabled": True,
                    "min_ms": 50,
                    "max_ms": 300,
                    "spike_probability": 0.05,
                    "spike_min_ms": 500,
                    "spike_max_ms": 2000,
                    "type_overrides": {
                        "ping": {"min_ms": 5, "max_ms": 20},
                        "user_query": {"min_ms": 150, "max_ms": 500},
                    },
                }
            ]
        }
    }


class LatencySimulator:
    """
    Simulates realistic network and processing latency.
    
    Features:
    - Random delay within configurable bounds
    - Occasional latency spikes to simulate real-world conditions
    - Per-message-type configuration for different response characteristics
    - Full logging of simulated delays for debugging
    """

    def __init__(self, config: LatencyConfig) -> None:
        """
        Initialize the latency simulator.
        
        Args:
            config: Latency configuration settings.
        """
        self._config = config
        self._logger = logger.bind(component="latency_simulator")

    @property
    def config(self) -> LatencyConfig:
        """Get the current configuration."""
        return self._config

    def update_config(self, config: LatencyConfig) -> None:
        """
        Update the latency configuration.
        
        Args:
            config: New latency configuration.
        """
        self._config = config
        self._logger.info(
            "config_updated",
            enabled=config.enabled,
            min_ms=config.min_ms,
            max_ms=config.max_ms,
        )

    async def simulate(self, message_type: str | None = None) -> int:
        """
        Simulate latency delay.
        
        Args:
            message_type: Optional message type for type-specific latency.
            
        Returns:
            The actual delay applied in milliseconds.
        """
        if not self._config.enabled:
            return 0

        delay_ms = self._calculate_delay(message_type)
        
        if delay_ms > 0:
            self._logger.debug(
                "simulating_latency",
                message_type=message_type,
                delay_ms=delay_ms,
                is_spike=delay_ms >= self._config.spike_min_ms,
            )
            await asyncio.sleep(delay_ms / 1000.0)

        return delay_ms

    async def simulate_range(self, min_ms: int, max_ms: int) -> int:
        """
        Simulate latency delay within a specific range.
        
        Args:
            min_ms: Minimum latency in milliseconds.
            max_ms: Maximum latency in milliseconds.
            
        Returns:
            The actual delay applied in milliseconds.
        """
        if not self._config.enabled:
            return 0

        # Ensure min <= max
        if min_ms > max_ms:
            min_ms, max_ms = max_ms, min_ms

        delay_ms = random.randint(min_ms, max_ms)
        
        if delay_ms > 0:
            self._logger.debug(
                "simulating_latency_range",
                min_ms=min_ms,
                max_ms=max_ms,
                delay_ms=delay_ms,
            )
            await asyncio.sleep(delay_ms / 1000.0)

        return delay_ms

    def _calculate_delay(self, message_type: str | None = None) -> int:
        """
        Calculate the delay to apply.
        
        Args:
            message_type: Optional message type for type-specific delays.
            
        Returns:
            Delay in milliseconds.
        """
        # Get base min/max values
        min_ms = self._config.min_ms
        max_ms = self._config.max_ms

        # Apply type-specific override if available
        if message_type and message_type in self._config.type_overrides:
            override = self._config.type_overrides[message_type]
            min_ms = override.get("min_ms", min_ms)
            max_ms = override.get("max_ms", max_ms)

        # Check for latency spike
        if random.random() < self._config.spike_probability:
            return random.randint(
                self._config.spike_min_ms,
                self._config.spike_max_ms,
            )

        # Ensure min <= max
        if min_ms > max_ms:
            min_ms, max_ms = max_ms, min_ms

        return random.randint(min_ms, max_ms)

    def get_expected_latency(self, message_type: str | None = None) -> dict[str, Any]:
        """
        Get expected latency range for a message type.
        
        Useful for clients to understand expected response times.
        
        Args:
            message_type: Optional message type.
            
        Returns:
            Dictionary with latency expectations.
        """
        if not self._config.enabled:
            return {"enabled": False, "expected_ms": 0}

        min_ms = self._config.min_ms
        max_ms = self._config.max_ms

        if message_type and message_type in self._config.type_overrides:
            override = self._config.type_overrides[message_type]
            min_ms = override.get("min_ms", min_ms)
            max_ms = override.get("max_ms", max_ms)

        return {
            "enabled": True,
            "min_ms": min_ms,
            "max_ms": max_ms,
            "spike_probability": self._config.spike_probability,
            "spike_range_ms": {
                "min": self._config.spike_min_ms,
                "max": self._config.spike_max_ms,
            },
        }
