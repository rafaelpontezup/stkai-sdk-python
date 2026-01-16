"""
Authentication providers for the stkai SDK.

This module provides authentication abstractions that can be used with
HTTP clients to authenticate requests to StackSpot AI APIs.

The main classes are:
- AuthProvider: Abstract base class for authentication providers.
- ClientCredentialsAuthProvider: OAuth2 client credentials flow implementation.

Example:
    >>> from stkai._auth import ClientCredentialsAuthProvider
    >>> auth = ClientCredentialsAuthProvider(
    ...     client_id="my-client-id",
    ...     client_secret="my-client-secret",
    ... )
    >>> headers = auth.get_auth_headers()
    >>> # {"Authorization": "Bearer eyJ..."}
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from stkai._config import AuthConfig


# =============================================================================
# Exceptions
# =============================================================================


class AuthenticationError(Exception):
    """
    Raised when authentication fails.

    This exception is raised when the authentication provider fails to
    obtain or refresh an access token.

    Attributes:
        message: Description of the authentication failure.
        cause: The underlying exception that caused the failure, if any.

    Example:
        >>> try:
        ...     token = auth.get_access_token()
        ... except AuthenticationError as e:
        ...     print(f"Auth failed: {e}")
    """

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.message = message
        self.cause = cause


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class TokenInfo:
    """
    Token with expiration metadata.

    Attributes:
        access_token: The OAuth2 access token.
        expires_at: Unix timestamp when the token expires.
    """

    access_token: str
    expires_at: float


# =============================================================================
# Abstract Base Class
# =============================================================================


class AuthProvider(ABC):
    """
    Abstract base class for authentication providers.

    Implementations are responsible for obtaining and managing access tokens.
    All implementations must be thread-safe.

    Example:
        >>> class MyAuthProvider(AuthProvider):
        ...     def get_access_token(self) -> str:
        ...         return "my-token"
        ...
        >>> auth = MyAuthProvider()
        >>> headers = auth.get_auth_headers()
        >>> # {"Authorization": "Bearer my-token"}
    """

    @abstractmethod
    def get_access_token(self) -> str:
        """
        Obtain a valid access token.

        Returns:
            Access token string (without "Bearer" prefix).

        Raises:
            AuthenticationError: If unable to obtain a valid token.
        """
        pass

    def get_auth_headers(self) -> dict[str, str]:
        """
        Return authorization headers for HTTP requests.

        Returns:
            Dict with Authorization header containing Bearer token.

        Example:
            >>> headers = auth.get_auth_headers()
            >>> # {"Authorization": "Bearer eyJ..."}
        """
        return {"Authorization": f"Bearer {self.get_access_token()}"}


# =============================================================================
# Implementations
# =============================================================================


class ClientCredentialsAuthProvider(AuthProvider):
    """
    OAuth2 Client Credentials flow for StackSpot.

    This provider implements the OAuth2 client credentials grant type,
    which is used for machine-to-machine authentication.

    Features:
        - Token caching: Avoids unnecessary token requests.
        - Auto-refresh: Automatically refreshes tokens before expiration.
        - Thread-safe: Safe for use across multiple threads.

    Attributes:
        DEFAULT_TOKEN_URL: Default StackSpot OAuth2 token endpoint.
        DEFAULT_REFRESH_MARGIN: Seconds before expiration to refresh (60s).

    Example:
        >>> auth = ClientCredentialsAuthProvider(
        ...     client_id="my-client-id",
        ...     client_secret="my-client-secret",
        ... )
        >>> headers = auth.get_auth_headers()
        >>> # {"Authorization": "Bearer eyJ..."}

    Args:
        client_id: StackSpot client ID.
        client_secret: StackSpot client secret.
        token_url: OAuth2 token endpoint URL.
        refresh_margin: Seconds before expiration to trigger refresh.
    """

    DEFAULT_TOKEN_URL = "https://idm.stackspot.com/stackspot-dev/oidc/oauth/token"
    DEFAULT_REFRESH_MARGIN = 60  # Refresh 1 min before expiration

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str = DEFAULT_TOKEN_URL,
        refresh_margin: int = DEFAULT_REFRESH_MARGIN,
    ):
        assert client_id, "client_id cannot be empty"
        assert client_secret, "client_secret cannot be empty"

        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url
        self._refresh_margin = refresh_margin

        self._token: TokenInfo | None = None
        self._lock = threading.Lock()

    def get_access_token(self) -> str:
        """
        Obtain a valid access token, fetching a new one if necessary.

        This method is thread-safe. If the current token is valid (not expired
        and not within the refresh margin), it returns the cached token.
        Otherwise, it fetches a new token from the OAuth2 endpoint.

        Returns:
            Valid access token string.

        Raises:
            AuthenticationError: If unable to obtain a valid token.
        """
        with self._lock:
            if self._is_token_valid():
                assert self._token is not None  # for type checker
                return self._token.access_token

            self._token = self._fetch_new_token()
            return self._token.access_token

    def _is_token_valid(self) -> bool:
        """Check if current token exists and is not near expiration."""
        if self._token is None:
            return False
        return time.time() < (self._token.expires_at - self._refresh_margin)

    def _fetch_new_token(self) -> TokenInfo:
        """
        Fetch a new token from the OAuth2 endpoint.

        Returns:
            TokenInfo with the new access token and expiration time.

        Raises:
            AuthenticationError: If the token request fails.
        """
        try:
            response = requests.post(
                self._token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            expires_in = data.get("expires_in", 1199)

            return TokenInfo(
                access_token=data["access_token"],
                expires_at=time.time() + expires_in,
            )

        except requests.HTTPError as e:
            raise AuthenticationError(
                f"Failed to obtain access token (HTTP {e.response.status_code}): {e}",
                cause=e,
            ) from e
        except requests.RequestException as e:
            raise AuthenticationError(
                f"Failed to obtain access token: {e}",
                cause=e,
            ) from e
        except KeyError as e:
            raise AuthenticationError(
                f"Invalid token response: missing '{e}' field",
                cause=e,
            ) from e


# =============================================================================
# Helper Functions
# =============================================================================


def create_standalone_auth(config: AuthConfig | None = None) -> ClientCredentialsAuthProvider:
    """
    Create a ClientCredentialsAuthProvider from configuration.

    This helper function creates an auth provider using credentials from
    the provided config or from the global STKAI.config.

    Args:
        config: Optional AuthConfig with credentials. If None, uses
            STKAI.config.auth from global configuration.

    Returns:
        Configured ClientCredentialsAuthProvider instance.

    Raises:
        ValueError: If credentials are not configured.

    Example:
        >>> from stkai import STKAI
        >>> STKAI.configure(auth={"client_id": "x", "client_secret": "y"})
        >>> auth = create_standalone_auth()
        >>> # Uses credentials from global config
    """
    if config is None:
        from stkai._config import STKAI

        config = STKAI.config.auth

    if not config.has_credentials():
        raise ValueError(
            "Client credentials not configured. "
            "Set client_id and client_secret via STKAI.configure() or environment variables "
            "(STKAI_AUTH_CLIENT_ID, STKAI_AUTH_CLIENT_SECRET)."
        )

    return ClientCredentialsAuthProvider(
        client_id=config.client_id,  # type: ignore[arg-type]
        client_secret=config.client_secret,  # type: ignore[arg-type]
        token_url=config.token_url,
    )
