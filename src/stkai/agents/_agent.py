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

from stkai._http import HttpClient
from stkai._retry import Retrying
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
        retry_max_retries: Maximum number of retry attempts for failed chat calls.
            Use 0 to disable retries (single attempt only).
            Use 3 for 4 total attempts (1 original + 3 retries).
        retry_initial_delay: Initial delay in seconds for the first retry attempt.
            Subsequent retries use exponential backoff (delay doubles each attempt).

    Example:
        >>> # Use all defaults from config
        >>> agent = Agent(agent_id="my-agent")
        >>>
        >>> # Customize timeout and enable retry
        >>> options = AgentOptions(request_timeout=120, retry_max_retries=3)
        >>> agent = Agent(agent_id="my-agent", options=options)
    """
    request_timeout: int | None = None
    retry_max_retries: int | None = None
    retry_initial_delay: float | None = None

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
            retry_max_retries=self.retry_max_retries if self.retry_max_retries is not None else cfg.retry_max_retries,
            retry_initial_delay=self.retry_initial_delay if self.retry_initial_delay is not None else cfg.retry_initial_delay,
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

        If retry is configured (retry_max_retries > 0), automatically retries on:
        - HTTP 5xx errors (500, 502, 503, 504)
        - Network errors (Timeout, ConnectionError)

        Does NOT retry on:
        - HTTP 4xx errors (client errors)

        Note:
            retry_max_retries=0 means 1 attempt (no retry).
            retry_max_retries=3 means 4 attempts (1 original + 3 retries).

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
        assert self.options.retry_max_retries is not None, \
            "🌀 Sanity check | retry_max_retries must be set after with_defaults_from()"
        assert self.options.retry_initial_delay is not None, \
            "🌀 Sanity check | retry_initial_delay must be set after with_defaults_from()"

        try:
            for attempt in Retrying(
                max_retries=self.options.retry_max_retries,
                initial_delay=self.options.retry_initial_delay,
                logger_prefix=f"{request.id[:26]:<26} | Agent",
            ):
                with attempt:
                    logger.info(
                        f"{request.id[:26]:<26} | Agent | "
                        f"Sending message to agent '{self.agent_id}' (attempt {attempt.attempt_number}/{attempt.max_attempts})..."
                    )
                    response = self._do_chat(
                        request=request,
                        result_handler=result_handler
                    )

                    assert response, "🌀 Sanity check | Chat-Response was not created while sending the message."
                    assert response.request is request, "🌀 Sanity check | Unexpected mismatch: response does not reference its corresponding request."
                    return response

            # Should never reach here - Retrying raises MaxRetriesExceededError
            raise RuntimeError(
                "Unexpected error while chatting the agent: "
                "reached end of `_do_chat` method without returning a response."
            )

        except Exception as e:
            error_status = ChatStatus.from_exception(e)
            error_msg = f"Chat message failed: {e}"
            if isinstance(e, requests.HTTPError) and e.response is not None:
                error_msg = f"Chat message failed due to an HTTP error {e.response.status_code}: {e.response.text}"
            logger.error(
                f"{request.id[:26]:<26} | Agent | ❌ {error_msg}",
                exc_info=logger.isEnabledFor(logging.DEBUG)
            )
            return ChatResponse(
                request=request,
                status=error_status,
                error=error_msg
            )

    def _do_chat(
        self,
        request: ChatRequest,
        result_handler: "ChatResultHandler | None" = None,
    ) -> ChatResponse:
        """
        Execute the actual chat request (without retry logic).

        This internal method performs the HTTP request and processes the response.
        It raises exceptions on failure, which are handled by the retry mechanism
        in chat().

        Args:
            request: The request containing the user prompt and options.
            result_handler: Optional handler to process the response message.

        Returns:
            ChatResponse with the Agent's reply.

        Raises:
            requests.Timeout: On request timeout.
            requests.ConnectionError: On network errors.
            requests.HTTPError: On HTTP error responses.
            ChatResultHandlerError: If the result handler fails.
        """
        # Assertion for type narrowing (mypy) - caller (chat) already validates this
        assert self.options.request_timeout is not None, \
            "🌀 Sanity check | request_timeout must be set after with_defaults_from()"

        # Prepare request
        payload = request.to_api_payload()
        url = f"{self.base_url}/v1/agent/{self.agent_id}/chat"

        http_response = self.http_client.post(
            url=url,
            data=payload,
            timeout=self.options.request_timeout,
        )
        assert isinstance(http_response, requests.Response), \
            f"🌀 Sanity check | Object returned by `post` method is not an instance of `requests.Response`. ({http_response.__class__})"

        http_response.raise_for_status()
        response_data = http_response.json()
        raw_message = response_data.get("message")

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
            raw_response=response_data,
        )

        logger.info(
            f"{request.id[:26]:<26} | Agent | "
            f"✅ Response received (tokens: {response.tokens.total if response.tokens else 'N/A'})"
        )
        return response
