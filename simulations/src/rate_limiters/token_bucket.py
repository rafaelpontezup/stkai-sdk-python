"""
Token Bucket rate limiter - high fidelity port from stkai._rate_limit.

Simple rate limiting with constant token refill.
"""

from simulations.src.config import RateLimitConfig
from simulations.src.rate_limiters.base import (
    RateLimiter,
    RateLimitResult,
    AcquireResult,
)


class TokenBucketRateLimiter(RateLimiter):
    """
    Token Bucket rate limiter.

    High-fidelity port of stkai._rate_limit.TokenBucketRateLimitedHttpClient.

    Key behaviors:
    - Refills tokens continuously based on elapsed time
    - Blocks (returns wait time) if no tokens available
    - Times out if max_wait_time exceeded
    """

    def __init__(self, config: RateLimitConfig, process_id: int = 0):
        """
        Initialize token bucket.

        Args:
            config: Rate limit configuration.
            process_id: Simulated process ID (for jitter seeding).
        """
        self.max_requests = config.max_requests
        self.time_window = config.time_window
        self.max_wait_time = config.max_wait_time

        # Token bucket state
        self._tokens = float(config.max_requests)
        self._last_refill: float | None = None

    def acquire_token(self, current_time: float) -> AcquireResult:
        """
        Acquire a token from the bucket.

        Implements the same logic as TokenBucketRateLimitedHttpClient._acquire_token().

        Args:
            current_time: Current simulation time.

        Returns:
            AcquireResult with ACQUIRED or TIMEOUT status.
        """
        # Initialize last_refill on first call
        if self._last_refill is None:
            self._last_refill = current_time

        # Refill tokens based on elapsed time since last refill
        elapsed_since_refill = current_time - self._last_refill
        if elapsed_since_refill > 0:
            refill_rate = self.max_requests / self.time_window
            self._tokens = min(
                float(self.max_requests),
                self._tokens + elapsed_since_refill * refill_rate
            )
            self._last_refill = current_time

        # Try to acquire token immediately
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return AcquireResult(
                result=RateLimitResult.ACQUIRED,
                wait_time=0.0,
            )

        # Not enough tokens - calculate wait time
        refill_rate = self.max_requests / self.time_window
        wait_time = (1.0 - self._tokens) / refill_rate

        # Check timeout
        if self.max_wait_time is not None and wait_time > self.max_wait_time:
            return AcquireResult(
                result=RateLimitResult.TIMEOUT,
                wait_time=0.0,
            )

        # Reserve the token: deduct now (may go negative), caller will yield wait_time.
        # Negative tokens represent "debt" that naturally queues concurrent workers.
        self._tokens -= 1.0

        return AcquireResult(
            result=RateLimitResult.ACQUIRED,
            wait_time=wait_time,
        )

    def on_success(self) -> None:
        """No-op for simple token bucket (no adaptation)."""
        pass

    def on_rate_limited(self) -> None:
        """No-op for simple token bucket (no adaptation)."""
        pass

    def get_effective_rate(self) -> float:
        """Token bucket has constant rate."""
        return float(self.max_requests)
