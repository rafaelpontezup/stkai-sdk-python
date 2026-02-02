"""
Pure Congestion Control - TCP-style without rate limiting.

Controls only CONCURRENCY via latency feedback.
No token bucket. No AIMD on rate.
"""

from simulations.src.config import RateLimitConfig
from simulations.src.rate_limiters.base import (
    RateLimiter,
    RateLimitResult,
    AcquireResult,
)


class PureCongestionControlRateLimiter(RateLimiter):
    """
    TCP-style congestion control.

    Key differences from CongestionControlledRateLimiter:
    - NO token bucket (no rate limiting)
    - NO AIMD on rate
    - ONLY cwnd (congestion window) controls throughput
    - Latency feedback adjusts cwnd

    The effective rate emerges from: rate = cwnd / latency
    """

    # Thresholds for latency-based decisions
    _LATENCY_HEALTHY_MULTIPLIER = 1.5   # < rtt_min * 1.5 = healthy
    _LATENCY_PRESSURE_MULTIPLIER = 2.0  # > rtt_min * 2.0 = pressure

    def __init__(self, config: RateLimitConfig, process_id: int = 0):
        """
        Initialize pure congestion control.

        Args:
            config: Rate limit configuration.
            process_id: Process ID (unused, for interface compatibility).
        """
        self.max_cwnd = config.max_concurrency
        self.max_wait_time = config.max_wait_time

        # Congestion window state
        initial = config.initial_cwnd if config.initial_cwnd is not None else 1
        self._cwnd = initial
        self._ssthresh = self.max_cwnd  # slow start threshold
        self._in_flight = 0

        # RTT tracking
        self._rtt_min: float | None = None  # baseline (minimum observed)
        self._rtt_ema: float | None = None  # smoothed average
        self._rtt_alpha = 0.125  # EMA smoothing (TCP default)

        # For fractional cwnd growth in congestion avoidance
        self._cwnd_fractional = 0.0

    def acquire_token(self, current_time: float) -> AcquireResult:
        """
        Try to acquire a slot in the congestion window.

        No token bucket - just check if cwnd allows more in-flight.
        """
        if self._in_flight < self._cwnd:
            self._in_flight += 1
            return AcquireResult(result=RateLimitResult.ACQUIRED, wait_time=0.0)

        # Window full - estimate wait time based on RTT
        if self._rtt_ema is not None:
            estimated_wait = self._rtt_ema
        else:
            estimated_wait = 0.5  # default estimate

        # Check timeout
        if self.max_wait_time is not None and estimated_wait > self.max_wait_time:
            return AcquireResult(result=RateLimitResult.TIMEOUT, wait_time=0.0)

        # Will need to wait for a slot
        # In simulation, we return the wait time and let SimPy handle it
        # After waiting, caller should retry acquire_token
        return AcquireResult(result=RateLimitResult.ACQUIRED, wait_time=estimated_wait)

    def release_concurrency(self) -> None:
        """Release a slot (decrement in_flight)."""
        self._in_flight = max(0, self._in_flight - 1)

    def record_latency(self, latency: float) -> None:
        """Record latency and adjust cwnd based on it."""
        self._update_rtt(latency)

        # Decide growth/shrink based on latency health
        if self._is_latency_healthy(latency):
            self._grow_cwnd()
        elif self._is_latency_pressured(latency):
            self._shrink_cwnd_gentle()

    def on_success(self) -> None:
        """
        Called on successful response.

        In pure congestion control, growth is handled by record_latency.
        This is a no-op to maintain interface compatibility.
        """
        pass  # Growth handled in record_latency

    def on_rate_limited(self) -> None:
        """
        Called on 429 response.

        This is a strong signal - shrink cwnd aggressively (TCP-style).
        """
        # Multiplicative decrease
        self._ssthresh = max(self._cwnd // 2, 1)
        self._cwnd = max(self._cwnd // 2, 1)
        self._cwnd_fractional = 0.0

    def get_effective_rate(self) -> float:
        """
        Estimate effective rate based on cwnd and RTT.

        rate = cwnd / rtt
        """
        if self._rtt_ema is None or self._rtt_ema == 0:
            return float(self._cwnd) * 60  # rough estimate: cwnd * 60 req/min
        # Convert to req/min
        return (self._cwnd / self._rtt_ema) * 60

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

    def _is_latency_healthy(self, latency: float) -> bool:
        """Is latency close to baseline? (can grow)"""
        if self._rtt_min is None:
            return True
        return latency < self._rtt_min * self._LATENCY_HEALTHY_MULTIPLIER

    def _is_latency_pressured(self, latency: float) -> bool:
        """Is latency elevated? (should shrink)"""
        if self._rtt_min is None:
            return False
        return latency > self._rtt_min * self._LATENCY_PRESSURE_MULTIPLIER

    def _grow_cwnd(self) -> None:
        """Grow congestion window (TCP-style)."""
        if self._cwnd >= self.max_cwnd:
            return

        if self._cwnd < self._ssthresh:
            # Slow start: exponential growth (+1 per success)
            self._cwnd = min(self._cwnd + 1, self.max_cwnd)
        else:
            # Congestion avoidance: linear growth
            # TCP: cwnd += 1/cwnd per ACK
            # We accumulate fractional growth
            self._cwnd_fractional += 1.0 / self._cwnd
            if self._cwnd_fractional >= 1.0:
                self._cwnd = min(self._cwnd + 1, self.max_cwnd)
                self._cwnd_fractional = 0.0

    def _shrink_cwnd_gentle(self) -> None:
        """Gentle shrink on latency pressure (not 429)."""
        if self._cwnd > 1:
            self._cwnd -= 1
            self._cwnd_fractional = 0.0
