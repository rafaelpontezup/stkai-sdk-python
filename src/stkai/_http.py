"""
Unified HTTP client abstraction for the stkai SDK.

This module provides a generic HTTP client interface inspired by popular SDKs
(OpenAI, Anthropic, Stripe) that can be used across all SDK components.

Available implementations:
    - EnvironmentAwareHttpClient: Auto-detects environment (CLI or standalone). Default.
    - StkCLIHttpClient: Uses StackSpot CLI (oscli) for authentication.
    - StandaloneHttpClient: Uses AuthProvider for standalone authentication.
    - RateLimitedHttpClient: Decorator that adds rate limiting (Token Bucket).
    - AdaptiveRateLimitedHttpClient: Decorator with adaptive rate limiting and 429 handling.

Example (recommended - auto-detection):
    >>> from stkai._http import EnvironmentAwareHttpClient
    >>> client = EnvironmentAwareHttpClient()
    >>> response = client.post("https://api.example.com/v1/resource", data={"key": "value"})

Example (explicit CLI):
    >>> from stkai._http import StkCLIHttpClient
    >>> client = StkCLIHttpClient()
    >>> response = client.post("https://api.example.com/v1/resource", data={"key": "value"})

For rate limiting:
    >>> from stkai._http import RateLimitedHttpClient, EnvironmentAwareHttpClient
    >>> client = RateLimitedHttpClient(
    ...     delegate=EnvironmentAwareHttpClient(),
    ...     max_requests=10,
    ...     time_window=60.0,
    ... )
"""

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, override

import requests

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from stkai._auth import AuthProvider


# =============================================================================
# Exceptions
# =============================================================================


class RateLimitTimeoutError(Exception):
    """
    Raised when rate limiter exceeds max_wait_time waiting for a token.

    This exception indicates that a thread waited too long to acquire
    a rate limit token and gave up. This prevents threads from blocking
    indefinitely when rate limits are very restrictive.

    Attributes:
        waited: Time in seconds the thread waited before giving up.
        max_wait_time: The configured maximum wait time.

    Example:
        >>> try:
        ...     client.post(url, data)
        ... except RateLimitTimeoutError as e:
        ...     print(f"Rate limit timeout after {e.waited:.1f}s")
    """

    def __init__(self, waited: float, max_wait_time: float):
        self.waited = waited
        self.max_wait_time = max_wait_time
        super().__init__(
            f"Rate limit timeout: waited {waited:.2f}s, max_wait_time={max_wait_time:.2f}s"
        )


# =============================================================================
# Abstract Base Class
# =============================================================================


class HttpClient(ABC):
    """
    Abstract base class for HTTP clients.

    This is the unified HTTP client interface for the stkai SDK.
    All HTTP operations in the SDK should use this interface.

    Implementations handle authentication and can be wrapped with
    decorators for rate limiting, retries, and other cross-cutting concerns.

    Example:
        >>> class MyHttpClient(HttpClient):
        ...     def get(self, url, headers=None, timeout=30):
        ...         return requests.get(url, headers=headers, timeout=timeout)
        ...     def post(self, url, data=None, headers=None, timeout=30):
        ...         return requests.post(url, json=data, headers=headers, timeout=timeout)
    """

    @abstractmethod
    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Execute an authenticated GET request.

        Args:
            url: The full URL to request.
            headers: Additional headers to include (merged with auth headers).
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response.

        Raises:
            requests.RequestException: If the HTTP request fails.
        """
        pass

    @abstractmethod
    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Execute an authenticated POST request with JSON body.

        Args:
            url: The full URL to request.
            data: JSON-serializable data to send in the request body.
            headers: Additional headers to include (merged with auth headers).
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response.

        Raises:
            requests.RequestException: If the HTTP request fails.
        """
        pass


# =============================================================================
# StackSpot CLI Implementation
# =============================================================================


class StkCLIHttpClient(HttpClient):
    """
    HTTP client using StackSpot CLI (oscli) for authentication.

    This client delegates authentication to the StackSpot CLI,
    which must be installed and logged in for this client to work.

    The CLI handles token management, refresh, and injection of
    authorization headers into HTTP requests.

    Note:
        Requires the `oscli` package to be installed and configured.
        Install via: pip install oscli
        Login via: stk login

    Example:
        >>> from stkai._http import StkCLIHttpClient
        >>> client = StkCLIHttpClient()
        >>> response = client.post("https://api.example.com/endpoint", data={"key": "value"})

    See Also:
        StandaloneHttpClient: Alternative that doesn't require oscli.
    """

    @override
    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Execute an authenticated GET request using oscli.

        Args:
            url: The full URL to request.
            headers: Additional headers to include.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response.

        Raises:
            AssertionError: If url is empty or timeout is invalid.
            requests.RequestException: If the HTTP request fails.
        """
        assert url, "URL cannot be empty."
        assert timeout is not None, "Timeout cannot be None."
        assert timeout > 0, "Timeout must be greater than 0."

        from oscli.core.http import get_with_authorization

        response: requests.Response = get_with_authorization(
            url=url,
            timeout=timeout,
            headers=headers,
        )
        return response

    @override
    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Execute an authenticated POST request using oscli.

        Args:
            url: The full URL to request.
            data: JSON-serializable data to send in the request body.
            headers: Additional headers to include.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response.

        Raises:
            AssertionError: If url is empty or timeout is invalid.
            requests.RequestException: If the HTTP request fails.
        """
        assert url, "URL cannot be empty."
        assert timeout is not None, "Timeout cannot be None."
        assert timeout > 0, "Timeout must be greater than 0."

        from oscli.core.http import post_with_authorization

        response: requests.Response = post_with_authorization(
            url=url,
            body=data,
            timeout=timeout,
            headers=headers,
        )
        return response


# =============================================================================
# Standalone Implementation
# =============================================================================


class StandaloneHttpClient(HttpClient):
    """
    HTTP client using AuthProvider for standalone authentication.

    This client uses an AuthProvider to obtain authorization tokens,
    enabling standalone operation without the StackSpot CLI.

    Use this client when:
    - You want to run without the StackSpot CLI dependency
    - You need to use client credentials directly
    - You're deploying to an environment without CLI access

    Example:
        >>> from stkai._auth import ClientCredentialsAuthProvider
        >>> from stkai._http import StandaloneHttpClient
        >>>
        >>> auth = ClientCredentialsAuthProvider(
        ...     client_id="my-client-id",
        ...     client_secret="my-client-secret",
        ... )
        >>> client = StandaloneHttpClient(auth_provider=auth)
        >>> response = client.post("https://api.example.com/endpoint", data={"key": "value"})

    Args:
        auth_provider: Provider for authorization tokens.

    See Also:
        ClientCredentialsAuthProvider: OAuth2 client credentials implementation.
        StkCLIHttpClient: Alternative that uses oscli for authentication.
    """

    def __init__(self, auth_provider: "AuthProvider"):
        """
        Initialize the standalone HTTP client.

        Args:
            auth_provider: Provider for authorization tokens.

        Raises:
            AssertionError: If auth_provider is None or invalid type.
        """
        from stkai._auth import AuthProvider

        assert auth_provider is not None, "auth_provider cannot be None"
        assert isinstance(auth_provider, AuthProvider), "auth_provider must be an AuthProvider instance"

        self._auth = auth_provider

    @override
    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Execute an authenticated GET request.

        Args:
            url: The full URL to request.
            headers: Additional headers to include.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response.

        Raises:
            AssertionError: If url is empty or timeout is invalid.
            requests.RequestException: If the HTTP request fails.
            AuthenticationError: If unable to obtain authorization token.
        """
        assert url, "URL cannot be empty."
        assert timeout is not None, "Timeout cannot be None."
        assert timeout > 0, "Timeout must be greater than 0."

        merged_headers = {**self._auth.get_auth_headers(), **(headers or {})}

        return requests.get(
            url,
            headers=merged_headers,
            timeout=timeout,
        )

    @override
    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Execute an authenticated POST request with JSON body.

        Args:
            url: The full URL to request.
            data: JSON-serializable data to send in the request body.
            headers: Additional headers to include.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response.

        Raises:
            AssertionError: If url is empty or timeout is invalid.
            requests.RequestException: If the HTTP request fails.
            AuthenticationError: If unable to obtain authorization token.
        """
        assert url, "URL cannot be empty."
        assert timeout is not None, "Timeout cannot be None."
        assert timeout > 0, "Timeout must be greater than 0."

        merged_headers = {**self._auth.get_auth_headers(), **(headers or {})}

        return requests.post(
            url,
            json=data,
            headers=merged_headers,
            timeout=timeout,
        )


# =============================================================================
# Environment-Aware Implementation
# =============================================================================


class EnvironmentAwareHttpClient(HttpClient):
    """
    Environment-aware HTTP client that automatically selects the appropriate implementation.

    This client detects the runtime environment and lazily creates the appropriate
    HTTP client implementation:

    1. If StackSpot CLI (oscli) is installed → uses StkCLIHttpClient
    2. If credentials are configured → uses StandaloneHttpClient
    3. Otherwise → raises ValueError with clear instructions

    The detection happens lazily on the first request, allowing configuration
    via `STKAI.configure()` after import.

    This implementation is thread-safe using double-checked locking pattern.

    Example:
        >>> from stkai._http import EnvironmentAwareHttpClient
        >>> client = EnvironmentAwareHttpClient()
        >>> # Automatically uses CLI or standalone based on environment
        >>> response = client.post("https://api.example.com/endpoint", data={"key": "value"})

    Note:
        CLI takes precedence over credentials if both are available.

    See Also:
        StkCLIHttpClient: Explicit CLI-based client.
        StandaloneHttpClient: Explicit standalone client.
    """

    def __init__(self) -> None:
        """Initialize the environment-aware HTTP client."""
        self._delegate: HttpClient | None = None
        self._lock = threading.Lock()

    def _get_delegate(self) -> HttpClient:
        """
        Get or create the delegate HTTP client.

        Uses double-checked locking for thread-safe lazy initialization.

        Returns:
            The appropriate HttpClient implementation for the current environment.

        Raises:
            ValueError: If no authentication method is available.
        """
        if self._delegate is None:
            with self._lock:
                if self._delegate is None:
                    self._delegate = self._create_delegate()
        return self._delegate

    def _create_delegate(self) -> HttpClient:
        """
        Create the appropriate HTTP client based on environment detection.

        Returns:
            StkCLIHttpClient if oscli is available, otherwise StandaloneHttpClient.
            Wrapped with rate limiting if configured via STKAI.config.rate_limit.

        Raises:
            ValueError: If no authentication method is available.
        """
        # 1. Create base client
        base_client = self._create_base_client()

        # 2. Apply rate limiting if configured
        return self._apply_rate_limiting(base_client)

    def _create_base_client(self) -> HttpClient:
        """
        Create the base HTTP client based on environment detection.

        Returns:
            StkCLIHttpClient if oscli is available, otherwise StandaloneHttpClient.

        Raises:
            ValueError: If no authentication method is available.
        """
        # 1. Try CLI first (has priority)
        if self._is_cli_available():
            logger.debug(
                "EnvironmentAwareHttpClient: StackSpot CLI (oscli) detected. "
                "Using StkCLIHttpClient."
            )
            return StkCLIHttpClient()

        # 2. Try standalone with credentials
        from stkai._auth import create_standalone_auth
        from stkai._config import STKAI

        if STKAI.config.auth.has_credentials():
            logger.debug(
                "EnvironmentAwareHttpClient: Client credentials detected. "
                "Using StandaloneHttpClient."
            )
            auth = create_standalone_auth()
            return StandaloneHttpClient(auth_provider=auth)

        # 3. No valid configuration
        logger.debug(
            "EnvironmentAwareHttpClient: No authentication method available. "
            "Neither oscli nor client credentials found."
        )
        raise ValueError(
            "No authentication method available. Either:\n"
            "  1. Install and login to StackSpot CLI: pip install oscli && stk login\n"
            "  2. Set credentials via environment variables:\n"
            "     STKAI_AUTH_CLIENT_ID and STKAI_AUTH_CLIENT_SECRET\n"
            "  3. Call STKAI.configure(auth={...}) at startup"
        )

    def _apply_rate_limiting(self, client: HttpClient) -> HttpClient:
        """
        Wrap the client with rate limiting if configured.

        Args:
            client: The base HTTP client to potentially wrap.

        Returns:
            The client wrapped with rate limiting, or the original client
            if rate limiting is not enabled.

        Raises:
            ValueError: If an unknown rate limit strategy is configured.
        """
        from stkai._config import STKAI

        rl_config = STKAI.config.rate_limit

        if not rl_config.enabled:
            return client

        if rl_config.strategy == "token_bucket":
            logger.debug(
                "EnvironmentAwareHttpClient: Applying token_bucket rate limiting "
                f"(max_requests={rl_config.max_requests}, time_window={rl_config.time_window}s)."
            )
            return RateLimitedHttpClient(
                delegate=client,
                max_requests=rl_config.max_requests,
                time_window=rl_config.time_window,
                max_wait_time=rl_config.max_wait_time,
            )
        elif rl_config.strategy == "adaptive":
            logger.debug(
                "EnvironmentAwareHttpClient: Applying adaptive rate limiting "
                f"(max_requests={rl_config.max_requests}, time_window={rl_config.time_window}s)."
            )
            return AdaptiveRateLimitedHttpClient(
                delegate=client,
                max_requests=rl_config.max_requests,
                time_window=rl_config.time_window,
                max_wait_time=rl_config.max_wait_time,
                min_rate_floor=rl_config.min_rate_floor,
                max_retries_on_429=rl_config.max_retries_on_429,
                penalty_factor=rl_config.penalty_factor,
                recovery_factor=rl_config.recovery_factor,
            )
        else:
            raise ValueError(
                f"Unknown rate limit strategy: {rl_config.strategy}. "
                f"Valid strategies are: 'token_bucket', 'adaptive'."
            )

    def _is_cli_available(self) -> bool:
        """
        Check if StackSpot CLI (oscli) is available.

        Returns:
            True if oscli can be imported, False otherwise.
        """
        try:
            import oscli  # noqa: F401

            return True
        except ImportError:
            return False

    @override
    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Delegate GET request to the appropriate HTTP client.

        Args:
            url: The full URL to request.
            headers: Additional headers to include.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response.
        """
        return self._get_delegate().get(url, headers, timeout)

    @override
    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Delegate POST request to the appropriate HTTP client.

        Args:
            url: The full URL to request.
            data: JSON-serializable data to send in the request body.
            headers: Additional headers to include.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response.
        """
        return self._get_delegate().post(url, data, headers, timeout)


# =============================================================================
# Rate-Limited Decorators
# =============================================================================


class RateLimitedHttpClient(HttpClient):
    """
    HTTP client decorator that applies rate limiting to requests.

    Uses the Token Bucket algorithm to limit the rate of requests.
    Only POST requests are rate-limited; GET requests (typically polling)
    pass through without limiting.

    This decorator is thread-safe and can be used with concurrent requests.

    Example:
        >>> from stkai._http import RateLimitedHttpClient, StkCLIHttpClient
        >>> # Limit to 10 requests per minute, give up after 60s waiting
        >>> client = RateLimitedHttpClient(
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
        RateLimitTimeoutError: If max_wait_time is exceeded while waiting for a token.
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
        - Raises RateLimitTimeoutError if max_wait_time is exceeded

        Raises:
            RateLimitTimeoutError: If waiting exceeds max_wait_time.
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
                    raise RateLimitTimeoutError(
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
    HTTP client decorator with adaptive rate limiting and automatic 429 handling.

    Extends rate limiting with:
    - Automatic retry on HTTP 429 (Too Many Requests)
    - Respects Retry-After header from server
    - AIMD algorithm to adapt rate based on server responses
    - Floor protection to prevent deadlock
    - Configurable timeout to prevent indefinite blocking

    This is ideal for scenarios with multiple clients sharing the same rate limit
    quota, where the effective available rate is unpredictable.

    Example:
        >>> from stkai._http import AdaptiveRateLimitedHttpClient, StkCLIHttpClient
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
        max_retries_on_429: Maximum retries when receiving 429 (default: 3).
        penalty_factor: Rate reduction factor on 429 (default: 0.2 = -20%).
        recovery_factor: Rate increase factor on success (default: 0.01 = +1%).
        max_wait_time: Maximum time in seconds to wait for a token. If None,
            waits indefinitely. Default is 60 seconds.

    Raises:
        RateLimitTimeoutError: If max_wait_time is exceeded while waiting for a token.
    """

    def __init__(
        self,
        delegate: HttpClient,
        max_requests: int,
        time_window: float,
        min_rate_floor: float = 0.1,
        max_retries_on_429: int = 3,
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
            max_retries_on_429: Maximum retries when receiving 429 (default: 3).
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
        assert max_retries_on_429 is not None, "max_retries_on_429 cannot be None."
        assert max_retries_on_429 >= 0, "max_retries_on_429 must be >= 0."
        assert penalty_factor is not None, "penalty_factor cannot be None."
        assert 0 < penalty_factor < 1, "penalty_factor must be between 0 and 1 (exclusive)."
        assert recovery_factor is not None, "recovery_factor cannot be None."
        assert 0 < recovery_factor < 1, "recovery_factor must be between 0 and 1 (exclusive)."
        assert max_wait_time is None or max_wait_time > 0, "max_wait_time must be > 0 or None."

        self.delegate = delegate
        self.max_requests = max_requests
        self.time_window = time_window
        self.min_rate_floor = min_rate_floor
        self.max_retries_on_429 = max_retries_on_429
        self.penalty_factor = penalty_factor
        self.recovery_factor = recovery_factor
        self.max_wait_time = max_wait_time

        # Token bucket state (adaptive)
        self._effective_max = float(max_requests)
        self._min_effective = max_requests * min_rate_floor
        self._tokens = float(max_requests)
        self._last_refill = time.time()
        self._lock = threading.Lock()

    @property
    def effective_max(self) -> float:
        """Return the current effective maximum requests (for monitoring)."""
        with self._lock:
            return self._effective_max

    def _acquire_token(self) -> None:
        """
        Acquire a token using adaptive effective_max.

        Uses Token Bucket algorithm with adaptive rate based on 429 responses.
        Raises RateLimitTimeoutError if max_wait_time is exceeded.

        Raises:
            RateLimitTimeoutError: If waiting exceeds max_wait_time.
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
                    raise RateLimitTimeoutError(
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
        """
        with self._lock:
            old_max = self._effective_max
            self._effective_max = max(
                self._min_effective,
                self._effective_max * (1 - self.penalty_factor)
            )
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
        Acquire token, delegate request, handle 429 with retry and adaptation.

        This method:
        1. Acquires a rate limit token (blocking if necessary)
        2. Delegates the request to the underlying client
        3. On success: gradually increases the effective rate
        4. On 429: reduces effective rate and retries with backoff

        Args:
            url: The full URL to request.
            data: JSON-serializable data to send in the request body.
            headers: Additional headers to include.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response.
            May return a 429 response if max_retries_on_429 is exceeded.
        """
        last_response: requests.Response | None = None

        for attempt in range(self.max_retries_on_429 + 1):
            self._acquire_token()
            response = self.delegate.post(url, data, headers, timeout)

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

            logger.warning(
                f"Rate limited (429). Attempt {attempt + 1}/{self.max_retries_on_429 + 1}. "
                f"Waiting {wait_time:.1f}s before retry..."
            )
            time.sleep(wait_time)

        # Return last response (429) for caller to handle
        assert last_response is not None, "Expected at least one response from retry loop"
        return last_response
