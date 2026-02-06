"""
Simulated client with retry and rate limiting.

Combines rate limiting and retry logic to simulate SDK behavior.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from simulations.src.config import RateLimitConfig, RetryConfig
from simulations.src.rate_limiters.base import RateLimiter, RateLimitResult
from simulations.src.rate_limiters.token_bucket import TokenBucketRateLimiter
from simulations.src.rate_limiters.adaptive import AdaptiveRateLimiter
from simulations.src.rate_limiters.congestion_aware import CongestionAwareRateLimiter
from simulations.src.retry import RetryHandler
from simulations.src.server import SimulatedServer, ServerResponse
from simulations.src.metrics import MetricsCollector, RequestMetrics, FailureReason

if TYPE_CHECKING:
    import simpy


@dataclass
class RequestResult:
    """Result of a client request."""

    success: bool
    status_code: int
    total_time: float
    attempts: int
    wait_time: float  # Time waiting for rate limit tokens
    retry_time: float  # Time spent in retry delays


class SimulatedClient:
    """
    Simulated SDK client with retry and rate limiting.

    Combines rate limiting (Token Bucket, Adaptive, or Congestion Controlled)
    with retry logic to simulate full SDK request flow.
    """

    def __init__(
        self,
        process_id: int,
        rate_limit_config: RateLimitConfig,
        retry_config: RetryConfig,
        server: SimulatedServer,
        metrics_collector: MetricsCollector,
        env: "simpy.Environment",
    ):
        """
        Initialize the simulated client.

        Args:
            process_id: Unique identifier for this client process.
            rate_limit_config: Rate limiting configuration.
            retry_config: Retry configuration.
            server: Simulated server to send requests to.
            metrics_collector: Collector for metrics.
            env: SimPy environment.
        """
        self.process_id = process_id
        self.rate_limit_config = rate_limit_config
        self.retry_config = retry_config
        self.server = server
        self.metrics_collector = metrics_collector
        self.env = env

        # Create rate limiter based on strategy
        self.rate_limiter = self._create_rate_limiter()

        # Create retry handler (per-request, so we'll create new ones)
        self.retry_handler: RetryHandler | None = None

        # Request counter
        self._request_id = 0

    def _create_rate_limiter(self) -> RateLimiter | None:
        """Create rate limiter based on configuration."""
        if self.rate_limit_config.strategy == "none":
            return None

        if self.rate_limit_config.strategy == "token_bucket":
            return TokenBucketRateLimiter(
                config=self.rate_limit_config,
                process_id=self.process_id,
            )

        if self.rate_limit_config.strategy == "adaptive":
            return AdaptiveRateLimiter(
                config=self.rate_limit_config,
                process_id=self.process_id,
            )

        if self.rate_limit_config.strategy == "congestion_aware":
            return CongestionAwareRateLimiter(
                config=self.rate_limit_config,
                process_id=self.process_id,
            )

        raise ValueError(f"Unknown strategy: {self.rate_limit_config.strategy}")

    def execute_request(self, client_type: str = "rqc") -> "simpy.Process":
        """
        Execute a request as a SimPy process.

        This is a generator that yields SimPy events for delays.

        Args:
            client_type: Type of client (rqc or agent).

        Yields:
            SimPy timeout events for delays.

        Returns:
            RequestResult via process return value.
        """
        self._request_id += 1
        request_id = self._request_id

        start_time = self.env.now
        total_wait_time = 0.0
        total_retry_time = 0.0
        attempts = 0
        final_status = 0
        success = False
        failure_reason: str | None = None

        # Create new retry handler for this request
        self.retry_handler = RetryHandler(self.retry_config)

        while True:
            attempts += 1
            self.metrics_collector.record_attempt()

            # Step 1: Acquire rate limit token (if rate limiting enabled)
            if self.rate_limiter is not None:
                acquire_result = self.rate_limiter.acquire_token(self.env.now)

                if acquire_result.result == RateLimitResult.TIMEOUT:
                    # Token acquisition timeout
                    self.metrics_collector.record_token_timeout(self.env.now)

                    # Check if we should retry token timeout
                    retry_decision = self.retry_handler.should_retry(
                        status_code=429,  # Treat as rate limit error
                        retry_after=None,
                    )

                    if retry_decision.should_retry:
                        total_retry_time += retry_decision.wait_time
                        yield self.env.timeout(retry_decision.wait_time)
                        continue

                    # No more retries - fail due to token timeout
                    final_status = 429
                    failure_reason = FailureReason.TOKEN_TIMEOUT
                    break

                # Wait for token
                if acquire_result.wait_time > 0:
                    total_wait_time += acquire_result.wait_time
                    yield self.env.timeout(acquire_result.wait_time)

            # Step 2: Send request to server
            response = self.server.handle_request(
                current_time=self.env.now,
                client_type=client_type,
            )

            # Wait for server response latency
            yield self.env.timeout(response.latency)

            # Release concurrency slot (always, regardless of response)
            if self.rate_limiter is not None:
                self.rate_limiter.release_concurrency()

            final_status = response.status_code

            # Step 3: Handle response
            if response.status_code == 200:
                # Success!
                success = True
                if self.rate_limiter is not None:
                    # Record latency only for successful requests.
                    # 429s have fixed low latency (10ms) which would dilute
                    # the pressure signal from actual server processing time.
                    self.rate_limiter.record_latency(response.latency)
                    self.rate_limiter.on_success()
                    self.metrics_collector.record_effective_rate(
                        self.env.now,
                        self.rate_limiter.get_effective_rate(),
                    )
                break

            if response.status_code == 429:
                # Rate limited by server
                self.metrics_collector.record_429(self.env.now)

                if self.rate_limiter is not None:
                    self.rate_limiter.on_rate_limited()
                    self.metrics_collector.record_effective_rate(
                        self.env.now,
                        self.rate_limiter.get_effective_rate(),
                    )

                # Check if we should retry
                retry_decision = self.retry_handler.should_retry(
                    status_code=429,
                    retry_after=response.retry_after,
                )

                if retry_decision.should_retry:
                    total_retry_time += retry_decision.wait_time
                    yield self.env.timeout(retry_decision.wait_time)
                    continue

                # No more retries - fail due to server 429
                failure_reason = FailureReason.SERVER_429
                break

            # Other status codes (5xx) - check retry
            retry_decision = self.retry_handler.should_retry(
                status_code=response.status_code,
                retry_after=None,
            )

            if retry_decision.should_retry:
                total_retry_time += retry_decision.wait_time
                yield self.env.timeout(retry_decision.wait_time)
                continue

            # No more retries - fail due to server error
            failure_reason = FailureReason.SERVER_ERROR
            break

        # Record metrics
        end_time = self.env.now
        metrics = RequestMetrics(
            process_id=self.process_id,
            request_id=request_id,
            start_time=start_time,
            end_time=end_time,
            success=success,
            status_code=final_status,
            attempts=attempts,
            wait_time=total_wait_time,
            retry_time=total_retry_time,
            failure_reason=failure_reason,
        )
        self.metrics_collector.record_request(metrics)

        # Return result (accessible via process.value in SimPy 4+)
        return RequestResult(
            success=success,
            status_code=final_status,
            total_time=end_time - start_time,
            attempts=attempts,
            wait_time=total_wait_time,
            retry_time=total_retry_time,
        )
