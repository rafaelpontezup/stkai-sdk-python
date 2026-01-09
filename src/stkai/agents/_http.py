"""
HTTP client implementations for StackSpot AI Agents.

This module contains concrete implementations of AgentHttpClient
for making authorized HTTP requests to the StackSpot AI Agent API.

The default implementation (StkCLIAgentHttpClient) uses the StackSpot CLI
for authentication, which requires the CLI to be installed and configured.

Available implementations:
    - StkCLIAgentHttpClient: Uses StackSpot CLI for authentication.
"""

from abc import ABC, abstractmethod
from typing import Any, override

import requests


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

        from oscli import __codebuddy_base_url__
        from oscli.core.http import post_with_authorization

        url = f"{__codebuddy_base_url__}/v1/agent/{agent_id}/chat"

        response: requests.Response = post_with_authorization(
            url=url,
            body=data,
            timeout=timeout,
        )
        return response
