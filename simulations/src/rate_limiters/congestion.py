"""
Congestion Controlled rate limiter - high fidelity port from stkai._rate_limit.

Combines AIMD with concurrency control and latency tracking.
"""

import math

from simulations.src.config import RateLimitConfig
from simulations.src.jitter import Jitter
from simulations.src.rate_limiters.base import (
    RateLimiter,
    RateLimitResult,
    AcquireResult,
)


class CongestionControlledRateLimiter(RateLimiter):
    """
    Congestion Controlled rate limiter.

    High-fidelity port of stkai._rate_limit.CongestionControlledHttpClient.

    Key behaviors:
    - Token Bucket + Semaphore (concurrency) + Latency EMA
    - AIMD on 429 responses
    - Concurrency adapts based on latency
    - 30% probability for concurrency growth (slow increase)
    """

    # Probability of increasing concurrency on each successful request
    _CONCURRENCY_GROWTH_PROBABILITY = 0.30

    def __init__(self, config: RateLimitConfig, process_id: int = 0):
        """
        Initialize congestion controlled rate limiter.

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
        self.max_concurrency = config.max_concurrency
        self.initial_concurrency = (
            config.initial_concurrency
            if config.initial_concurrency is not None
            else config.max_concurrency
        )

        # Token bucket state
        self._effective_max = float(config.max_requests)
        self._min_effective = config.max_requests * config.min_rate_floor
        self._tokens = float(config.max_requests)
        self._last_refill: float | None = None

        # Concurrency control - start at initial_concurrency
        self._concurrency_limit = self.initial_concurrency
        self._in_flight = 0

        # Latency tracking (EMA)
        self._latency_ema: float | None = None
        self._latency_alpha = 0.2

        # Structural jitter
        self._jitter = Jitter(factor=config.jitter_factor, process_id=process_id)

    def acquire_token(self, current_time: float) -> AcquireResult:
        """
        Acquire token and concurrency slot.

        Uses a reservation approach for token acquisition to avoid setting
        _last_refill to a future time, which would corrupt state for other
        concurrent workers sharing this rate limiter.

        Note: In simulation, we simplify concurrency tracking since
        SimPy handles actual request execution.
        """
        concurrency_wait = 0.0

        # Check concurrency limit (simplified - just check if at limit)
        if self._in_flight >= self._concurrency_limit:
            concurrency_wait = 0.1
            if self.max_wait_time is not None and concurrency_wait > self.max_wait_time:
                return AcquireResult(
                    result=RateLimitResult.TIMEOUT,
                    wait_time=0.0,
                )

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
            self._in_flight += 1
            return AcquireResult(
                result=RateLimitResult.ACQUIRED,
                wait_time=concurrency_wait,
            )

        # Calculate wait time for next token
        wait_time = (1.0 - self._tokens) / refill_rate
        total_wait = concurrency_wait + wait_time

        # Check timeout — don't modify state on timeout
        if self.max_wait_time is not None and total_wait > self.max_wait_time:
            return AcquireResult(
                result=RateLimitResult.TIMEOUT,
                wait_time=0.0,
            )

        # Reserve the token: deduct now (may go negative), caller will yield wait_time
        self._tokens -= 1.0
        self._in_flight += 1
        return AcquireResult(
            result=RateLimitResult.ACQUIRED,
            wait_time=total_wait,
        )

    def release_concurrency(self) -> None:
        """Release a concurrency slot after request completes."""
        self._in_flight = max(0, self._in_flight - 1)

    def record_latency(self, latency: float) -> None:
        """Record request latency using EMA."""
        if self._latency_ema is None:
            self._latency_ema = latency
        else:
            self._latency_ema = (
                self._latency_alpha * latency
                + (1.0 - self._latency_alpha) * self._latency_ema
            )

    def on_success(self) -> None:
        """Additive increase and concurrency recomputation."""
        # AIMD recovery
        recovery = self.max_requests * self.recovery_factor * self._jitter
        self._effective_max = min(
            float(self.max_requests),
            self._effective_max + recovery
        )

        # Recompute concurrency
        self._recompute_concurrency()

    def on_rate_limited(self) -> None:
        """Multiplicative decrease and concurrency recomputation."""
        # AIMD penalty
        jittered_penalty = self.penalty_factor * self._jitter
        self._effective_max = max(
            self._min_effective,
            self._effective_max * (1.0 - jittered_penalty)
        )
        self._tokens = min(self._tokens, self._effective_max)

        # Recompute concurrency
        self._recompute_concurrency()

    def _recompute_concurrency(self) -> None:
        """
        Recompute concurrency limit based on observed latency pressure.

        Uses Little's Law (L = λW) as a pressure metric:
        - High latency → high pressure → reduce concurrency (backpressure)
        - Low latency → low pressure → increase concurrency (probe capacity)

        Mirrors CongestionControlledHttpClient._recompute_concurrency().
        """
        if self._latency_ema is None:
            return

        rate_per_sec = self._effective_max / self.time_window
        # Pressure metric: how many requests "want" to be in-flight
        # High pressure = server is slow, reduce concurrency
        pressure = rate_per_sec * self._latency_ema

        pressure = max(1, int(math.ceil(pressure)))
        pressure = min(pressure, self.max_concurrency)

        if pressure == self._concurrency_limit:
            return

        if pressure > self._concurrency_limit:
            # High pressure → shrink immediately (backpressure)
            if self._concurrency_limit > 1:
                self._concurrency_limit -= 1
        else:
            # Low pressure → grow slowly (probe capacity)
            if self._concurrency_limit < self.max_concurrency:
                if self._jitter.random() < self._CONCURRENCY_GROWTH_PROBABILITY:
                    self._concurrency_limit += 1

    def get_effective_rate(self) -> float:
        """Get current adaptive effective rate."""
        return self._effective_max
