"""
Configuration dataclasses for simulations.

These mirror the stkai SDK configuration but are independent to avoid
coupling the simulation to the SDK implementation.
"""

from dataclasses import dataclass, field
from typing import Literal


RateLimitStrategy = Literal["none", "token_bucket", "adaptive", "congestion_aware"]


@dataclass(frozen=True)
class RetryConfig:
    """
    Retry configuration - mirrors stkai._retry.Retrying.

    Attributes:
        max_retries: Maximum retry attempts (0 = disabled, 3 = 4 total attempts).
        initial_delay: Initial delay in seconds for first retry.
        jitter_factor: Random variation applied to delays (±10%).
        max_retry_after: Maximum Retry-After header value to respect.
    """

    max_retries: int = 3
    initial_delay: float = 0.5
    jitter_factor: float = 0.10
    max_retry_after: float = 60.0


@dataclass(frozen=True)
class RateLimitConfig:
    """
    Rate limiting configuration - mirrors stkai._config.RateLimitConfig.

    Attributes:
        strategy: Rate limiting algorithm to use.
        max_requests: Maximum requests per time window.
        time_window: Time window in seconds.
        max_wait_time: Maximum wait for token (None = unlimited).
        min_rate_floor: Minimum rate as fraction of max_requests (adaptive).
        penalty_factor: Rate reduction on 429 (adaptive).
        recovery_factor: Rate increase on success (adaptive).
        jitter_factor: Jitter applied to AIMD operations (adaptive).
        max_concurrency: Maximum in-flight requests (congestion_controlled).
    """

    strategy: RateLimitStrategy = "adaptive"
    max_requests: int = 100
    time_window: float = 60.0
    max_wait_time: float | None = 30.0
    # Adaptive parameters
    min_rate_floor: float = 0.1
    penalty_factor: float = 0.3
    recovery_factor: float = 0.05
    jitter_factor: float = 0.20
    # Congestion controlled parameters
    max_concurrency: int = 8
    initial_concurrency: int | None = None  # None = use max_concurrency
    # Pure congestion parameters (TCP-style)
    initial_cwnd: int | None = None  # None = start at 1 (conservative)
    # Congestion-aware parameters (Little's Law)
    pressure_threshold: float = 2.0  # Backpressure when pressure > threshold

    # Preset factories
    @classmethod
    def conservative(cls, max_requests: int = 20) -> "RateLimitConfig":
        """Conservative preset: stability over throughput."""
        return cls(
            strategy="adaptive",
            max_requests=max_requests,
            time_window=60.0,
            max_wait_time=120.0,
            min_rate_floor=0.05,
            penalty_factor=0.5,
            recovery_factor=0.02,
        )

    @classmethod
    def balanced(cls, max_requests: int = 40) -> "RateLimitConfig":
        """Balanced preset: sensible defaults."""
        return cls(
            strategy="adaptive",
            max_requests=max_requests,
            time_window=60.0,
            max_wait_time=45.0,
            min_rate_floor=0.1,
            penalty_factor=0.3,
            recovery_factor=0.05,
        )

    @classmethod
    def optimistic(cls, max_requests: int = 80) -> "RateLimitConfig":
        """Optimistic preset: throughput over stability."""
        return cls(
            strategy="adaptive",
            max_requests=max_requests,
            time_window=60.0,
            max_wait_time=20.0,
            min_rate_floor=0.3,
            penalty_factor=0.15,
            recovery_factor=0.1,
        )

    @classmethod
    def token_bucket(cls, max_requests: int = 100) -> "RateLimitConfig":
        """Simple token bucket (no adaptation)."""
        return cls(
            strategy="token_bucket",
            max_requests=max_requests,
            time_window=60.0,
            max_wait_time=30.0,
        )

    @classmethod
    def none(cls) -> "RateLimitConfig":
        """No rate limiting (retry only)."""
        return cls(strategy="none")


@dataclass(frozen=True)
class ServerConfig:
    """
    Simulated server configuration.

    Attributes:
        quota_per_minute: Total requests allowed per minute across all clients.
        request_latency_ms: Base latency for RQC POST requests.
        agent_latency_ms: Latency for Agent POST requests (10-30s).
        quota_reset_interval: Seconds between quota resets.
        retry_after_seconds: Retry-After header value on 429.
    """

    quota_per_minute: int = 100
    request_latency_ms: float = 200.0
    agent_latency_ms: float = 15000.0
    quota_reset_interval: float = 60.0
    retry_after_seconds: float = 5.0


@dataclass(frozen=True)
class SimulationConfig:
    """
    Simulation run configuration.

    Attributes:
        duration_seconds: Total simulation duration.
        num_processes: Number of concurrent client processes.
        workers_per_process: Number of concurrent workers per process (default 8 for RQC).
        requests_per_process: Total requests each process will attempt (distributed among workers).
        arrival_pattern: Request arrival distribution.
        random_seed: Seed for reproducibility (None = random).
        client_type: Type of client to simulate (rqc or agent).
    """

    duration_seconds: float = 300.0
    num_processes: int = 5
    workers_per_process: int = 8  # Default matches RQC's max_workers
    requests_per_process: int = 50
    arrival_pattern: Literal["poisson", "constant", "burst"] = "poisson"
    random_seed: int | None = 42
    client_type: Literal["rqc", "agent"] = "rqc"


@dataclass
class ScenarioConfig:
    """
    Complete scenario configuration.

    Combines all configuration components for a simulation run.
    """

    name: str
    description: str
    server: ServerConfig = field(default_factory=ServerConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig.balanced)
    retry: RetryConfig = field(default_factory=RetryConfig)
    simulation: SimulationConfig = field(default_factory=SimulationConfig)
