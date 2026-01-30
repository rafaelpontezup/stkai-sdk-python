"""
Rate limiting components for the stkai SDK.

This module provides rate limiting decorators for HTTP clients using
different algorithms:

- Token Bucket: Simple, predictable rate limiting
- Adaptive (AIMD): Dynamic rate adjustment based on server responses

Available implementations:
    - TokenBucketRateLimitedHttpClient: Decorator that adds rate limiting (Token Bucket).
    - AdaptiveRateLimitedHttpClient: Decorator with adaptive rate limiting (AIMD).

Example (Token Bucket):
    >>> from stkai._rate_limit import TokenBucketRateLimitedHttpClient
    >>> from stkai._http import EnvironmentAwareHttpClient
    >>> client = TokenBucketRateLimitedHttpClient(
    ...     delegate=EnvironmentAwareHttpClient(),
    ...     max_requests=10,
    ...     time_window=60.0,
    ... )

Example (Adaptive):
    >>> from stkai._rate_limit import AdaptiveRateLimitedHttpClient
    >>> from stkai._http import StkCLIHttpClient
    >>> client = AdaptiveRateLimitedHttpClient(
    ...     delegate=StkCLIHttpClient(),
    ...     max_requests=100,
    ...     time_window=60.0,
    ...     min_rate_floor=0.1,
    ... )
"""

import logging
import math
import os
import random
import socket
import threading
import time
from typing import Any, override

import requests

from stkai._http import HttpClient
from stkai._retry import RetryableError
from stkai._utils import sleep_with_jitter

logger = logging.getLogger(__name__)


# =============================================================================
# Jitter Abstraction
# =============================================================================


class Jitter:
    """
    Structural jitter for desynchronizing processes sharing a quota.

    Uses a per-process seeded RNG to ensure:
    - Same process = deterministic sequence (reproducible for debugging)
    - Different processes = different sequences (desynchronization)

    The jitter factor determines the range of random variation applied
    to values. A factor of 0.20 means values will be multiplied by a
    random number in the range [0.80, 1.20] (±20%).

    Example:
        >>> jitter = Jitter(factor=0.20)
        >>> # Apply jitter to a value
        >>> jittered = jitter.apply(100.0)  # Returns ~80-120
        >>> # Or use multiplication syntax
        >>> jittered = 100.0 * jitter  # Same effect

    Args:
        factor: Jitter factor (default: 0.20 = ±20%).
        rng: Optional RNG for testing. If None, creates a per-process seeded RNG.
    """

    def __init__(self, factor: float = 0.20, rng: random.Random | None = None):
        """
        Initialize the jitter generator.

        Args:
            factor: Jitter factor as a fraction (e.g., 0.20 for ±20%).
            rng: Optional RNG for dependency injection in tests.
                 If None, creates a deterministic per-process RNG.
        """
        assert factor >= 0, "factor must be non-negative"
        assert factor < 1, "factor must be less than 1"

        self.factor = factor
        self._rng = rng or self._create_process_local_rng()

    @staticmethod
    def _create_process_local_rng() -> random.Random:
        """
        Create a deterministic RNG seeded with hostname and PID.

        This ensures:
        - Same process = same random sequence (deterministic)
        - Different processes = different sequences (desynchronization)
        """
        seed = hash((socket.gethostname(), os.getpid()))
        return random.Random(seed)

    def next(self) -> float:
        """
        Return a random jitter value in [1-factor, 1+factor].

        Each call returns a new random value. Use this when you need
        the raw jitter multiplier.

        Returns:
            A random value in the range [1-factor, 1+factor].
        """
        return self._rng.uniform(1.0 - self.factor, 1.0 + self.factor)

    def random(self) -> float:
        """
        Return a random value in [0, 1).

        Use this for probabilistic decisions that don't need the jitter factor.
        Each call returns a new random value.

        Returns:
            A random value in the range [0, 1).
        """
        return self._rng.random()

    def apply(self, value: float) -> float:
        """
        Multiply value by a jittered factor.

        Args:
            value: The value to apply jitter to.

        Returns:
            The value multiplied by a random factor in [1-factor, 1+factor].
        """
        return value * self.next()

    def __mul__(self, other: float) -> float:
        """
        Support: jitter * value

        Args:
            other: The value to multiply.

        Returns:
            The jittered value.
        """
        return self.apply(other)

    def __rmul__(self, other: float) -> float:
        """
        Support: value * jitter

        Args:
            other: The value to multiply.

        Returns:
            The jittered value.
        """
        return self.apply(other)


# =============================================================================
# Exceptions
# =============================================================================


class ClientSideRateLimitError(RetryableError):
    """
    Base exception for client-side rate limiting errors.

    This is the base class for all rate limiting errors that originate
    from the client's rate limiter (TokenBucket, Adaptive, etc.), as opposed
    to server-side rate limiting (HTTP 429).

    Extends RetryableError so all client-side rate limit errors are
    automatically retried by the Retrying context manager.

    Example:
        >>> try:
        ...     client.post(url, data)
        ... except ClientSideRateLimitError as e:
        ...     print(f"Client-side rate limit: {e}")
    """

    pass


class TokenAcquisitionTimeoutError(ClientSideRateLimitError):
    """
    Raised when rate limiter exceeds max_wait_time waiting for a token.

    This exception indicates that a thread waited too long to acquire
    a rate limit token and gave up. This prevents threads from blocking
    indefinitely when rate limits are very restrictive.

    Extends ClientSideRateLimitError (which extends RetryableError) so it's
    automatically retried by the Retrying context manager, following the
    pattern used by Resilience4J, Polly, failsafe-go, AWS SDK, and Spring
    Retry - where rate limit/throttling exceptions are retryable by default.

    Attributes:
        waited: Time in seconds the thread waited before giving up.
        max_wait_time: The configured maximum wait time.

    Example:
        >>> try:
        ...     client.post(url, data)
        ... except TokenAcquisitionTimeoutError as e:
        ...     print(f"Rate limit timeout after {e.waited:.1f}s")
    """

    def __init__(self, waited: float, max_wait_time: float):
        self.waited = waited
        self.max_wait_time = max_wait_time
        super().__init__(
            f"Rate limit timeout: waited {waited:.2f}s, max_wait_time={max_wait_time:.2f}s"
        )


class ServerSideRateLimitError(RetryableError):
    """
    Raised when server returns HTTP 429 (Too Many Requests).

    This exception indicates that the server has rate-limited the request.
    It wraps the original response so the Retry-After header can be extracted
    for calculating the appropriate wait time before retrying.

    Extends RetryableError so it's automatically retried by the Retrying
    context manager. The Retrying class will extract the Retry-After header
    from the wrapped response to determine the wait time.

    Only raised by AdaptiveRateLimitedHttpClient after applying AIMD penalty.
    Other clients (TokenBucket, no rate-limit) let HTTPError propagate directly.

    Attributes:
        response: The original HTTP response with status code 429.

    Example:
        >>> try:
        ...     client.post(url, data)
        ... except ServerSideRateLimitError as e:
        ...     retry_after = e.response.headers.get("Retry-After")
        ...     print(f"Server rate limited. Retry after: {retry_after}s")
    """

    def __init__(self, response: requests.Response):
        self.response = response
        super().__init__("Server rate limit exceeded (HTTP 429)")


# =============================================================================
# Rate-Limited Decorators
# =============================================================================


class TokenBucketRateLimitedHttpClient(HttpClient):
    """
    HTTP client decorator that applies rate limiting to requests.

    Uses the Token Bucket algorithm to limit the rate of requests.
    Only POST requests are rate-limited; GET requests (typically polling)
    pass through without limiting.

    This decorator is thread-safe and can be used with concurrent requests.

    Example:
        >>> from stkai._rate_limit import TokenBucketRateLimitedHttpClient
        >>> from stkai._http import StkCLIHttpClient
        >>> # Limit to 10 requests per minute, give up after 30s waiting
        >>> client = TokenBucketRateLimitedHttpClient(
        ...     delegate=StkCLIHttpClient(),
        ...     max_requests=10,
        ...     time_window=60.0,
        ...     max_wait_time=30.0,
        ... )

    Args:
        delegate: The underlying HTTP client to delegate requests to.
        max_requests: Maximum number of requests allowed in the time window.
        time_window: Time window in seconds for the rate limit.
        max_wait_time: Maximum time in seconds to wait for a token. If None,
            waits indefinitely. Default is 30 seconds.

    Raises:
        TokenAcquisitionTimeoutError: If max_wait_time is exceeded while waiting for a token.
    """

    def __init__(
        self,
        delegate: HttpClient,
        max_requests: int,
        time_window: float,
        max_wait_time: float | None = 30.0,
    ):
        """
        Initialize the rate-limited HTTP client.

        Args:
            delegate: The underlying HTTP client to delegate requests to.
            max_requests: Maximum number of requests allowed in the time window.
            time_window: Time window in seconds for the rate limit.
            max_wait_time: Maximum time in seconds to wait for a token.
                If None, waits indefinitely. Default is 30 seconds.

        Raises:
            AssertionError: If any parameter is invalid.
        """
        assert delegate is not None, "Delegate HTTP client is required."
        assert max_requests is not None, "max_requests cannot be None."
        assert max_requests > 0, "max_requests must be greater than 0."
        assert time_window is not None, "time_window cannot be None."
        assert time_window > 0, "time_window must be greater than 0."
        assert max_wait_time is None or max_wait_time > 0, "max_wait_time must be > 0 or None."

        self.delegate = delegate
        self.max_requests = max_requests
        self.time_window = time_window
        self.max_wait_time = max_wait_time

        # Token bucket state
        self._tokens = float(max_requests)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _acquire_token(self) -> None:
        """
        Acquire a token, blocking if necessary until one is available.

        Uses Token Bucket algorithm:
        - Refills tokens based on elapsed time
        - Waits if no tokens are available
        - Raises TokenAcquisitionTimeoutError if max_wait_time is exceeded

        Raises:
            TokenAcquisitionTimeoutError: If waiting exceeds max_wait_time.
        """
        start_time = time.monotonic()

        while True:
            with self._lock:
                now = time.monotonic()
                # Refill tokens based on elapsed time
                elapsed_since_refill = now - self._last_refill
                refill_rate = self.max_requests / self.time_window
                self._tokens = min(
                    float(self.max_requests),
                    self._tokens + elapsed_since_refill * refill_rate
                )
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                # Calculate wait time for next token
                wait_time = (1.0 - self._tokens) / refill_rate

            # Check timeout before sleeping
            if self.max_wait_time is not None:
                total_waited = time.monotonic() - start_time
                if total_waited + wait_time > self.max_wait_time:
                    raise TokenAcquisitionTimeoutError(
                        waited=total_waited,
                        max_wait_time=self.max_wait_time,
                    )

            # Sleep outside the lock to allow other threads to proceed
            time.sleep(wait_time)

    @override
    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Delegate GET request without rate limiting.

        GET requests (typically polling) are not rate-limited as they
        usually don't count against API rate limits.

        Args:
            url: The full URL to request.
            headers: Additional headers to include.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response.
        """
        return self.delegate.get(url, headers, timeout)

    @override
    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Acquire a rate limit token, then delegate POST request.

        This method blocks until a token is available if the rate limit
        has been reached.

        Args:
            url: The full URL to request.
            data: JSON-serializable data to send in the request body.
            headers: Additional headers to include.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response.
        """
        self._acquire_token()
        return self.delegate.post(url, data, headers, timeout)


class AdaptiveRateLimitedHttpClient(HttpClient):
    """
    HTTP client decorator with adaptive rate limiting using AIMD algorithm.

    Extends rate limiting with:
    - AIMD algorithm to adapt rate based on server responses
    - Floor protection to prevent deadlock
    - Configurable timeout to prevent indefinite blocking

    When an HTTP 429 response is received, this client:
    1. Applies AIMD penalty (reduces effective rate)
    2. Raises requests.HTTPError for the caller/Retrying to handle

    This follows the pattern of Resilience4J, Polly, and AWS SDK where rate
    limiting and retry are separate concerns. Use this client with Retrying
    for complete 429 handling with backoff.

    Example:
        >>> from stkai._rate_limit import AdaptiveRateLimitedHttpClient
        >>> from stkai._http import StkCLIHttpClient
        >>> client = AdaptiveRateLimitedHttpClient(
        ...     delegate=StkCLIHttpClient(),
        ...     max_requests=100,
        ...     time_window=60.0,
        ...     min_rate_floor=0.1,  # Never below 10 req/min
        ...     max_wait_time=30.0,  # Give up after 30s waiting
        ... )

    Args:
        delegate: The underlying HTTP client to delegate requests to.
        max_requests: Maximum number of requests allowed in the time window.
        time_window: Time window in seconds for the rate limit.
        min_rate_floor: Minimum rate as fraction of max_requests (default: 0.1 = 10%).
        penalty_factor: Rate reduction factor on 429 (default: 0.3 = -30%).
        recovery_factor: Rate increase factor on success (default: 0.05 = +5%).
        max_wait_time: Maximum time in seconds to wait for a token. If None,
            waits indefinitely. Default is 30 seconds.

    Raises:
        TokenAcquisitionTimeoutError: If max_wait_time is exceeded while waiting for a token.
        requests.HTTPError: When server returns HTTP 429 (after AIMD penalty applied).
    """

    # Structural jitter applied to AIMD factors and sleep times.
    # ±20% desynchronizes processes sharing a quota, preventing
    # thundering herd effects and synchronized oscillations.
    _JITTER_FACTOR = 0.20

    def __init__(
        self,
        delegate: HttpClient,
        max_requests: int,
        time_window: float,
        min_rate_floor: float = 0.1,
        penalty_factor: float = 0.3,
        recovery_factor: float = 0.05,
        max_wait_time: float | None = 30.0,
    ):
        """
        Initialize the adaptive rate-limited HTTP client.

        Args:
            delegate: The underlying HTTP client to delegate requests to.
            max_requests: Maximum number of requests allowed in the time window.
            time_window: Time window in seconds for the rate limit.
            min_rate_floor: Minimum rate as fraction of max_requests (default: 0.1 = 10%).
            penalty_factor: Rate reduction factor on 429 (default: 0.3 = -30%).
            recovery_factor: Rate increase factor on success (default: 0.05 = +5%).
            max_wait_time: Maximum time in seconds to wait for a token.
                If None, waits indefinitely. Default is 30 seconds.

        Raises:
            AssertionError: If any parameter is invalid.
        """
        assert delegate is not None, "Delegate HTTP client is required."
        assert max_requests is not None, "max_requests cannot be None."
        assert max_requests > 0, "max_requests must be greater than 0."
        assert time_window is not None, "time_window cannot be None."
        assert time_window > 0, "time_window must be greater than 0."
        assert min_rate_floor is not None, "min_rate_floor cannot be None."
        assert 0 < min_rate_floor <= 1, "min_rate_floor must be between 0 (exclusive) and 1 (inclusive)."
        assert penalty_factor is not None, "penalty_factor cannot be None."
        assert 0 < penalty_factor < 1, "penalty_factor must be between 0 and 1 (exclusive)."
        assert recovery_factor is not None, "recovery_factor cannot be None."
        assert 0 < recovery_factor < 1, "recovery_factor must be between 0 and 1 (exclusive)."
        assert max_wait_time is None or max_wait_time > 0, "max_wait_time must be > 0 or None."

        self.delegate = delegate
        self.max_requests = max_requests
        self.time_window = time_window
        self.min_rate_floor = min_rate_floor
        self.penalty_factor = penalty_factor
        self.recovery_factor = recovery_factor
        self.max_wait_time = max_wait_time

        # Token bucket state (adaptive)
        self._effective_max = float(max_requests)
        self._min_effective = max_requests * min_rate_floor
        self._tokens = float(max_requests)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

        # Structural jitter for desynchronizing processes
        self._jitter = Jitter(factor=self._JITTER_FACTOR)

    def _acquire_token(self) -> None:
        """
        Acquire a token using adaptive effective_max.

        Uses Token Bucket algorithm with adaptive rate based on 429 responses.
        Raises TokenAcquisitionTimeoutError if max_wait_time is exceeded.

        Raises:
            TokenAcquisitionTimeoutError: If waiting exceeds max_wait_time.
        """
        start_time = time.monotonic()

        while True:
            with self._lock:
                now = time.monotonic()
                elapsed_since_refill = now - self._last_refill
                refill_rate = self._effective_max / self.time_window
                self._tokens = min(
                    self._effective_max,
                    self._tokens + elapsed_since_refill * refill_rate
                )
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                wait_time = (1.0 - self._tokens) / refill_rate

            # Check timeout before sleeping
            if self.max_wait_time is not None:
                total_waited = time.monotonic() - start_time
                if total_waited + wait_time > self.max_wait_time:
                    raise TokenAcquisitionTimeoutError(
                        waited=total_waited,
                        max_wait_time=self.max_wait_time,
                    )

            # Sleep with jitter to prevent thundering herd
            sleep_with_jitter(wait_time, jitter_factor=self._JITTER_FACTOR)

    def _on_success(self) -> None:
        """
        Additive increase after successful request.

        Gradually recovers the effective rate after successful requests,
        up to the original max_requests ceiling.

        Uses jittered recovery factor to desynchronize processes
        and prevent collective oscillations.
        """
        with self._lock:
            recovery = self.max_requests * self.recovery_factor * self._jitter
            self._effective_max = min(
                float(self.max_requests),
                self._effective_max + recovery
            )

    def _on_rate_limited(self) -> None:
        """
        Multiplicative decrease after receiving 429.

        Reduces the effective rate to adapt to server-side rate limits,
        but never below the configured floor.

        Uses jittered penalty factor to desynchronize processes
        and prevent collective oscillations.

        Also clamps _tokens to maintain Token Bucket invariant: tokens <= effective_max.
        Without this, after penalization the tokens could exceed the new effective_max,
        breaking the bucket's capacity constraint.
        """
        with self._lock:
            jittered_penalty = self.penalty_factor * self._jitter

            old_max = self._effective_max
            self._effective_max = max(
                self._min_effective,
                self._effective_max * (1.0 - jittered_penalty)
            )
            # Clamp tokens to maintain invariant: tokens <= effective_max
            self._tokens = min(self._tokens, self._effective_max)
            logger.warning(
                f"Rate limit adapted: effective_max reduced from {old_max:.1f} to {self._effective_max:.1f}"
            )

    @override
    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Delegate GET request without rate limiting.

        GET requests (typically polling) are not rate-limited as they
        usually don't count against API rate limits.

        Args:
            url: The full URL to request.
            headers: Additional headers to include.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response.
        """
        return self.delegate.get(url, headers, timeout)

    @override
    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Acquire token, delegate request, adapt rate based on response.

        This method:
        1. Acquires a rate limit token (blocking if necessary)
        2. Delegates the request to the underlying client
        3. On success: gradually increases the effective rate (AIMD recovery)
        4. On 429: reduces effective rate (AIMD penalty) and raises HTTPError

        The 429 handling follows the separation of concerns pattern:
        - Rate limiter: applies AIMD penalty and raises exception
        - Retrying: handles retry with Retry-After header support

        Args:
            url: The full URL to request.
            data: JSON-serializable data to send in the request body.
            headers: Additional headers to include.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response (non-429 responses only).

        Raises:
            ServerSideRateLimitError: When server returns HTTP 429.
            TokenAcquisitionTimeoutError: When max_wait_time is exceeded.
        """
        self._acquire_token()
        response = self.delegate.post(url, data, headers, timeout)

        if response.status_code == 429:
            self._on_rate_limited()
            raise ServerSideRateLimitError(response)

        self._on_success()
        return response


class CongestionControlledHttpClient(HttpClient):
    """
    Adaptive, best-effort HTTP client with congestion control semantics.

    MENTAL MODEL
    ------------
    This client is not a simple rate limiter. It behaves as a local,
    feedback-driven congestion controller inspired by TCP and the AWS SDK.

    For a detailed comparison with AWS SDK's adaptive retry mode, see:
        docs/internal/aws-sdk-comparison.md

    The system continuously balances three interacting signals:

    1. Rate (Token Bucket)
       -------------------
       A token bucket limits the *average* request rate over a time window.
       The effective bucket capacity (`_effective_max`) is adaptive and
       governed by an AIMD (Additive Increase / Multiplicative Decrease)
       algorithm.

       - On success: the effective rate increases slowly (additive recovery)
       - On HTTP 429: the effective rate decreases aggressively (multiplicative penalty)

       This allows the client to probe available capacity while reacting
       quickly to server-side throttling.

    2. Concurrency (In-flight Requests)
       --------------------------------
       A semaphore limits the number of concurrent in-flight requests.
       Concurrency starts conservatively and adapts based on observed latency.

       The key insight is:
           pressure = rate × latency

       High latency implies that the system is saturated even if no explicit
       rate limit has been hit yet. By adjusting concurrency based on latency,
       the client applies *preventive backpressure* instead of only reacting
       after receiving HTTP 429 responses.

    3. Latency (Feedback Signal)
       -------------------------
       Request latency is tracked using an EMA (EWMA), providing a stable,
       low-noise signal of system pressure.

       Latency is intentionally used as a first-class control signal:
       - rising latency → reduce concurrency
       - stable/low latency → cautiously increase concurrency

       This allows the client to avoid overload before server-side rate
       limiting triggers.

    THREADING AND CONSISTENCY MODEL
    -------------------------------
    The client is designed for multi-threaded and multi-process environments,
    but it does NOT attempt global coordination or strict synchronization.

    Important design choices:
    - Token accounting and AIMD state are protected by a lock
    - Semaphore operations are thread-safe by definition
    - Concurrency recomputation is intentionally not strictly thread-safe

    This system favors:
        eventual consistency
        over
        strong consistency

    Occasional overshoot or undershoot is expected and acceptable. The
    feedback loop (latency + 429 responses) continuously corrects the system.

    Avoiding heavy synchronization improves stability and throughput under
    contention.

    MULTI-PROCESS BEHAVIOR
    ---------------------
    Each process runs an independent controller with identical configuration
    but slightly different dynamics.

    Structural jitter (randomized recovery/penalty factors and probabilistic
    concurrency growth) ensures that multiple processes do not synchronize
    their control decisions, preventing collective oscillations and thundering
    herd effects.

    This is a deliberate "best-effort" strategy. No distributed quota sharing
    or cross-process coordination is attempted.

    ERROR HANDLING AND RETRY
    -----------------------
    This client intentionally separates concerns:
    - Rate limiting and adaptation are handled here
    - Retry behavior is expected to be handled by the caller

    On HTTP 429:
    - The effective rate is penalized immediately
    - A specific exception is raised
    - Retry logic (including Retry-After handling) is delegated upward

    This mirrors patterns used by libraries such as AWS SDK, Polly, and
    Resilience4J.

    SUMMARY
    -------
    This client is a self-tuning, feedback-driven controller designed to:
    - Prevent overload before it happens
    - React quickly when overload is detected
    - Remain stable under concurrency and partial failures
    - Behave reasonably in shared-quota, multi-process environments

    It prioritizes system stability, adaptability, and operational safety
    over rigid guarantees or maximal throughput.
    """

    # Structural jitter applied to AIMD factors (±20%).
    # Desynchronizes processes sharing a quota, preventing thundering
    # herd effects and synchronized oscillations.
    _JITTER_FACTOR = 0.20

    # Probability of increasing concurrency on each successful request.
    # Low probability (30%) ensures slow, cautious growth.
    _CONCURRENCY_GROWTH_PROBABILITY = 0.30

    def __init__(
        self,
        delegate: HttpClient,
        max_requests: int,
        time_window: float,
        min_rate_floor: float = 0.1,
        penalty_factor: float = 0.3,
        recovery_factor: float = 0.05,
        max_wait_time: float | None = 30.0,
        max_concurrency: int = 5,
        latency_alpha: float = 0.2,
    ):
        """
        Initialize the adaptive rate-limited HTTP client.

        All parameters are intentionally static configuration inputs.
        The system dynamically adapts its behavior at runtime using
        feedback (latency and HTTP 429 responses).

        Args:
            delegate: Underlying HTTP client responsible for actual I/O.
            max_requests: Upper bound for requests per time window.
            time_window: Duration (seconds) of the rate limit window.
            min_rate_floor: Minimum effective rate as a fraction of max_requests.
            penalty_factor: Multiplicative decrease applied on HTTP 429.
            recovery_factor: Additive increase applied on successful requests.
            max_wait_time: Maximum time to wait for a rate-limit token.
            max_concurrency: Upper bound for in-flight requests.
            latency_alpha: EMA smoothing factor for latency tracking.

        Raises:
            AssertionError: If any parameter is invalid.
        """
        assert delegate is not None, "Delegate HTTP client is required."
        assert max_requests is not None, "max_requests cannot be None."
        assert max_requests > 0, "max_requests must be greater than 0."
        assert time_window is not None, "time_window cannot be None."
        assert time_window > 0, "time_window must be greater than 0."
        assert min_rate_floor is not None, "min_rate_floor cannot be None."
        assert 0 < min_rate_floor <= 1, "min_rate_floor must be between 0 (exclusive) and 1 (inclusive)."
        assert penalty_factor is not None, "penalty_factor cannot be None."
        assert 0 < penalty_factor < 1, "penalty_factor must be between 0 and 1 (exclusive)."
        assert recovery_factor is not None, "recovery_factor cannot be None."
        assert 0 < recovery_factor < 1, "recovery_factor must be between 0 and 1 (exclusive)."
        assert max_wait_time is None or max_wait_time > 0, "max_wait_time must be > 0 or None."
        assert max_concurrency is not None, "max_concurrency cannot be None."
        assert max_concurrency >= 1, "max_concurrency must be at least 1."
        assert latency_alpha is not None, "latency_alpha cannot be None."
        assert 0 < latency_alpha < 1, "latency_alpha must be between 0 and 1 (exclusive)."

        self.delegate = delegate
        self.max_requests = max_requests
        self.time_window = time_window
        self.min_rate_floor = min_rate_floor
        self.penalty_factor = penalty_factor
        self.recovery_factor = recovery_factor
        self.max_wait_time = max_wait_time
        self.max_concurrency = max_concurrency

        # Token bucket state
        self._effective_max = float(max_requests)
        self._min_effective = max_requests * min_rate_floor
        self._tokens = float(max_requests)
        self._last_refill = time.monotonic()

        # Concurrency control (start conservatively)
        self._concurrency_limit = 1
        self._semaphore = threading.Semaphore(1)

        # Latency tracking (EMA)
        self._latency_ema: float | None = None
        self._latency_alpha = latency_alpha

        # Synchronization
        self._lock = threading.Lock()

        # Structural jitter for desynchronizing processes
        self._jitter = Jitter(factor=self._JITTER_FACTOR)

    # ------------------------------------------------------------------
    # Token Bucket
    # ------------------------------------------------------------------

    def _acquire_token(self) -> None:
        """
        Acquire a token from the adaptive token bucket.

        This method enforces the *average* request rate over time.
        It blocks until a token becomes available or until max_wait_time
        is exceeded.

        Token refill rate depends on `_effective_max`, which is continuously
        adjusted by AIMD feedback.
        """
        start = time.monotonic()

        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                refill_rate = self._effective_max / self.time_window

                self._tokens = min(
                    self._effective_max,
                    self._tokens + elapsed * refill_rate,
                )
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                wait_time = (1.0 - self._tokens) / refill_rate

            if self.max_wait_time is not None:
                waited = time.monotonic() - start
                if waited + wait_time > self.max_wait_time:
                    raise TokenAcquisitionTimeoutError(waited, self.max_wait_time)

            time.sleep(wait_time)

    # ------------------------------------------------------------------
    # Concurrency control
    # ------------------------------------------------------------------

    def _acquire_concurrency(self) -> None:
        """
        Acquire a concurrency slot.

        This limits the number of in-flight requests and acts as a
        preventive backpressure mechanism based on observed latency.
        """
        self._semaphore.acquire()

    def _release_concurrency(self) -> None:
        """
        Release a previously acquired concurrency slot.

        Always called in a `finally` block to avoid leakage even
        in the presence of exceptions.
        """
        self._semaphore.release()

    # ------------------------------------------------------------------
    # Latency tracking
    # ------------------------------------------------------------------

    def _record_latency(self, latency: float) -> None:
        """
        Record request latency using an Exponential Moving Average (EMA).

        EMA provides a low-noise approximation of system pressure,
        favoring recent samples while retaining historical stability.
        """
        with self._lock:
            if self._latency_ema is None:
                self._latency_ema = latency
            else:
                self._latency_ema = (
                    self._latency_alpha * latency
                    + (1.0 - self._latency_alpha) * self._latency_ema
                )

    # ------------------------------------------------------------------
    # AIMD reactions
    # ------------------------------------------------------------------

    def _on_success(self) -> None:
        """
        Apply additive recovery after a successful request.

        Recovery is intentionally slow and jittered to:
        - avoid overshoot
        - prevent synchronization across processes
        - probe available capacity gradually
        """
        with self._lock:
            recovery = self.max_requests * self.recovery_factor * self._jitter
            self._effective_max = min(
                float(self.max_requests),
                self._effective_max + recovery,
            )

    def _on_rate_limited(self) -> None:
        """
        Apply multiplicative penalty after receiving HTTP 429.

        Penalty is aggressive and immediate, reflecting a clear
        server-side signal of overload.
        """
        with self._lock:
            penalty = self.penalty_factor * self._jitter

            old = self._effective_max
            self._effective_max = max(
                self._min_effective,
                self._effective_max * (1.0 - penalty),
            )

            # Clamp tokens to maintain bucket invariant
            self._tokens = min(self._tokens, self._effective_max)

            logger.warning(
                "Rate limited: effective_max reduced from %.1f to %.1f",
                old,
                self._effective_max,
            )

    # ------------------------------------------------------------------
    # Adaptive concurrency
    # ------------------------------------------------------------------

    def _recompute_concurrency(self) -> None:
        """
        Recompute the desired concurrency level based on observed latency.

        NOTE ON THREAD SAFETY:
        ----------------------
        This method is intentionally NOT strictly thread-safe.

        Multiple threads may enter this method concurrently and observe or
        update `_concurrency_limit` at roughly the same time.

        This is acceptable and intentional for the following reasons:
        - `_concurrency_limit` is a soft control target, not a strict invariant
        - `threading.Semaphore` operations (acquire/release) are thread-safe
        - Occasional overshoot or undershoot is tolerated by the control loop
        - Latency feedback and AIMD corrections converge the system over time

        In other words, this method favors eventual consistency and low
        synchronization overhead over strong consistency, which is appropriate
        for adaptive congestion control algorithms.

        Adding a global lock here would increase contention and reduce stability
        under high concurrency without providing meaningful correctness gains.
        """
        if self._latency_ema is None:
            return

        rate_per_sec = self._effective_max / self.time_window
        target = rate_per_sec * self._latency_ema

        target = max(1, int(math.ceil(target)))
        target = min(target, self.max_concurrency)

        if target == self._concurrency_limit:
            return

        if target < self._concurrency_limit:
            # Shrink immediately
            shrink = self._concurrency_limit - target
            for _ in range(shrink):
                self._semaphore.acquire(blocking=False)
            self._concurrency_limit = target

        else:
            # Grow slowly and probabilistically to avoid synchronization
            if self._jitter.random() >= self._CONCURRENCY_GROWTH_PROBABILITY:
                return
            self._semaphore.release()
            self._concurrency_limit += 1

    # ------------------------------------------------------------------
    # Public POST method (original semantics preserved)
    # ------------------------------------------------------------------

    @override
    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Entry point for rate-limited POST requests.

        This method ties together all control loops:
        - token bucket (rate)
        - semaphore (concurrency)
        - latency measurement
        - AIMD feedback

        It represents a single control cycle of the system.
        """
        self._acquire_concurrency()
        start = time.monotonic()

        try:
            self._acquire_token()
            response = self.delegate.post(url, data, headers, timeout)

            latency = time.monotonic() - start
            self._record_latency(latency)

            if response.status_code == 429:
                self._on_rate_limited()
                self._recompute_concurrency()
                raise ServerSideRateLimitError(response)

            self._on_success()
            self._recompute_concurrency()
            return response

        finally:
            self._release_concurrency()

    @override
    def get(
            self,
            url: str,
            headers: dict[str, str] | None = None,
            timeout: int = 30,
    ) -> requests.Response:
        """
        Delegate GET request without rate limiting.

        GET requests (typically polling) are not rate-limited as they
        usually don't count against API rate limits.

        Args:
            url: The full URL to request.
            headers: Additional headers to include.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response.
        """
        return self.delegate.get(url, headers, timeout)
