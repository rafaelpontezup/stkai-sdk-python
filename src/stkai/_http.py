"""
Unified HTTP client abstraction for the stkai SDK.

This module provides a generic HTTP client interface inspired by popular SDKs
(OpenAI, Anthropic, Stripe) that can be used across all SDK components.

Available implementations:
    - EnvironmentAwareHttpClient: Auto-detects environment (CLI or standalone). Default.
    - StkCLIHttpClient: Uses StackSpot CLI (oscli) for authentication.
    - StandaloneHttpClient: Uses AuthProvider for standalone authentication.

For rate limiting, see the `_rate_limit` module.

Example (recommended - auto-detection):
    >>> from stkai._http import EnvironmentAwareHttpClient
    >>> client = EnvironmentAwareHttpClient()
    >>> response = client.post("https://api.example.com/v1/resource", data={"key": "value"})

Example (explicit CLI):
    >>> from stkai._http import StkCLIHttpClient
    >>> client = StkCLIHttpClient()
    >>> response = client.post("https://api.example.com/v1/resource", data={"key": "value"})
"""

import logging
import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, override

import requests

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from stkai._auth import AuthProvider


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
            use_cache=False, # disables client-side caching
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
            # Warn if credentials are also configured (they will be ignored)
            from stkai._config import STKAI

            if STKAI.config.auth.has_credentials():
                logger.warning(
                    "⚠️ Auth credentials detected (via env vars or configure) but running in CLI mode. "
                    "Authentication will be handled by oscli. Credentials will be ignored."
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

        # Lazy import to avoid circular dependency
        from stkai._rate_limit import (
            AdaptiveRateLimitedHttpClient,
            TokenBucketRateLimitedHttpClient,
        )

        if rl_config.strategy == "token_bucket":
            logger.debug(
                "EnvironmentAwareHttpClient: Applying token_bucket rate limiting "
                f"(max_requests={rl_config.max_requests}, time_window={rl_config.time_window}s)."
            )
            return TokenBucketRateLimitedHttpClient(
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
        from stkai._cli import StkCLI

        return StkCLI.is_available()

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
