"""
Latency-Aware Rate Limiter - Wrapper that adds backpressure based on latency.

Wraps any rate limiter and applies additional backpressure when latency
indicates server pressure, BEFORE receiving 429s.
"""

from simulations.src.config import RateLimitConfig
from simulations.src.rate_limiters.base import (
    RateLimiter,
    RateLimitResult,
    AcquireResult,
)
from simulations.src.rate_limiters.adaptive import AdaptiveRateLimiter


class LatencyAwareRateLimiter(RateLimiter):
    """
    Wrapper that adds latency-based backpressure to AdaptiveRateLimiter.

    Key behavior:
    - Server OK (latency normal): pass-through, no interference
    - Server under pressure (latency high): apply backpressure to delegate

    This allows the user's rate limit configuration to remain unchanged,
    while adding proactive congestion detection via latency.
    """

    # Thresholds for latency-based decisions
    _LATENCY_PRESSURE_MULTIPLIER = 2.0   # > rtt_min * 2.0 = pressure
    _LATENCY_CRITICAL_MULTIPLIER = 3.0   # > rtt_min * 3.0 = critical

    def __init__(self, config: RateLimitConfig, process_id: int = 0):
        """
        Initialize latency-aware wrapper.

        Args:
            config: Rate limit configuration (passed to delegate).
            process_id: Process ID for jitter seeding.
        """
        # Create the underlying adaptive rate limiter
        self._delegate = AdaptiveRateLimiter(config, process_id)

        # RTT tracking (independent from delegate)
        self._rtt_min: float | None = None  # baseline (minimum observed)
        self._rtt_ema: float | None = None  # smoothed average
        self._rtt_alpha = 0.125  # EMA smoothing factor

        # Backpressure state
        self._consecutive_pressure_count = 0
        self._pressure_threshold = 3  # Apply backpressure after N consecutive pressured requests

    def acquire_token(self, current_time: float) -> AcquireResult:
        """
        Acquire token from delegate.

        If under sustained pressure, apply backpressure before acquiring.
        """
        # Check if we should apply proactive backpressure
        if self._should_apply_backpressure():
            # Simulate a "soft 429" - apply AIMD penalty without actual rejection
            self._delegate.on_rate_limited()
            self._consecutive_pressure_count = 0  # Reset after applying

        return self._delegate.acquire_token(current_time)

    def on_success(self) -> None:
        """Delegate to underlying rate limiter."""
        self._delegate.on_success()

    def on_rate_limited(self) -> None:
        """Delegate to underlying rate limiter."""
        self._delegate.on_rate_limited()
        # Also reset pressure count since we got explicit feedback
        self._consecutive_pressure_count = 0

    def release_concurrency(self) -> None:
        """No concurrency control in this wrapper."""
        pass

    def record_latency(self, latency: float) -> None:
        """
        Record latency and track pressure state.

        This is the key method that enables proactive backpressure.
        """
        self._update_rtt(latency)

        # Track consecutive pressured requests
        if self._is_under_pressure(latency):
            self._consecutive_pressure_count += 1
        else:
            self._consecutive_pressure_count = 0

    def get_effective_rate(self) -> float:
        """Get effective rate from delegate."""
        return self._delegate.get_effective_rate()

    def _update_rtt(self, latency: float) -> None:
        """Update RTT estimates."""
        # Track minimum (baseline)
        if self._rtt_min is None or latency < self._rtt_min:
            self._rtt_min = latency

        # Update EMA
        if self._rtt_ema is None:
            self._rtt_ema = latency
        else:
            self._rtt_ema = (
                self._rtt_alpha * latency +
                (1 - self._rtt_alpha) * self._rtt_ema
            )

    def _is_under_pressure(self, latency: float) -> bool:
        """Is current latency indicating server pressure?"""
        if self._rtt_min is None:
            return False
        return latency > self._rtt_min * self._LATENCY_PRESSURE_MULTIPLIER

    def _should_apply_backpressure(self) -> bool:
        """Should we apply proactive backpressure?"""
        # Only apply after sustained pressure (avoid reacting to noise)
        return self._consecutive_pressure_count >= self._pressure_threshold
