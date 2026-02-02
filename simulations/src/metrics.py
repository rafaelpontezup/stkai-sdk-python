"""
Metrics collection and aggregation for simulations.

Collects detailed metrics during simulation runs for analysis and visualization.
"""

from dataclasses import dataclass, field
from typing import Any
import numpy as np


class FailureReason:
    """Constants for failure reasons."""

    NONE = None  # Success
    TOKEN_TIMEOUT = "token_timeout"  # Rate limiter token acquisition timeout
    SERVER_429 = "server_429"  # Server rejected with 429 (exhausted retries)
    SERVER_ERROR = "server_error"  # Server 5xx error (exhausted retries)


@dataclass
class RequestMetrics:
    """Metrics for a single request."""

    process_id: int
    request_id: int
    start_time: float
    end_time: float
    success: bool
    status_code: int
    attempts: int
    wait_time: float  # Time waiting for rate limit token
    retry_time: float  # Time spent in retry delays
    failure_reason: str | None = None  # Why the request failed (None = success)


@dataclass
class TimeSeriesPoint:
    """A point in a time series."""

    time: float
    value: float


@dataclass
class SimulationMetrics:
    """Aggregated metrics from a simulation run."""

    # Configuration
    scenario_name: str
    strategy: str
    num_processes: int
    server_quota: int
    duration: float

    # Primary metrics
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_429s: int = 0
    token_timeouts: int = 0
    total_attempts: int = 0  # Includes retries (for server rejection rate)

    # Failure breakdown (client perspective - why did my request fail?)
    failures_token_timeout: int = 0  # Failed: couldn't get rate limit token
    failures_server_429: int = 0  # Failed: server rejected after all retries
    failures_server_error: int = 0  # Failed: server 5xx after all retries

    # Latency (in seconds) - total time including waits and retries
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
    latency_mean: float = 0.0

    # Wait time (time waiting for rate limit tokens)
    wait_time_total: float = 0.0
    wait_time_mean: float = 0.0
    wait_time_p95: float = 0.0

    # Retry time (time spent in retry delays)
    retry_time_total: float = 0.0
    retry_time_mean: float = 0.0

    # Throughput
    throughput_per_minute: float = 0.0
    rps_amplification: float = 1.0  # total_attempts / original_requests

    # Time series data (for visualization)
    success_rate_over_time: list[TimeSeriesPoint] = field(default_factory=list)
    effective_rate_over_time: list[TimeSeriesPoint] = field(default_factory=list)
    latency_over_time: list[TimeSeriesPoint] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Percentage of successful requests."""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100

    @property
    def rate_429(self) -> float:
        """Percentage of 429 responses (per original request, can exceed 100%)."""
        if self.total_requests == 0:
            return 0.0
        return (self.total_429s / self.total_requests) * 100

    @property
    def server_rejection_rate(self) -> float:
        """
        Percentage of server attempts that were rejected with 429.

        This is the TRUE server rejection rate: 429s / total_attempts.
        Unlike rate_429, this is always 0-100% and shows how often
        the server actually rejects requests.
        """
        if self.total_attempts == 0:
            return 0.0
        return (self.total_429s / self.total_attempts) * 100

    @property
    def failure_rate(self) -> float:
        """Percentage of failed requests (client perspective)."""
        if self.total_requests == 0:
            return 0.0
        return (self.failed_requests / self.total_requests) * 100

    @property
    def failure_rate_token_timeout(self) -> float:
        """Percentage of requests that failed due to token timeout."""
        if self.total_requests == 0:
            return 0.0
        return (self.failures_token_timeout / self.total_requests) * 100

    @property
    def failure_rate_server_429(self) -> float:
        """Percentage of requests that failed due to server 429."""
        if self.total_requests == 0:
            return 0.0
        return (self.failures_server_429 / self.total_requests) * 100

    @property
    def failure_rate_server_error(self) -> float:
        """Percentage of requests that failed due to server errors."""
        if self.total_requests == 0:
            return 0.0
        return (self.failures_server_error / self.total_requests) * 100

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for DataFrame creation."""
        return {
            "scenario": self.scenario_name,
            "strategy": self.strategy,
            "processes": self.num_processes,
            "quota": self.server_quota,
            "duration": self.duration,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": self.success_rate,
            "total_429s": self.total_429s,
            "rate_429": self.rate_429,
            "token_timeouts": self.token_timeouts,
            "latency_p50": self.latency_p50,
            "latency_p95": self.latency_p95,
            "latency_p99": self.latency_p99,
            "latency_mean": self.latency_mean,
            "wait_time_total": self.wait_time_total,
            "wait_time_mean": self.wait_time_mean,
            "wait_time_p95": self.wait_time_p95,
            "retry_time_total": self.retry_time_total,
            "retry_time_mean": self.retry_time_mean,
            "throughput_per_minute": self.throughput_per_minute,
            "rps_amplification": self.rps_amplification,
        }


class MetricsCollector:
    """
    Collects metrics during a simulation run.

    Thread-safe collection of request metrics with aggregation.
    """

    def __init__(
        self,
        scenario_name: str,
        strategy: str,
        num_processes: int,
        server_quota: int,
        bucket_size: float = 10.0,  # Time bucket for time series (seconds)
    ):
        self.scenario_name = scenario_name
        self.strategy = strategy
        self.num_processes = num_processes
        self.server_quota = server_quota
        self.bucket_size = bucket_size

        self._requests: list[RequestMetrics] = []
        self._429_times: list[float] = []
        self._token_timeout_times: list[float] = []
        self._effective_rates: list[tuple[float, float]] = []  # (time, rate)
        self._total_attempts = 0

    def record_request(self, metrics: RequestMetrics) -> None:
        """Record metrics for a completed request."""
        self._requests.append(metrics)

    def record_429(self, time: float) -> None:
        """Record a 429 response."""
        self._429_times.append(time)

    def record_token_timeout(self, time: float) -> None:
        """Record a token acquisition timeout."""
        self._token_timeout_times.append(time)

    def record_effective_rate(self, time: float, rate: float) -> None:
        """Record the current effective rate (for AIMD tracking)."""
        self._effective_rates.append((time, rate))

    def record_attempt(self) -> None:
        """Record a request attempt (for RPS amplification)."""
        self._total_attempts += 1

    def aggregate(self, duration: float) -> SimulationMetrics:
        """
        Aggregate collected metrics into summary statistics.

        Args:
            duration: Total simulation duration in seconds.

        Returns:
            SimulationMetrics with aggregated data.
        """
        metrics = SimulationMetrics(
            scenario_name=self.scenario_name,
            strategy=self.strategy,
            num_processes=self.num_processes,
            server_quota=self.server_quota,
            duration=duration,
        )

        if not self._requests:
            return metrics

        # Count totals
        metrics.total_requests = len(self._requests)
        metrics.successful_requests = sum(1 for r in self._requests if r.success)
        metrics.failed_requests = metrics.total_requests - metrics.successful_requests
        metrics.total_429s = len(self._429_times)
        metrics.token_timeouts = len(self._token_timeout_times)
        metrics.total_attempts = self._total_attempts

        # Count failure breakdown (client perspective)
        for r in self._requests:
            if not r.success:
                if r.failure_reason == FailureReason.TOKEN_TIMEOUT:
                    metrics.failures_token_timeout += 1
                elif r.failure_reason == FailureReason.SERVER_429:
                    metrics.failures_server_429 += 1
                elif r.failure_reason == FailureReason.SERVER_ERROR:
                    metrics.failures_server_error += 1

        # Calculate latencies (only for completed requests)
        latencies = [r.end_time - r.start_time for r in self._requests]
        if latencies:
            metrics.latency_p50 = float(np.percentile(latencies, 50))
            metrics.latency_p95 = float(np.percentile(latencies, 95))
            metrics.latency_p99 = float(np.percentile(latencies, 99))
            metrics.latency_mean = float(np.mean(latencies))

        # Calculate wait times (time waiting for rate limit tokens)
        wait_times = [r.wait_time for r in self._requests]
        if wait_times:
            metrics.wait_time_total = float(sum(wait_times))
            metrics.wait_time_mean = float(np.mean(wait_times))
            metrics.wait_time_p95 = float(np.percentile(wait_times, 95))

        # Calculate retry times
        retry_times = [r.retry_time for r in self._requests]
        if retry_times:
            metrics.retry_time_total = float(sum(retry_times))
            metrics.retry_time_mean = float(np.mean(retry_times))

        # Throughput
        if duration > 0:
            metrics.throughput_per_minute = (metrics.successful_requests / duration) * 60

        # RPS amplification
        original_requests = len(self._requests)
        if original_requests > 0 and self._total_attempts > 0:
            metrics.rps_amplification = self._total_attempts / original_requests

        # Time series: success rate over time
        metrics.success_rate_over_time = self._calculate_success_rate_time_series(duration)

        # Time series: effective rate over time
        metrics.effective_rate_over_time = self._calculate_effective_rate_time_series()

        # Time series: latency over time
        metrics.latency_over_time = self._calculate_latency_time_series(duration)

        return metrics

    def _calculate_success_rate_time_series(self, duration: float) -> list[TimeSeriesPoint]:
        """Calculate success rate in time buckets."""
        if not self._requests:
            return []

        points = []
        bucket_start = 0.0

        while bucket_start < duration:
            bucket_end = bucket_start + self.bucket_size
            bucket_requests = [
                r for r in self._requests
                if bucket_start <= r.end_time < bucket_end
            ]

            if bucket_requests:
                success_count = sum(1 for r in bucket_requests if r.success)
                rate = (success_count / len(bucket_requests)) * 100
                points.append(TimeSeriesPoint(time=bucket_start, value=rate))

            bucket_start = bucket_end

        return points

    def _calculate_effective_rate_time_series(self) -> list[TimeSeriesPoint]:
        """Convert effective rate recordings to time series."""
        return [
            TimeSeriesPoint(time=t, value=r)
            for t, r in self._effective_rates
        ]

    def _calculate_latency_time_series(self, duration: float) -> list[TimeSeriesPoint]:
        """Calculate mean latency in time buckets."""
        if not self._requests:
            return []

        points = []
        bucket_start = 0.0

        while bucket_start < duration:
            bucket_end = bucket_start + self.bucket_size
            bucket_requests = [
                r for r in self._requests
                if bucket_start <= r.end_time < bucket_end
            ]

            if bucket_requests:
                latencies = [r.end_time - r.start_time for r in bucket_requests]
                mean_latency = float(np.mean(latencies))
                points.append(TimeSeriesPoint(time=bucket_start, value=mean_latency))

            bucket_start = bucket_end

        return points
