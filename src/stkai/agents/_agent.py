"""
Agent client for StackSpot AI.

This module provides a synchronous client for interacting with StackSpot AI Agents,
supporting single message requests and conversation context.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stkai._config import AgentConfig
    from stkai.agents._handlers import ChatResultHandler

import requests

from stkai._http import HttpClient, RateLimitTimeoutError
from stkai.agents._models import ChatRequest, ChatResponse, ChatStatus

logger = logging.getLogger(__name__)


class ChatResultHandlerError(RuntimeError):
    """
    Exception raised when a result handler fails to process a chat response.

    This exception wraps the underlying error from the handler and provides
    context about which handler failed.

    Attributes:
        message: Human-readable error message.
        cause: The original exception that caused this error.
        result_handler: The handler that failed (if available).

    Example:
        >>> try:
        ...     response = agent.chat(request, result_handler=JSON_RESULT_HANDLER)
        ... except ChatResultHandlerError as e:
        ...     print(f"Handler failed: {e}")
        ...     print(f"Original error: {e.cause}")
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        result_handler: "ChatResultHandler | None" = None,
    ):
        super().__init__(message)
        self.cause = cause
        self.result_handler = result_handler


@dataclass(frozen=True)
class AgentOptions:
    """
    Configuration options for the Agent client.

    Fields set to None will use values from global config (STKAI.config.agent).

    Attributes:
        request_timeout: HTTP request timeout in seconds.

    Example:
        >>> # Use all defaults from config
        >>> agent = Agent(agent_id="my-agent")
        >>>
        >>> # Customize timeout
        >>> options = AgentOptions(request_timeout=120)
        >>> agent = Agent(agent_id="my-agent", options=options)
    """
    request_timeout: int | None = None

    def with_defaults_from(self, cfg: "AgentConfig") -> "AgentOptions":
        """
        Returns a new AgentOptions with None values filled from config.

        User-provided values take precedence; None values use config defaults.
        This follows the Single Source of Truth principle where STKAI.config
        is the authoritative source for default values.

        Args:
            cfg: The AgentConfig to use for default values.

        Returns:
            A new AgentOptions with all fields resolved (no None values).

        Example:
            >>> options = AgentOptions(request_timeout=120)
            >>> resolved = options.with_defaults_from(STKAI.config.agent)
            >>> resolved.request_timeout  # 120 (user-defined)
        """
        return AgentOptions(
            request_timeout=self.request_timeout if self.request_timeout is not None else cfg.request_timeout,
        )


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
        ...     print(response.result)

    Attributes:
        agent_id: The Agent ID (slug) to interact with.
        base_url: The base URL for the StackSpot AI API.
        options: Configuration options for the client.
        http_client: HTTP client for API calls (default: EnvironmentAwareHttpClient).
    """

    def __init__(
        self,
        agent_id: str,
        base_url: str | None = None,
        options: AgentOptions | None = None,
        http_client: HttpClient | None = None,
    ):
        """
        Initialize the Agent client.

        Args:
            agent_id: The Agent ID (slug) to interact with.
            base_url: Base URL for the StackSpot AI API.
                If None, uses global config (STKAI.config.agent.base_url).
            options: Configuration options for the client.
                If None, uses defaults from global config (STKAI.config.agent).
                Partial options are merged with config defaults via with_defaults_from().
            http_client: Custom HTTP client implementation for API calls.
                If None, uses EnvironmentAwareHttpClient (auto-detects CLI or standalone).

        Raises:
            AssertionError: If agent_id is empty.
        """
        # Get global config for defaults
        from stkai._config import STKAI
        cfg = STKAI.config.agent

        # Resolve options with defaults from config (Single Source of Truth)
        resolved_options = (options or AgentOptions()).with_defaults_from(cfg)

        # Resolve base_url
        if base_url is None:
            base_url = cfg.base_url

        if not http_client:
            from stkai._http import EnvironmentAwareHttpClient
            http_client = EnvironmentAwareHttpClient()

        # Validations
        assert agent_id, "Agent ID cannot be empty."
        assert base_url, "Agent base_url cannot be empty."
        assert http_client is not None, "Agent http_client cannot be None."

        self.agent_id = agent_id
        self.base_url = base_url.rstrip("/")
        self.options = resolved_options
        self.http_client: HttpClient = http_client

    def chat(
        self,
        request: ChatRequest,
        result_handler: "ChatResultHandler | None" = None,
    ) -> ChatResponse:
        """
        Send a message to the Agent and wait for the response (blocking).

        This method sends a user prompt to the Agent and blocks until
        a response is received or an error occurs.

        Args:
            request: The request containing the user prompt and options.
            result_handler: Optional handler to process the response message.
                If None, uses RawResultHandler (returns message as-is).
                Use JSON_RESULT_HANDLER to parse JSON responses.

        Returns:
            ChatResponse with the Agent's reply or error information.
            The `result` field contains the processed result from the handler.

        Raises:
            ChatResultHandlerError: If the result handler fails to process the response.

        Example:
            >>> # Single message (default RawResultHandler)
            >>> response = agent.chat(
            ...     request=ChatRequest(user_prompt="Hello!")
            ... )
            >>> print(response.result)  # Same as response.raw_result
            >>>
            >>> # Parse JSON response
            >>> from stkai.agents import JSON_RESULT_HANDLER
            >>> response = agent.chat(request, result_handler=JSON_RESULT_HANDLER)
            >>> print(response.result)  # Parsed dict
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
        assert request, "🌀 Sanity check | Chat-Request can not be None."
        assert request.id, "🌀 Sanity check | Chat-Request ID can not be None."

        # Assertion for type narrowing (mypy)
        assert self.options.request_timeout is not None, \
            "🌀 Sanity check | request_timeout must be set after with_defaults_from()"

        logger.info(
            f"{request.id[:26]:<26} | Agent | "
            f"Sending message to agent '{self.agent_id}'..."
        )

        # Prepare request
        payload = request.to_api_payload()
        url = f"{self.base_url}/v1/agent/{self.agent_id}/chat"
        try:
            http_response = self.http_client.post(
                url=url,
                data=payload,
                timeout=self.options.request_timeout,
            )
            http_response.raise_for_status()

            data = http_response.json()
            raw_message = data.get("message")

            # Process result through handler
            if not result_handler:
                from stkai.agents._handlers import DEFAULT_RESULT_HANDLER
                result_handler = DEFAULT_RESULT_HANDLER

            try:
                from stkai.agents._handlers import ChatResultContext
                context = ChatResultContext(request=request, raw_result=raw_message)
                processed_result = result_handler.handle_result(context)
            except Exception as e:
                handler_name = type(result_handler).__name__
                raise ChatResultHandlerError(
                    f"{request.id} | Agent | Result handler '{handler_name}' failed: {e}",
                    cause=e, result_handler=result_handler,
                ) from e

            response = ChatResponse(
                request=request,
                status=ChatStatus.SUCCESS,
                result=processed_result,
                raw_response=data,
            )

            logger.info(
                f"{request.id[:26]:<26} | Agent | "
                f"✅ Response received (tokens: {response.tokens.total if response.tokens else 'N/A'})"
            )
            return response

        except (requests.Timeout, RateLimitTimeoutError) as e:
            logger.error(
                f"{request.id[:26]:<26} | Agent | ❌ Request timed out due to: {e}"
            )
            return ChatResponse(
                request=request,
                status=ChatStatus.TIMEOUT,
                error=f"Request timed out due to: {e}",
            )

        except requests.RequestException as e:
            error_msg = f"Request failed: {e}"
            if isinstance(e, requests.HTTPError):
                error_msg = f"Request failed due to an HTTP error {e.response.status_code}: {e.response.text}"
            logger.error(
                f"{request.id[:26]:<26} | Agent | ❌ {error_msg}"
            )
            return ChatResponse(
                request=request,
                status=ChatStatus.ERROR,
                error=error_msg,
            )

        except Exception as e:
            logger.error(
                f"{request.id[:26]:<26} | Agent | ❌ Request failed with an unexpected error: {e}",
                exc_info=logger.isEnabledFor(logging.DEBUG)
            )
            return ChatResponse(
                request=request,
                status=ChatStatus.ERROR,
                error=f"Request failed with an unexpected error: {e}",
            )
