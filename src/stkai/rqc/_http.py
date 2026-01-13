"""
HTTP client implementations for Remote Quick Command.

This module contains the RqcHttpClient abstract base class and concrete
implementations for making authorized HTTP requests to the StackSpot AI API.

Available implementations:
    - StkCLIRqcHttpClient: Uses StackSpot CLI for authentication.
    - StandaloneRqcHttpClient: Uses AuthProvider for standalone authentication.
    - RateLimitedHttpClient: Wrapper that adds rate limiting to any client.
    - AdaptiveRateLimitedHttpClient: Wrapper with adaptive rate limiting and 429 handling.
"""

import logging
import random
import threading
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, override

import requests

if TYPE_CHECKING:
    from stkai._auth import AuthProvider


class RqcHttpClient(ABC):
    """
    Abstract base class for RQC HTTP clients.

    Implement this class to provide custom HTTP client implementations
    for different authentication mechanisms or environments.

    See Also:
        StkCLIRqcHttpClient: Default implementation using StackSpot CLI credentials.
    """

    @abstractmethod
    def get_with_authorization(self, execution_id: str, timeout: int = 30) -> requests.Response:
        """
        Execute an authorized GET request to retrieve execution status.

        Args:
            execution_id: The execution ID to query.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response from the StackSpot AI API.
        """
        pass

    @abstractmethod
    def post_with_authorization(self, slug_name: str, data: dict[str, Any] | None = None, timeout: int = 20) -> requests.Response:
        """
        Execute an authorized POST request to create an execution.

        Args:
            slug_name: The Quick Command slug name to execute.
            data: The request payload to send.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response from the StackSpot AI API.
        """
        pass


class StkCLIRqcHttpClient(RqcHttpClient):
    """
    HTTP client implementation using StackSpot CLI for authorization.

    This client delegates authentication to the StackSpot CLI (oscli),
    which must be installed and logged in for this client to work.

    The CLI handles token management, refresh, and injection of
    authorization headers into HTTP requests.

    Note:
        Requires the `oscli` package to be installed and configured.
        Install via: pip install oscli
        Login via: stk login

    See Also:
        RqcHttpClient: Abstract base class defining the interface.
    """

    @override
    def get_with_authorization(self, execution_id: str, timeout: int = 30) -> requests.Response:
        """
        Retrieves the execution status from the StackSpot AI API.

        Args:
            execution_id: The execution ID to query.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response containing execution status and result.

        Raises:
            AssertionError: If execution_id is empty or timeout is invalid.
            requests.RequestException: If the HTTP request fails.
        """
        assert execution_id, "Execution ID can not be empty."
        assert timeout is not None, "Timeout can not be None."
        assert timeout > 0, "Timeout must be greater than 0."

        from oscli import __codebuddy_base_url__
        from oscli.core.http import get_with_authorization

        codebuddy_base_url = __codebuddy_base_url__
        nocache_param = random.randint(0, 1000000)
        url = f"{codebuddy_base_url}/v1/quick-commands/callback/{execution_id}?nocache={nocache_param}"
        headers = {
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }

        response: requests.Response = get_with_authorization(url=url, timeout=timeout, headers=headers)
        return response

    @override
    def post_with_authorization(self, slug_name: str, data: dict[str, Any] | None = None, timeout: int = 20) -> requests.Response:
        """
        Creates a new Quick Command execution on the StackSpot AI API.

        Args:
            slug_name: The Quick Command slug name to execute.
            data: The request payload containing input data.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response containing the execution ID.

        Raises:
            AssertionError: If slug_name is empty or timeout is invalid.
            requests.RequestException: If the HTTP request fails.
        """
        assert slug_name, "RQC slug-name can not be empty."
        assert timeout is not None, "Timeout can not be None."
        assert timeout > 0, "Timeout must be greater than 0."

        from oscli import __codebuddy_base_url__
        from oscli.core.http import post_with_authorization

        codebuddy_base_url = __codebuddy_base_url__
        url = f"{codebuddy_base_url}/v1/quick-commands/create-execution/{slug_name}"

        response: requests.Response = post_with_authorization(url=url, body=data, timeout=timeout)
        return response


class StandaloneRqcHttpClient(RqcHttpClient):
    """
    HTTP client implementation using AuthProvider for standalone authentication.

    This client uses an AuthProvider to obtain authorization tokens,
    enabling standalone operation without the StackSpot CLI.

    Use this client when:
    - You want to run without the StackSpot CLI dependency
    - You need to use client credentials directly
    - You're deploying to an environment without CLI access

    Example:
        >>> from stkai._auth import ClientCredentialsAuthProvider
        >>> from stkai.rqc._http import StandaloneRqcHttpClient
        >>>
        >>> auth = ClientCredentialsAuthProvider(
        ...     client_id="my-client-id",
        ...     client_secret="my-client-secret",
        ... )
        >>> client = StandaloneRqcHttpClient(auth_provider=auth)
        >>> rqc = RemoteQuickCommand("my-slug", http_client=client)

    Args:
        auth_provider: Provider for authorization tokens.
        base_url: Base URL for the RQC API.

    See Also:
        ClientCredentialsAuthProvider: OAuth2 client credentials implementation.
        RqcHttpClient: Abstract base class defining the interface.
    """

    DEFAULT_BASE_URL = "https://genai-code-buddy-api.stackspot.com"

    def __init__(
        self,
        auth_provider: "AuthProvider",
        base_url: str = DEFAULT_BASE_URL,
    ):
        """
        Initialize the standalone HTTP client.

        Args:
            auth_provider: Provider for authorization tokens.
            base_url: Base URL for the RQC API.

        Raises:
            AssertionError: If auth_provider is None.
        """
        from stkai._auth import AuthProvider

        assert auth_provider is not None, "auth_provider cannot be None"
        assert isinstance(auth_provider, AuthProvider), "auth_provider must be an AuthProvider instance"

        self._auth = auth_provider
        self._base_url = base_url.rstrip("/")

    @override
    def get_with_authorization(self, execution_id: str, timeout: int = 30) -> requests.Response:
        """
        Retrieves the execution status from the StackSpot AI API.

        Args:
            execution_id: The execution ID to query.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response containing execution status and result.

        Raises:
            AssertionError: If execution_id is empty or timeout is invalid.
            requests.RequestException: If the HTTP request fails.
            AuthenticationError: If unable to obtain authorization token.
        """
        assert execution_id, "Execution ID can not be empty."
        assert timeout is not None, "Timeout can not be None."
        assert timeout > 0, "Timeout must be greater than 0."

        nocache_param = random.randint(0, 1000000)
        url = f"{self._base_url}/v1/quick-commands/callback/{execution_id}?nocache={nocache_param}"

        return requests.get(
            url,
            headers={
                **self._auth.get_auth_headers(),
                "Cache-Control": "no-cache, no-store",
                "Pragma": "no-cache",
            },
            timeout=timeout,
        )

    @override
    def post_with_authorization(
        self, slug_name: str, data: dict[str, Any] | None = None, timeout: int = 20
    ) -> requests.Response:
        """
        Creates a new Quick Command execution on the StackSpot AI API.

        Args:
            slug_name: The Quick Command slug name to execute.
            data: The request payload containing input data.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response containing the execution ID.

        Raises:
            AssertionError: If slug_name is empty or timeout is invalid.
            requests.RequestException: If the HTTP request fails.
            AuthenticationError: If unable to obtain authorization token.
        """
        assert slug_name, "RQC slug-name can not be empty."
        assert timeout is not None, "Timeout can not be None."
        assert timeout > 0, "Timeout must be greater than 0."

        url = f"{self._base_url}/v1/quick-commands/create-execution/{slug_name}"

        return requests.post(
            url,
            json=data,
            headers=self._auth.get_auth_headers(),
            timeout=timeout,
        )


class RateLimitedHttpClient(RqcHttpClient):
    """
    HTTP client wrapper that applies rate limiting to requests.

    Uses the Token Bucket algorithm to limit the rate of requests.
    Only POST requests (create-execution) are rate-limited; GET requests
    (polling) pass through without limiting.

    This wrapper is thread-safe and can be used with execute_many().

    Example:
        >>> # Limit to 10 requests per minute
        >>> client = RateLimitedHttpClient(
        ...     delegate=StkCLIRqcHttpClient(),
        ...     max_requests=10,
        ...     time_window=60.0,
        ... )
        >>> rqc = RemoteQuickCommand(slug_name="my-rqc", http_client=client)

    Args:
        delegate: The underlying HTTP client to delegate requests to.
        max_requests: Maximum number of requests allowed in the time window.
        time_window: Time window in seconds for the rate limit.
    """

    def __init__(
        self,
        delegate: RqcHttpClient,
        max_requests: int,
        time_window: float,
    ):
        """
        Initialize the rate-limited HTTP client.

        Args:
            delegate: The underlying HTTP client to delegate requests to.
            max_requests: Maximum number of requests allowed in the time window.
            time_window: Time window in seconds for the rate limit.

        Raises:
            AssertionError: If any parameter is invalid.
        """
        assert delegate, "Delegate HTTP client is required."
        assert max_requests is not None, "max_requests can not be None."
        assert max_requests > 0, "max_requests must be greater than 0."
        assert time_window is not None, "time_window can not be None."
        assert time_window > 0, "time_window must be greater than 0."

        self.delegate = delegate
        self.max_requests = max_requests
        self.time_window = time_window

        # Token bucket state
        self._tokens = float(max_requests)
        self._last_refill = time.time()
        self._lock = threading.Lock()

    def _acquire_token(self) -> None:
        """
        Acquires a token, blocking if necessary until one is available.

        Uses Token Bucket algorithm:
        - Refills tokens based on elapsed time
        - Waits if no tokens are available
        """
        while True:
            with self._lock:
                now = time.time()
                # Refill tokens based on elapsed time
                elapsed = now - self._last_refill
                refill_rate = self.max_requests / self.time_window
                self._tokens = min(
                    float(self.max_requests),
                    self._tokens + elapsed * refill_rate
                )
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                # Calculate wait time for next token
                wait_time = (1.0 - self._tokens) / refill_rate

            # Sleep outside the lock to allow other threads to proceed
            time.sleep(wait_time)

    @override
    def get_with_authorization(self, execution_id: str, timeout: int = 30) -> requests.Response:
        """
        Delegates to underlying client without rate limiting.

        GET requests (polling) are not rate-limited as they typically
        don't count against API rate limits.

        Args:
            execution_id: The execution ID to query.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response from the StackSpot AI API.
        """
        return self.delegate.get_with_authorization(execution_id, timeout)

    @override
    def post_with_authorization(
        self, slug_name: str, data: dict[str, Any] | None = None, timeout: int = 20
    ) -> requests.Response:
        """
        Acquires a rate limit token, then delegates to underlying client.

        This method blocks until a token is available if the rate limit
        has been reached.

        Args:
            slug_name: The Quick Command slug name to execute.
            data: The request payload to send.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response from the StackSpot AI API.
        """
        self._acquire_token()
        return self.delegate.post_with_authorization(slug_name, data, timeout)


class AdaptiveRateLimitedHttpClient(RqcHttpClient):
    """
    HTTP client wrapper with adaptive rate limiting and automatic 429 handling.

    Extends rate limiting with:
    - Automatic retry on HTTP 429 (Too Many Requests)
    - Respects Retry-After header from server
    - AIMD algorithm to adapt rate based on server responses
    - Floor protection to prevent deadlock

    This is ideal for scenarios with multiple clients sharing the same rate limit
    quota, where the effective available rate is unpredictable.

    Example:
        >>> client = AdaptiveRateLimitedHttpClient(
        ...     delegate=StkCLIRqcHttpClient(),
        ...     max_requests=100,
        ...     time_window=60.0,
        ...     min_rate_floor=0.1,  # Never below 10 req/min
        ... )
        >>> rqc = RemoteQuickCommand(slug_name="my-rqc", http_client=client)

    Args:
        delegate: The underlying HTTP client to delegate requests to.
        max_requests: Maximum number of requests allowed in the time window.
        time_window: Time window in seconds for the rate limit.
        min_rate_floor: Minimum rate as fraction of max_requests (default: 0.1 = 10%).
        max_retries_on_429: Maximum retries when receiving 429 (default: 3).
        penalty_factor: Rate reduction factor on 429 (default: 0.2 = -20%).
        recovery_factor: Rate increase factor on success (default: 0.01 = +1%).
    """

    def __init__(
        self,
        delegate: RqcHttpClient,
        max_requests: int,
        time_window: float,
        min_rate_floor: float = 0.1,
        max_retries_on_429: int = 3,
        penalty_factor: float = 0.2,
        recovery_factor: float = 0.01,
    ):
        """
        Initialize the adaptive rate-limited HTTP client.

        Args:
            delegate: The underlying HTTP client to delegate requests to.
            max_requests: Maximum number of requests allowed in the time window.
            time_window: Time window in seconds for the rate limit.
            min_rate_floor: Minimum rate as fraction of max_requests (default: 0.1 = 10%).
            max_retries_on_429: Maximum retries when receiving 429 (default: 3).
            penalty_factor: Rate reduction factor on 429 (default: 0.2 = -20%).
            recovery_factor: Rate increase factor on success (default: 0.01 = +1%).

        Raises:
            AssertionError: If any parameter is invalid.
        """
        assert delegate, "Delegate HTTP client is required."
        assert max_requests is not None, "max_requests can not be None."
        assert max_requests > 0, "max_requests must be greater than 0."
        assert time_window is not None, "time_window can not be None."
        assert time_window > 0, "time_window must be greater than 0."
        assert min_rate_floor is not None, "min_rate_floor can not be None."
        assert 0 < min_rate_floor <= 1, "min_rate_floor must be between 0 (exclusive) and 1 (inclusive)."
        assert max_retries_on_429 is not None, "max_retries_on_429 can not be None."
        assert max_retries_on_429 >= 0, "max_retries_on_429 must be >= 0."
        assert penalty_factor is not None, "penalty_factor can not be None."
        assert 0 < penalty_factor < 1, "penalty_factor must be between 0 and 1 (exclusive)."
        assert recovery_factor is not None, "recovery_factor can not be None."
        assert 0 < recovery_factor < 1, "recovery_factor must be between 0 and 1 (exclusive)."

        self.delegate = delegate
        self.max_requests = max_requests
        self.time_window = time_window
        self.min_rate_floor = min_rate_floor
        self.max_retries_on_429 = max_retries_on_429
        self.penalty_factor = penalty_factor
        self.recovery_factor = recovery_factor

        # Token bucket state (adaptive)
        self._effective_max = float(max_requests)
        self._min_effective = max_requests * min_rate_floor
        self._tokens = float(max_requests)
        self._last_refill = time.time()
        self._lock = threading.Lock()

    @property
    def effective_max(self) -> float:
        """Returns the current effective maximum requests (for monitoring)."""
        with self._lock:
            return self._effective_max

    def _acquire_token(self) -> None:
        """
        Acquires a token using adaptive effective_max.

        Uses Token Bucket algorithm with adaptive rate based on 429 responses.
        """
        while True:
            with self._lock:
                now = time.time()
                elapsed = now - self._last_refill
                refill_rate = self._effective_max / self.time_window
                self._tokens = min(
                    self._effective_max,
                    self._tokens + elapsed * refill_rate
                )
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                wait_time = (1.0 - self._tokens) / refill_rate

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
        """
        with self._lock:
            old_max = self._effective_max
            self._effective_max = max(
                self._min_effective,
                self._effective_max * (1 - self.penalty_factor)
            )
            logging.warning(
                f"Rate limit adapted: effective_max reduced from {old_max:.1f} to {self._effective_max:.1f}"
            )

    @override
    def get_with_authorization(self, execution_id: str, timeout: int = 30) -> requests.Response:
        """
        Delegates to underlying client without rate limiting.

        GET requests (polling) are not rate-limited as they typically
        don't count against API rate limits.

        Args:
            execution_id: The execution ID to query.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response from the StackSpot AI API.
        """
        return self.delegate.get_with_authorization(execution_id, timeout)

    @override
    def post_with_authorization(
        self, slug_name: str, data: dict[str, Any] | None = None, timeout: int = 20
    ) -> requests.Response:
        """
        Acquires token, delegates request, handles 429 with retry and adaptation.

        This method:
        1. Acquires a rate limit token (blocking if necessary)
        2. Delegates the request to the underlying client
        3. On success: gradually increases the effective rate
        4. On 429: reduces effective rate and retries with backoff

        Args:
            slug_name: The Quick Command slug name to execute.
            data: The request payload to send.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response from the StackSpot AI API.
            May return a 429 response if max_retries_on_429 is exceeded.
        """
        last_response: requests.Response | None = None

        for attempt in range(self.max_retries_on_429 + 1):
            self._acquire_token()
            response = self.delegate.post_with_authorization(slug_name, data, timeout)

            if response.status_code != 429:
                self._on_success()
                return response

            # HTTP 429 - Rate limited by server
            last_response = response
            self._on_rate_limited()

            if attempt >= self.max_retries_on_429:
                break

            # Determine wait time from Retry-After header or calculate from rate
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    wait_time = float(retry_after)
                except ValueError:
                    # Retry-After might be a date string, fall back to calculated wait
                    wait_time = self.time_window / self._effective_max
            else:
                wait_time = self.time_window / self._effective_max

            logging.warning(
                f"Rate limited (429). Attempt {attempt + 1}/{self.max_retries_on_429 + 1}. "
                f"Waiting {wait_time:.1f}s before retry..."
            )
            time.sleep(wait_time)

        # Return last response (429) for caller to handle
        assert last_response is not None, "Expected at least one response from retry loop"
        return last_response
