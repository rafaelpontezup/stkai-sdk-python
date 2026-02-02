"""
Adaptive AIMD rate limiter - high fidelity port from stkai._rate_limit.

Implements Additive Increase, Multiplicative Decrease with jitter.
"""

from simulations.src.config import RateLimitConfig
from simulations.src.jitter import Jitter, sleep_with_jitter
from simulations.src.rate_limiters.base import (
    RateLimiter,
    RateLimitResult,
    AcquireResult,
)


class AdaptiveRateLimiter(RateLimiter):
    """
    Adaptive AIMD rate limiter.

    High-fidelity port of stkai._rate_limit.AdaptiveRateLimitedHttpClient.

    Key behaviors:
    - Uses Token Bucket with adaptive effective_max
    - On 429: multiplicative decrease (penalty * jitter)
    - On success: additive increase (recovery * jitter)
    - Jitter (±20%) desynchronizes processes sharing quota
    """

    def __init__(self, config: RateLimitConfig, process_id: int = 0):
        """
        Initialize adaptive rate limiter.

        Args:
            config: Rate limit configuration.
            process_id: Simulated process ID (for jitter seeding).
        """
        self.max_requests = config.max_requests
        self.time_window = config.time_window
        self.max_wait_time = config.max_wait_time
        self.min_rate_floor = config.min_rate_floor
        self.penalty_factor = config.penalty_factor
        self.recovery_factor = config.recovery_factor

        # Token bucket state (adaptive)
        self._effective_max = float(config.max_requests)
        self._min_effective = config.max_requests * config.min_rate_floor
        self._tokens = float(config.max_requests)
        self._last_refill: float | None = None

        # Structural jitter for desynchronizing processes
        self._jitter = Jitter(factor=config.jitter_factor, process_id=process_id)

    def acquire_token(self, current_time: float) -> AcquireResult:
        """
        Acquire a token using adaptive effective_max.

        Uses a reservation approach: refills tokens based on actual sim time,
        then either acquires immediately or reserves a token (going negative)
        and returns the wait time for the caller to yield.

        This avoids setting _last_refill to a future time, which would corrupt
        state for other concurrent workers sharing this rate limiter.

        Args:
            current_time: Current simulation time.

        Returns:
            AcquireResult with ACQUIRED or TIMEOUT status.
        """
        # Initialize last_refill on first call
        if self._last_refill is None:
            self._last_refill = current_time

        # Refill tokens based on actual elapsed time
        elapsed = current_time - self._last_refill
        refill_rate = self._effective_max / self.time_window
        if elapsed > 0:
            self._tokens = min(
                self._effective_max,
                self._tokens + elapsed * refill_rate,
            )
        self._last_refill = current_time

        # Try to acquire immediately
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return AcquireResult(
                result=RateLimitResult.ACQUIRED,
                wait_time=0.0,
            )

        # Calculate wait time for next token
        wait_time = (1.0 - self._tokens) / refill_rate

        # Apply jitter to wait time (mirrors SDK behavior)
        wait_time = sleep_with_jitter(wait_time, jitter_factor=self._jitter.factor)

        # Check timeout — don't modify state on timeout
        if self.max_wait_time is not None and wait_time > self.max_wait_time:
            return AcquireResult(
                result=RateLimitResult.TIMEOUT,
                wait_time=0.0,
            )

        # Reserve the token: deduct now (may go negative), caller will yield wait_time.
        # Negative tokens represent "debt" that naturally queues concurrent workers:
        # each subsequent worker sees the debt and computes a proportionally longer wait.
        self._tokens -= 1.0
        return AcquireResult(
            result=RateLimitResult.ACQUIRED,
            wait_time=wait_time,
        )

    def on_success(self) -> None:
        """
        Additive increase after successful request.

        Mirrors AdaptiveRateLimitedHttpClient._on_success().
        Uses jittered recovery factor to desynchronize processes.
        """
        recovery = self.max_requests * self.recovery_factor * self._jitter
        self._effective_max = min(
            float(self.max_requests),
            self._effective_max + recovery
        )

    def on_rate_limited(self) -> None:
        """
        Multiplicative decrease after receiving 429.

        Mirrors AdaptiveRateLimitedHttpClient._on_rate_limited().
        Uses jittered penalty factor to desynchronize processes.
        Also clamps tokens to maintain bucket invariant.
        """
        jittered_penalty = self.penalty_factor * self._jitter

        self._effective_max = max(
            self._min_effective,
            self._effective_max * (1.0 - jittered_penalty)
        )
        # Clamp tokens to maintain invariant: tokens <= effective_max
        self._tokens = min(self._tokens, self._effective_max)

    def get_effective_rate(self) -> float:
        """Get current adaptive effective rate."""
        return self._effective_max
