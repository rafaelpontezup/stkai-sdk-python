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
        >>> # Limit to 10 requests per minute, give up after 45s waiting
        >>> client = TokenBucketRateLimitedHttpClient(
        ...     delegate=StkCLIHttpClient(),
        ...     max_requests=10,
        ...     time_window=60.0,
        ...     max_wait_time=45.0,
        ... )

    Args:
        delegate: The underlying HTTP client to delegate requests to.
        max_requests: Maximum number of requests allowed in the time window.
        time_window: Time window in seconds for the rate limit.
        max_wait_time: Maximum time in seconds to wait for a token. If None,
            waits indefinitely. Default is 45 seconds.

    Raises:
        TokenAcquisitionTimeoutError: If max_wait_time is exceeded while waiting for a token.
    """

    def __init__(
        self,
        delegate: HttpClient,
        max_requests: int,
        time_window: float,
        max_wait_time: float | None = 45.0,
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

    @override
    def post_stream(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """Acquire a rate limit token, then delegate streaming POST request."""
        self._acquire_token()
        return self.delegate.post_stream(url, data, headers, timeout)


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
        ...     max_wait_time=45.0,  # Give up after 45s waiting
        ... )

    Args:
        delegate: The underlying HTTP client to delegate requests to.
        max_requests: Maximum number of requests allowed in the time window.
        time_window: Time window in seconds for the rate limit.
        min_rate_floor: Minimum rate as fraction of max_requests (default: 0.1 = 10%).
        penalty_factor: Rate reduction factor on 429 (default: 0.3 = -30%).
        recovery_factor: Rate increase factor on success (default: 0.05 = +5%).
        max_wait_time: Maximum time in seconds to wait for a token. If None,
            waits indefinitely. Default is 45 seconds.

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
        max_wait_time: float | None = 45.0,
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

    @override
    def post_stream(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """Acquire token, delegate streaming POST, adapt rate based on response."""
        self._acquire_token()
        response = self.delegate.post_stream(url, data, headers, timeout)

        if response.status_code == 429:
            self._on_rate_limited()
            raise ServerSideRateLimitError(response)

        self._on_success()
        return response


class CongestionAwareHttpClient(HttpClient):
    """
    (EXPERIMENTAL) HTTP client decorator with latency-based concurrency control.

    WARNING: EXPERIMENTAL
    ---------------------
    This component is experimental and may not provide significant benefits
    when combined with AdaptiveRateLimitedHttpClient (AIMD). In most scenarios,
    the AIMD rate limiter reacts to 429 responses faster than latency-based
    detection can detect congestion.

    WHEN TO CONSIDER THIS
    ---------------------
    This decorator MAY be useful in specific scenarios:

    1. Server degrades gracefully (latency increases before 429s):
       Some servers slow down under load before rejecting requests.
       In this case, latency-based detection can reduce concurrency
       proactively, before 429s are returned.

    2. No rate limiting (standalone concurrency control):
       If you don't need rate limiting but want to protect against
       overwhelming a slow server, this can be used alone.

    3. Long-running requests (Agent chat, not RQC):
       For requests that take 10-30 seconds (like Agent::chat()),
       concurrency control may be more relevant than rate limiting.

    MENTAL MODEL
    ------------
    This is a pure concurrency controller that uses Little's Law for
    proactive backpressure. It does NOT do rate limiting - that's the
    responsibility of a wrapping rate limiter.

    The intended composition is:
        Request → RateLimiter (RATE) → CongestionAwareHttpClient (CONCURRENCY) → HttpClient

    This separation of concerns means:
    - The rate limiter controls HOW FAST requests are sent
    - This client controls HOW MANY requests are in-flight simultaneously

    LITTLE'S LAW
    ------------
    Uses L = λW (Little's Law) to estimate system pressure:

        pressure = throughput × latency

    Where:
    - throughput = observed requests per second
    - latency = smoothed response time (EMA)
    - pressure = estimated concurrent requests "wanting" to be in-flight

    When pressure exceeds the threshold, we reduce concurrency proactively
    (before 429s), providing preventive backpressure.

    EXAMPLE USAGE
    -------------
    >>> from stkai._http import StkCLIHttpClient
    >>> from stkai._rate_limit import CongestionAwareHttpClient, AdaptiveRateLimitedHttpClient
    >>>
    >>> # Layer 1: Base HTTP client
    >>> base = StkCLIHttpClient()
    >>>
    >>> # Layer 2: Concurrency control (inner)
    >>> congestion = CongestionAwareHttpClient(
    ...     delegate=base,
    ...     max_concurrency=8,
    ...     pressure_threshold=2.0,
    ... )
    >>>
    >>> # Layer 3: Rate limiting (outer) - optional
    >>> client = AdaptiveRateLimitedHttpClient(
    ...     delegate=congestion,
    ...     max_requests=100,
    ...     time_window=60.0,
    ... )

    Args:
        delegate: The underlying HTTP client to delegate requests to.
        max_concurrency: Maximum concurrent in-flight requests.
        pressure_threshold: Little's Law pressure threshold above which
            we reduce concurrency. Lower = more conservative.
        latency_alpha: EMA smoothing factor for latency (default: 0.2).
        growth_probability: Probability of growing concurrency on low
            pressure (default: 0.3 = 30% chance per request).
    """

    # Probability of increasing concurrency on each successful request.
    # Low probability ensures slow, cautious growth.
    _DEFAULT_GROWTH_PROBABILITY = 0.30

    def __init__(
        self,
        delegate: HttpClient,
        max_concurrency: int = 8,
        pressure_threshold: float = 2.0,
        latency_alpha: float = 0.2,
        growth_probability: float | None = None,
    ):
        """
        Initialize the congestion-aware HTTP client.

        Args:
            delegate: The underlying HTTP client to delegate requests to.
            max_concurrency: Maximum concurrent in-flight requests (default: 8).
            pressure_threshold: Little's Law pressure threshold (default: 2.0).
            latency_alpha: EMA smoothing factor for latency (default: 0.2).
            growth_probability: Probability of growing concurrency when
                pressure is low. If None, uses default (0.30).

        Raises:
            AssertionError: If any parameter is invalid.
        """
        assert delegate is not None, "Delegate HTTP client is required."
        assert max_concurrency >= 1, "max_concurrency must be at least 1."
        assert pressure_threshold > 0, "pressure_threshold must be positive."
        assert 0 < latency_alpha < 1, "latency_alpha must be between 0 and 1."

        self.delegate = delegate
        self.max_concurrency = max_concurrency
        self.pressure_threshold = pressure_threshold
        self._latency_alpha = latency_alpha
        self._growth_probability = growth_probability or self._DEFAULT_GROWTH_PROBABILITY

        # Concurrency control (start at max - optimistic)
        self._concurrency_limit = max_concurrency
        self._semaphore = threading.Semaphore(max_concurrency)

        # Latency tracking (EMA)
        self._latency_ema: float | None = None

        # Throughput tracking (requests per second)
        self._request_count = 0
        self._throughput_window_start = time.monotonic()
        self._throughput: float = 0.0

        # Lock for state updates
        self._lock = threading.Lock()

        # Jitter for probabilistic growth
        self._jitter = Jitter(factor=0.20)

    def _acquire_concurrency(self) -> None:
        """Acquire a concurrency slot (blocks if at limit)."""
        self._semaphore.acquire()

    def _release_concurrency(self) -> None:
        """Release a concurrency slot."""
        self._semaphore.release()

    def _record_latency(self, latency: float) -> None:
        """
        Record request latency using EMA and update throughput estimate.

        Args:
            latency: Request latency in seconds.
        """
        with self._lock:
            # Update latency EMA
            if self._latency_ema is None:
                self._latency_ema = latency
            else:
                self._latency_ema = (
                    self._latency_alpha * latency
                    + (1.0 - self._latency_alpha) * self._latency_ema
                )

            # Update throughput estimate (sliding window)
            now = time.monotonic()
            self._request_count += 1
            elapsed = now - self._throughput_window_start

            # Reset window every 5 seconds for responsive throughput
            if elapsed >= 5.0:
                self._throughput = self._request_count / elapsed
                self._request_count = 0
                self._throughput_window_start = now

    def _calculate_pressure(self) -> float:
        """
        Calculate pressure using Little's Law (L = λW).

        Returns:
            Estimated number of concurrent requests "wanting" to be in-flight.
            Returns 0.0 if not enough data yet.
        """
        if self._latency_ema is None or self._throughput <= 0:
            return 0.0

        # Little's Law: L = λW
        return self._throughput * self._latency_ema

    def _adjust_concurrency(self) -> None:
        """
        Adjust concurrency limit based on pressure.

        - High pressure → shrink concurrency (backpressure)
        - Low pressure → cautiously grow concurrency (probe capacity)
        """
        pressure = self._calculate_pressure()

        if pressure <= 0:
            return

        if pressure > self.pressure_threshold:
            # High pressure → shrink immediately
            if self._concurrency_limit > 1:
                # Try to acquire (shrink) - non-blocking
                acquired = self._semaphore.acquire(blocking=False)
                if acquired:
                    self._concurrency_limit -= 1
                    logger.debug(
                        f"Congestion: high pressure ({pressure:.2f}), "
                        f"reduced concurrency to {self._concurrency_limit}"
                    )
        else:
            # Low pressure → grow slowly (probabilistic)
            if self._concurrency_limit < self.max_concurrency:
                if self._jitter.random() < self._growth_probability:
                    self._semaphore.release()
                    self._concurrency_limit += 1
                    logger.debug(
                        f"Congestion: low pressure ({pressure:.2f}), "
                        f"increased concurrency to {self._concurrency_limit}"
                    )

    @override
    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Delegate GET request without concurrency control.

        GET requests (typically polling) pass through directly.

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
        Execute POST with concurrency control.

        This method:
        1. Acquires a concurrency slot (blocks if at limit)
        2. Delegates the request
        3. Records latency for pressure calculation
        4. Adjusts concurrency based on pressure
        5. Releases the concurrency slot

        Args:
            url: The full URL to request.
            data: JSON-serializable data to send.
            headers: Additional headers to include.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response.
        """
        self._acquire_concurrency()
        start = time.monotonic()

        try:
            response = self.delegate.post(url, data, headers, timeout)

            # Only record latency for successful responses
            # 429s are fast rejections that don't reflect server processing
            if response.status_code != 429:
                latency = time.monotonic() - start
                self._record_latency(latency)
                self._adjust_concurrency()

            return response

        finally:
            self._release_concurrency()

    @override
    def post_stream(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """Execute streaming POST with concurrency control."""
        self._acquire_concurrency()
        start = time.monotonic()

        try:
            response = self.delegate.post_stream(url, data, headers, timeout)

            if response.status_code != 429:
                latency = time.monotonic() - start
                self._record_latency(latency)
                self._adjust_concurrency()

            return response

        finally:
            self._release_concurrency()
