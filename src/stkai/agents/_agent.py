"""
Agent client for StackSpot AI.

This module provides a synchronous client for interacting with StackSpot AI Agents,
supporting single message requests and conversation context.
"""

import logging
from dataclasses import dataclass
from typing import Any

import requests

from stkai.agents._http import AgentHttpClient, StkCLIAgentHttpClient
from stkai.agents._models import AgentRequest, AgentResponse, AgentTokenUsage


@dataclass(frozen=True)
class AgentOptions:
    """
    Configuration options for the Agent client.

    Attributes:
        request_timeout: HTTP request timeout in seconds (default: 60).
        use_knowledge_sources: Whether to use StackSpot knowledge sources (default: True).
        return_knowledge_sources: Whether to return knowledge source IDs in response (default: False).

    Example:
        >>> options = AgentOptions(
        ...     request_timeout=120,
        ...     use_knowledge_sources=True,
        ...     return_knowledge_sources=True,
        ... )
        >>> agent = Agent(agent_id="my-agent", options=options)
    """
    request_timeout: int = 60
    use_knowledge_sources: bool = True
    return_knowledge_sources: bool = False


class Agent:
    """
    Synchronous client for interacting with StackSpot AI Agents.

    This client provides a high-level interface for sending messages to Agents
    and receiving responses, with support for:

    - Single message requests (blocking)
    - Conversation context for multi-turn interactions
    - Knowledge source integration
    - Token usage tracking

    Example:
        >>> from stkai.agents import Agent, AgentRequest
        >>> agent = Agent(agent_id="my-agent-slug")
        >>> response = agent.chat(
        ...     request=AgentRequest(user_prompt="What is SOLID?")
        ... )
        >>> if response.is_success():
        ...     print(response.message)

    Attributes:
        agent_id: The Agent ID (slug) to interact with.
        options: Configuration options for the client.
        http_client: HTTP client for API calls (default: StkCLIAgentHttpClient).
    """

    def __init__(
        self,
        agent_id: str,
        options: AgentOptions | None = None,
        http_client: AgentHttpClient | None = None,
    ):
        """
        Initialize the Agent client.

        Args:
            agent_id: The Agent ID (slug) to interact with.
            options: Configuration options for the client.
            http_client: Custom HTTP client implementation for API calls.
                If None, uses StkCLIAgentHttpClient (requires StackSpot CLI).

        Raises:
            AssertionError: If agent_id is empty.
        """
        assert agent_id, "Agent ID cannot be empty."

        self.agent_id = agent_id
        self.options = options or AgentOptions()

        if not http_client:
            http_client = StkCLIAgentHttpClient()
        self.http_client: AgentHttpClient = http_client

    def chat(
        self,
        request: AgentRequest,
        use_conversation: bool = False,
    ) -> AgentResponse:
        """
        Send a message to the Agent and wait for the response (blocking).

        This method sends a user prompt to the Agent and blocks until
        a response is received or an error occurs.

        Args:
            request: The request containing the user prompt.
            use_conversation: If True, maintains conversation context between calls.
                If request.conversation_id is provided, it will be used to
                continue an existing conversation.

        Returns:
            AgentResponse with the Agent's reply or error information.

        Example:
            >>> # Single message
            >>> response = agent.chat(
            ...     request=AgentRequest(user_prompt="Hello!")
            ... )
            >>>
            >>> # With conversation context
            >>> resp1 = agent.chat(
            ...     request=AgentRequest(user_prompt="What is Python?"),
            ...     use_conversation=True
            ... )
            >>> resp2 = agent.chat(
            ...     request=AgentRequest(
            ...         user_prompt="What are its main features?",
            ...         conversation_id=resp1.conversation_id
            ...     ),
            ...     use_conversation=True
            ... )
        """
        logging.info(
            f"{request.id[:26]:<26} | Agent | "
            f"Sending message to agent '{self.agent_id}'..."
        )

        payload = request.to_api_payload(
            use_conversation=use_conversation,
            use_knowledge_sources=self.options.use_knowledge_sources,
            return_knowledge_sources=self.options.return_knowledge_sources,
        )

        try:
            http_response = self.http_client.send_message(
                agent_id=self.agent_id,
                data=payload,
                timeout=self.options.request_timeout,
            )
            http_response.raise_for_status()

            response = self._parse_response(request, http_response.json())
            logging.info(
                f"{request.id[:26]:<26} | Agent | "
                f"✅ Response received (tokens: {response.tokens.total if response.tokens else 'N/A'})"
            )
            return response

        except requests.HTTPError as e:
            error_msg = f"HTTP error {e.response.status_code}: {e.response.text}"
            logging.error(
                f"{request.id[:26]:<26} | Agent | "
                f"❌ {error_msg}"
            )
            return AgentResponse(
                request=request,
                error=error_msg,
            )

        except requests.RequestException as e:
            error_msg = f"Request failed: {e}"
            logging.error(
                f"{request.id[:26]:<26} | Agent | "
                f"❌ {error_msg}"
            )
            return AgentResponse(
                request=request,
                error=error_msg,
            )

    def _parse_response(self, request: AgentRequest, data: dict[str, Any]) -> AgentResponse:
        """
        Parse the API response into an AgentResponse object.

        Args:
            request: The original request.
            data: The JSON response from the API.

        Returns:
            AgentResponse with parsed data.
        """
        tokens = None
        if "tokens" in data and data["tokens"]:
            tokens = AgentTokenUsage(
                user=data["tokens"].get("user", 0),
                enrichment=data["tokens"].get("enrichment", 0),
                output=data["tokens"].get("output", 0),
            )

        return AgentResponse(
            request=request,
            message=data.get("message"),
            stop_reason=data.get("stop_reason"),
            tokens=tokens,
            conversation_id=data.get("conversation_id"),
            knowledge_sources=data.get("knowledge_source_id", []),
            raw_response=data,
        )
