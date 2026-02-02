"""
Congestion-Aware Rate Limiter - Uses Little's Law for concurrency control.

This is the simulation equivalent of `CongestionAwareHttpClient` from the SDK.
It adds concurrency control via Little's Law to the underlying rate limiter.

Architecture difference from SDK:
- SDK: RateLimiter(delegate=CongestionAware(delegate=HttpClient))
- Simulation: CongestionAware(delegate=RateLimiter) - wrapper approach

The simulation uses a wrapper approach because SimulatedClient expects a single
RateLimiter interface. The wrapper adds concurrency control on top of the
underlying rate limiter.
"""

from simulations.src.config import RateLimitConfig
from simulations.src.rate_limiters.base import (
    RateLimiter,
    RateLimitResult,
    AcquireResult,
)
from simulations.src.rate_limiters.adaptive import AdaptiveRateLimiter


class CongestionAwareRateLimiter(RateLimiter):
    """
    Rate limiter that adds congestion-aware concurrency control via Little's Law.

    MENTAL MODEL
    ------------
    This wrapper adds concurrency control to an underlying rate limiter.
    It uses Little's Law (L = λW) to estimate system pressure:

        pressure = throughput × latency

    Where:
    - throughput = current rate from delegate (requests/second)
    - latency = smoothed observed latency (EMA)
    - pressure = estimated concurrent requests "wanting" to be in-flight

    When pressure exceeds the threshold:
    - We reduce concurrency (fewer parallel requests)
    - Additional requests wait until slots are available

    This provides PROACTIVE backpressure based on latency, rather than
    waiting for 429 responses.

    KEY DIFFERENCE FROM CongestionControlledRateLimiter
    --------------------------------------------------
    - CongestionControlled: Tight coupling of rate + concurrency + latency
    - CongestionAware: Pure concurrency control using pressure threshold

    CongestionAware is simpler and more composable - it only cares about
    concurrency, delegating rate control entirely to the wrapped limiter.
    """

    def __init__(self, config: RateLimitConfig, process_id: int = 0):
        """
        Initialize congestion-aware rate limiter.

        Args:
            config: Rate limit configuration.
            process_id: Process ID for jitter seeding.
        """
        # Create the underlying rate limiter (handles AIMD)
        self._delegate = AdaptiveRateLimiter(config, process_id)

        # Pressure threshold: when pressure > threshold, we're congested
        # Lower values = more conservative (earlier backpressure)
        self._pressure_threshold = config.pressure_threshold

        # Concurrency tracking (SimPy is single-threaded, so counter is sufficient)
        self._max_concurrency = config.max_concurrency
        self._current_concurrency = 0

        # Latency tracking (EMA)
        self._latency_ema: float | None = None
        self._latency_alpha = 0.2

        # Throughput tracking
        self._last_time: float | None = None
        self._request_count = 0
        self._throughput: float = 0.0
        self._throughput_window = 5.0  # seconds

        # Time window from config (for rate calculation fallback)
        self._time_window = config.time_window

    def acquire_token(self, current_time: float) -> AcquireResult:
        """
        Acquire token with concurrency-aware backpressure.

        First checks pressure via Little's Law. If pressure is high,
        returns extra wait time proportional to latency. Then delegates
        to the underlying rate limiter for token acquisition.
        """
        # Calculate pressure-based wait (concurrency backpressure)
        pressure_wait = self._calculate_pressure_wait()

        # Delegate to underlying rate limiter for token acquisition
        result = self._delegate.acquire_token(current_time)

        # Combine waits: pressure wait + token wait
        total_wait = pressure_wait + result.wait_time

        # Track concurrency (will be decremented in release_concurrency)
        self._current_concurrency += 1

        return AcquireResult(
            result=result.result,
            wait_time=total_wait,
        )

    def on_success(self) -> None:
        """Delegate to underlying rate limiter."""
        self._delegate.on_success()

    def on_rate_limited(self) -> None:
        """Delegate to underlying rate limiter."""
        self._delegate.on_rate_limited()

    def release_concurrency(self) -> None:
        """Release concurrency slot after request completes."""
        if self._current_concurrency > 0:
            self._current_concurrency -= 1

    def record_latency(self, latency: float) -> None:
        """
        Record latency for pressure calculation using EMA.

        Args:
            latency: Request latency in seconds.
        """
        if self._latency_ema is None:
            self._latency_ema = latency
        else:
            self._latency_ema = (
                self._latency_alpha * latency +
                (1 - self._latency_alpha) * self._latency_ema
            )

        # Update throughput estimate
        self._request_count += 1

    def get_effective_rate(self) -> float:
        """Get effective rate from delegate."""
        return self._delegate.get_effective_rate()

    def _calculate_pressure(self) -> float:
        """
        Calculate pressure using Little's Law (L = λW).

        Returns:
            Estimated number of concurrent requests "wanting" to be in-flight.
        """
        if self._latency_ema is None:
            return 0.0

        # Get current rate from delegate (requests per minute)
        effective_rate_per_min = self._delegate.get_effective_rate()
        # Convert to requests per second
        rate_per_sec = effective_rate_per_min / 60.0

        # Little's Law: L = λW
        return rate_per_sec * self._latency_ema

    def _calculate_pressure_wait(self) -> float:
        """
        Calculate additional wait time based on pressure.

        When pressure exceeds threshold, we add wait time proportional
        to how much we're over the threshold. This provides graduated
        backpressure - higher pressure = longer waits.

        Returns:
            Additional wait time in seconds (0.0 if not congested).
        """
        pressure = self._calculate_pressure()

        if pressure <= self._pressure_threshold:
            return 0.0

        # Pressure exceeds threshold - apply backpressure
        # Wait time proportional to excess pressure
        excess_ratio = pressure / self._pressure_threshold

        # Base wait: latency EMA (wait one "cycle")
        base_wait = self._latency_ema if self._latency_ema else 0.2

        # Scale by how much over threshold we are
        # excess_ratio of 2.0 means pressure is 2x threshold → wait 1x latency
        # excess_ratio of 3.0 means pressure is 3x threshold → wait 2x latency
        return base_wait * (excess_ratio - 1.0)
