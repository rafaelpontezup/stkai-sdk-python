"""
Simulated server with rate limiting.

Implements a server that enforces quota limits and returns 429 responses.
"""

import random
from dataclasses import dataclass, field
from typing import Literal

from simulations.src.config import ServerConfig


@dataclass
class ServerResponse:
    """Response from the simulated server."""

    status_code: int
    latency: float  # Response latency in seconds
    retry_after: float | None = None  # Retry-After header value


class SimulatedServer:
    """
    Simulated StackSpot AI server.

    Enforces quota limits and returns 429 responses when exceeded.
    Uses a simple token bucket for server-side rate limiting.
    """

    def __init__(self, config: ServerConfig):
        """
        Initialize the simulated server.

        Args:
            config: Server configuration.
        """
        self.quota_per_minute = config.quota_per_minute
        self.request_latency = config.request_latency_ms / 1000.0
        self.agent_latency = config.agent_latency_ms / 1000.0
        self.quota_reset_interval = config.quota_reset_interval
        self.retry_after_seconds = config.retry_after_seconds
        self.latency_jitter_factor = config.latency_jitter_factor

        # Server-side quota tracking
        self._quota_remaining = config.quota_per_minute
        self._last_reset: float | None = None

    def handle_request(
        self,
        current_time: float,
        client_type: Literal["rqc", "agent"] = "rqc",
    ) -> ServerResponse:
        """
        Handle an incoming request.

        Args:
            current_time: Current simulation time.
            client_type: Type of client (affects latency).

        Returns:
            ServerResponse with status code and latency.
        """
        # Reset quota if interval has passed
        self._maybe_reset_quota(current_time)

        # Check if quota exceeded
        if self._quota_remaining <= 0:
            return ServerResponse(
                status_code=429,
                latency=0.01,  # 429 responses are fast
                retry_after=self.retry_after_seconds,
            )

        # Consume quota and return success
        self._quota_remaining -= 1
        base_latency = self.agent_latency if client_type == "agent" else self.request_latency
        latency = self._compute_latency(base_latency)

        return ServerResponse(
            status_code=200,
            latency=latency,
            retry_after=None,
        )

    def _compute_latency(self, base_latency: float) -> float:
        """
        Compute request latency based on current server utilization.

        Models real server behavior: latency increases as the server
        approaches capacity, following M/M/1 queuing theory (capped).
        Applies jitter to simulate real-world variability.

        Examples (with base_latency=200ms, no jitter):
            - 0% utilization:  200ms  (idle server)
            - 50% utilization: 400ms  (moderate load)
            - 80% utilization: 1000ms (high load)
            - 95% utilization: 4000ms (near capacity)

        Args:
            base_latency: Base latency in seconds (at zero load).

        Returns:
            Adjusted latency in seconds (with jitter if configured).
        """
        utilization = 1.0 - (self._quota_remaining / self.quota_per_minute)
        # Cap at 0.95 to avoid division by zero / infinity
        capped = min(max(utilization, 0.0), 0.95)
        latency = base_latency / (1.0 - capped)

        # Apply jitter if configured (e.g., 0.2 = ±20%)
        if self.latency_jitter_factor > 0:
            jitter = random.uniform(
                1.0 - self.latency_jitter_factor,
                1.0 + self.latency_jitter_factor,
            )
            latency *= jitter

        return latency

    def _maybe_reset_quota(self, current_time: float) -> None:
        """Reset quota if reset interval has passed."""
        if self._last_reset is None:
            self._last_reset = current_time
            return

        elapsed = current_time - self._last_reset
        if elapsed >= self.quota_reset_interval:
            # Calculate how many reset intervals have passed
            intervals = int(elapsed / self.quota_reset_interval)
            self._quota_remaining = self.quota_per_minute
            self._last_reset += intervals * self.quota_reset_interval

    def get_quota_remaining(self) -> int:
        """Get current remaining quota (for debugging)."""
        return self._quota_remaining

    def reset(self) -> None:
        """Reset server state."""
        self._quota_remaining = self.quota_per_minute
        self._last_reset = None
