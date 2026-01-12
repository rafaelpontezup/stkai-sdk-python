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
from stkai.agents._models import ChatRequest, ChatResponse, ChatStatus, ChatTokenUsage


@dataclass(frozen=True)
class AgentOptions:
    """
    Configuration options for the Agent client.

    Attributes:
        request_timeout: HTTP request timeout in seconds (default: 60).

    Example:
        >>> options = AgentOptions(request_timeout=120)
        >>> agent = Agent(agent_id="my-agent", options=options)
    """
    request_timeout: int = 60


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
        >>> from stkai.agents import Agent, ChatRequest
        >>> agent = Agent(agent_id="my-agent-slug")
        >>> response = agent.chat(
        ...     request=ChatRequest(user_prompt="What is SOLID?")
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
            http_client = StkCLIAgentHttpClient(base_url="https://genai-inference-app.stackspot.com")
        self.http_client: AgentHttpClient = http_client

    def chat(self, request: ChatRequest) -> ChatResponse:
        """
        Send a message to the Agent and wait for the response (blocking).

        This method sends a user prompt to the Agent and blocks until
        a response is received or an error occurs.

        Args:
            request: The request containing the user prompt and options.

        Returns:
            ChatResponse with the Agent's reply or error information.

        Example:
            >>> # Single message
            >>> response = agent.chat(
            ...     request=ChatRequest(user_prompt="Hello!")
            ... )
            >>>
            >>> # With conversation context
            >>> resp1 = agent.chat(
            ...     request=ChatRequest(
            ...         user_prompt="What is Python?",
            ...         use_conversation=True
            ...     )
            ... )
            >>> resp2 = agent.chat(
            ...     request=ChatRequest(
            ...         user_prompt="What are its main features?",
            ...         conversation_id=resp1.conversation_id,
            ...         use_conversation=True
            ...     )
            ... )
        """
        logging.info(
            f"{request.id[:26]:<26} | Agent | "
            f"Sending message to agent '{self.agent_id}'..."
        )

        payload = request.to_api_payload()
        try:
            http_response = self.http_client.send_message(
                agent_id=self.agent_id,
                data=payload,
                timeout=self.options.request_timeout,
            )
            http_response.raise_for_status()

            response = self._parse_success_response(request, http_response.json())
            logging.info(
                f"{request.id[:26]:<26} | Agent | "
                f"✅ Response received (tokens: {response.tokens.total if response.tokens else 'N/A'})"
            )
            return response

        except requests.Timeout as e:
            error_msg = f"Request timed out: {e}"
            logging.error(
                f"{request.id[:26]:<26} | Agent | "
                f"⏱️ {error_msg}"
            )
            return ChatResponse(
                request=request,
                status=ChatStatus.TIMEOUT,
                error=error_msg,
            )

        except requests.HTTPError as e:
            error_msg = f"HTTP error {e.response.status_code}: {e.response.text}"
            logging.error(
                f"{request.id[:26]:<26} | Agent | "
                f"❌ {error_msg}"
            )
            return ChatResponse(
                request=request,
                status=ChatStatus.ERROR,
                error=error_msg,
            )

        except requests.RequestException as e:
            error_msg = f"Request failed: {e}"
            logging.error(
                f"{request.id[:26]:<26} | Agent | "
                f"❌ {error_msg}"
            )
            return ChatResponse(
                request=request,
                status=ChatStatus.ERROR,
                error=error_msg,
            )

    def _parse_success_response(self, request: ChatRequest, data: dict[str, Any]) -> ChatResponse:
        """
        Parse the API response into a ChatResponse object.

        Args:
            request: The original request.
            data: The JSON response from the API.

        Returns:
            ChatResponse with parsed data and SUCCESS status.
        """
        tokens = None
        if "tokens" in data and data["tokens"]:
            tokens = ChatTokenUsage(
                user=data["tokens"].get("user", 0),
                enrichment=data["tokens"].get("enrichment", 0),
                output=data["tokens"].get("output", 0),
            )

        return ChatResponse(
            request=request,
            status=ChatStatus.SUCCESS,
            message=data.get("message"),
            stop_reason=data.get("stop_reason"),
            tokens=tokens,
            conversation_id=data.get("conversation_id"),
            knowledge_sources=data.get("knowledge_source_id", []),
            raw_response=data,
        )
