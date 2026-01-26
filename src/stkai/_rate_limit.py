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
import threading
import time
from typing import Any, override

import requests

from stkai._http import HttpClient
from stkai._retry import RetryableError

logger = logging.getLogger(__name__)


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
        >>> # Limit to 10 requests per minute, give up after 60s waiting
        >>> client = TokenBucketRateLimitedHttpClient(
        ...     delegate=StkCLIHttpClient(),
        ...     max_requests=10,
        ...     time_window=60.0,
        ...     max_wait_time=60.0,
        ... )

    Args:
        delegate: The underlying HTTP client to delegate requests to.
        max_requests: Maximum number of requests allowed in the time window.
        time_window: Time window in seconds for the rate limit.
        max_wait_time: Maximum time in seconds to wait for a token. If None,
            waits indefinitely. Default is 60 seconds.

    Raises:
        TokenAcquisitionTimeoutError: If max_wait_time is exceeded while waiting for a token.
    """

    def __init__(
        self,
        delegate: HttpClient,
        max_requests: int,
        time_window: float,
        max_wait_time: float | None = 60.0,
    ):
        """
        Initialize the rate-limited HTTP client.

        Args:
            delegate: The underlying HTTP client to delegate requests to.
            max_requests: Maximum number of requests allowed in the time window.
            time_window: Time window in seconds for the rate limit.
            max_wait_time: Maximum time in seconds to wait for a token.
                If None, waits indefinitely. Default is 60 seconds.

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
        self._last_refill = time.time()
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
        start_time = time.time()

        while True:
            with self._lock:
                now = time.time()
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
                total_waited = time.time() - start_time
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
        ...     max_wait_time=60.0,  # Give up after 60s waiting
        ... )

    Args:
        delegate: The underlying HTTP client to delegate requests to.
        max_requests: Maximum number of requests allowed in the time window.
        time_window: Time window in seconds for the rate limit.
        min_rate_floor: Minimum rate as fraction of max_requests (default: 0.1 = 10%).
        penalty_factor: Rate reduction factor on 429 (default: 0.2 = -20%).
        recovery_factor: Rate increase factor on success (default: 0.01 = +1%).
        max_wait_time: Maximum time in seconds to wait for a token. If None,
            waits indefinitely. Default is 60 seconds.

    Raises:
        TokenAcquisitionTimeoutError: If max_wait_time is exceeded while waiting for a token.
        requests.HTTPError: When server returns HTTP 429 (after AIMD penalty applied).
    """

    def __init__(
        self,
        delegate: HttpClient,
        max_requests: int,
        time_window: float,
        min_rate_floor: float = 0.1,
        penalty_factor: float = 0.2,
        recovery_factor: float = 0.01,
        max_wait_time: float | None = 60.0,
    ):
        """
        Initialize the adaptive rate-limited HTTP client.

        Args:
            delegate: The underlying HTTP client to delegate requests to.
            max_requests: Maximum number of requests allowed in the time window.
            time_window: Time window in seconds for the rate limit.
            min_rate_floor: Minimum rate as fraction of max_requests (default: 0.1 = 10%).
            penalty_factor: Rate reduction factor on 429 (default: 0.2 = -20%).
            recovery_factor: Rate increase factor on success (default: 0.01 = +1%).
            max_wait_time: Maximum time in seconds to wait for a token.
                If None, waits indefinitely. Default is 60 seconds.

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
        self._last_refill = time.time()
        self._lock = threading.Lock()

    def _acquire_token(self) -> None:
        """
        Acquire a token using adaptive effective_max.

        Uses Token Bucket algorithm with adaptive rate based on 429 responses.
        Raises TokenAcquisitionTimeoutError if max_wait_time is exceeded.

        Raises:
            TokenAcquisitionTimeoutError: If waiting exceeds max_wait_time.
        """
        start_time = time.time()

        while True:
            with self._lock:
                now = time.time()
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
                total_waited = time.time() - start_time
                if total_waited + wait_time > self.max_wait_time:
                    raise TokenAcquisitionTimeoutError(
                        waited=total_waited,
                        max_wait_time=self.max_wait_time,
                    )

            time.sleep(wait_time)

    def _on_success(self) -> None:
        """
        Additive increase after successful request.

        Gradually recovers the effective rate after successful requests,
        up to the original max_requests ceiling.
        """
        with self._lock:
            recovery = self.max_requests * self.recovery_factor
            self._effective_max = min(
                float(self.max_requests),
                self._effective_max + recovery
            )

    def _on_rate_limited(self) -> None:
        """
        Multiplicative decrease after receiving 429.

        Reduces the effective rate to adapt to server-side rate limits,
        but never below the configured floor.

        Also clamps _tokens to maintain Token Bucket invariant: tokens <= effective_max.
        Without this, after penalization the tokens could exceed the new effective_max,
        breaking the bucket's capacity constraint.
        """
        with self._lock:
            old_max = self._effective_max
            self._effective_max = max(
                self._min_effective,
                self._effective_max * (1 - self.penalty_factor)
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
