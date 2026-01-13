"""
HTTP client implementations for StackSpot AI Agents.

This module contains concrete implementations of AgentHttpClient
for making authorized HTTP requests to the StackSpot AI Agent API.

Available implementations:
    - StkCLIAgentHttpClient: Uses StackSpot CLI for authentication.
    - StandaloneAgentHttpClient: Uses AuthProvider for standalone authentication.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, override

import requests

if TYPE_CHECKING:
    from stkai._auth import AuthProvider


class AgentHttpClient(ABC):
    """
    Abstract base class for Agent HTTP clients.

    Implement this class to provide custom HTTP client implementations
    for different authentication mechanisms or environments.

    See Also:
        StkCLIAgentHttpClient: Default implementation using StackSpot CLI credentials.
    """

    @abstractmethod
    def send_message(
        self,
        agent_id: str,
        data: dict[str, Any],
        timeout: int = 60,
    ) -> requests.Response:
        """
        Send a message to an Agent via the StackSpot AI API.

        Args:
            agent_id: The Agent ID (slug) to send the message to.
            data: The request payload containing the message and options.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response from the StackSpot AI API.
        """
        pass


class StkCLIAgentHttpClient(AgentHttpClient):
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
        AgentHttpClient: Abstract base class defining the interface.
    """
    def __init__(self, base_url: str) -> None:
        assert base_url, "Agent API base-URL can not be empty."
        self.base_url = base_url

    @override
    def send_message(
        self,
        agent_id: str,
        data: dict[str, Any],
        timeout: int = 60,
    ) -> requests.Response:
        """
        Send a message to an Agent via the StackSpot AI API.

        Args:
            agent_id: The Agent ID (slug) to send the message to.
            data: The request payload containing the message and options.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response from the StackSpot AI API.

        Raises:
            AssertionError: If agent_id is empty or timeout is invalid.
            requests.RequestException: If the HTTP request fails.
        """
        assert agent_id, "Agent ID cannot be empty."
        assert timeout is not None, "Timeout cannot be None."
        assert timeout > 0, "Timeout must be greater than 0."

        from oscli.core.http import post_with_authorization

        url = f"{self.base_url}/v1/agent/{agent_id}/chat"

        response: requests.Response = post_with_authorization(
            url=url,
            body=data,
            timeout=timeout,
        )
        return response


class StandaloneAgentHttpClient(AgentHttpClient):
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
        >>> from stkai.agents._http import StandaloneAgentHttpClient
        >>>
        >>> auth = ClientCredentialsAuthProvider(
        ...     client_id="my-client-id",
        ...     client_secret="my-client-secret",
        ... )
        >>> client = StandaloneAgentHttpClient(auth_provider=auth)
        >>> agent = Agent("my-agent", http_client=client)

    Args:
        auth_provider: Provider for authorization tokens.
        base_url: Base URL for the Agent API.

    See Also:
        ClientCredentialsAuthProvider: OAuth2 client credentials implementation.
        AgentHttpClient: Abstract base class defining the interface.
    """

    DEFAULT_BASE_URL = "https://genai-inference-app.stackspot.com"

    def __init__(
        self,
        auth_provider: "AuthProvider",
        base_url: str = DEFAULT_BASE_URL,
    ):
        """
        Initialize the standalone HTTP client.

        Args:
            auth_provider: Provider for authorization tokens.
            base_url: Base URL for the Agent API.

        Raises:
            AssertionError: If auth_provider is None.
        """
        from stkai._auth import AuthProvider

        assert auth_provider is not None, "auth_provider cannot be None"
        assert isinstance(auth_provider, AuthProvider), "auth_provider must be an AuthProvider instance"

        self._auth = auth_provider
        self._base_url = base_url.rstrip("/")

    @override
    def send_message(
        self,
        agent_id: str,
        data: dict[str, Any],
        timeout: int = 60,
    ) -> requests.Response:
        """
        Send a message to an Agent via the StackSpot AI API.

        Args:
            agent_id: The Agent ID (slug) to send the message to.
            data: The request payload containing the message and options.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response from the StackSpot AI API.

        Raises:
            AssertionError: If agent_id is empty or timeout is invalid.
            requests.RequestException: If the HTTP request fails.
            AuthenticationError: If unable to obtain authorization token.
        """
        assert agent_id, "Agent ID cannot be empty."
        assert timeout is not None, "Timeout cannot be None."
        assert timeout > 0, "Timeout must be greater than 0."

        url = f"{self._base_url}/v1/agent/{agent_id}/chat"

        return requests.post(
            url,
            json=data,
            headers=self._auth.get_auth_headers(),
            timeout=timeout,
        )
