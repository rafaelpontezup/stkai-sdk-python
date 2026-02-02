"""
Base rate limiter interface for simulations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto


class RateLimitResult(Enum):
    """Result of a rate limit acquire operation."""

    ACQUIRED = auto()  # Token acquired, can proceed
    TIMEOUT = auto()  # Timed out waiting for token
    WOULD_BLOCK = auto()  # Would block but non-blocking mode


@dataclass
class AcquireResult:
    """Result of acquire_token operation."""

    result: RateLimitResult
    wait_time: float = 0.0  # Time spent waiting for token


class RateLimiter(ABC):
    """
    Abstract base class for rate limiters in simulation.

    Unlike the real SDK which blocks threads, simulation rate limiters
    return how long to wait, letting SimPy handle the delay.
    """

    @abstractmethod
    def acquire_token(self, current_time: float) -> AcquireResult:
        """
        Attempt to acquire a rate limit token.

        Args:
            current_time: Current simulation time in seconds.

        Returns:
            AcquireResult with status and wait time.
        """
        pass

    @abstractmethod
    def on_success(self) -> None:
        """Called after a successful request (for AIMD recovery)."""
        pass

    @abstractmethod
    def on_rate_limited(self) -> None:
        """Called when server returns 429 (for AIMD penalty)."""
        pass

    def release_concurrency(self) -> None:
        """Called after a request completes to release a concurrency slot.

        Only meaningful for CongestionControlledRateLimiter. No-op by default.
        """
        pass

    def record_latency(self, latency: float) -> None:
        """Called after a request completes to record response latency.

        Only meaningful for CongestionControlledRateLimiter. No-op by default.
        """
        pass

    @abstractmethod
    def get_effective_rate(self) -> float:
        """Get current effective rate (for metrics)."""
        pass
