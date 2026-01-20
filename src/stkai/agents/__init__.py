"""
Agents module for StackSpot AI.

This module provides client abstractions for interacting with
StackSpot AI Agents API.

Example:
    >>> from stkai.agents import Agent, ChatRequest
    >>> agent = Agent(agent_id="my-agent-slug")
    >>> response = agent.chat(
    ...     request=ChatRequest(user_prompt="What is SOLID?")
    ... )
    >>> if response.is_success():
    ...     print(response.result)

For conversation context:
    >>> resp1 = agent.chat(
    ...     request=ChatRequest(
    ...         user_prompt="What is Python?",
    ...         use_conversation=True
    ...     )
    ... )
    >>> resp2 = agent.chat(
    ...     request=ChatRequest(
    ...         user_prompt="What are its features?",
    ...         conversation_id=resp1.conversation_id,
    ...         use_conversation=True
    ...     )
    ... )

For JSON response parsing:
    >>> from stkai.agents import Agent, ChatRequest, JSON_RESULT_HANDLER
    >>> response = agent.chat(request, result_handler=JSON_RESULT_HANDLER)
    >>> print(response.result)  # Parsed dict
"""

from stkai.agents._agent import (
    Agent,
    AgentOptions,
    ChatResultHandlerError,
)
from stkai.agents._handlers import (
    DEFAULT_RESULT_HANDLER,
    JSON_RESULT_HANDLER,
    ChainedResultHandler,
    ChatResultContext,
    ChatResultHandler,
    JsonResultHandler,
    RawResultHandler,
)
from stkai.agents._models import (
    ChatRequest,
    ChatResponse,
    ChatStatus,
    ChatTokenUsage,
)

__all__ = [
    # Main client
    "Agent",
    # Options
    "AgentOptions",
    # Data models
    "ChatRequest",
    "ChatResponse",
    "ChatStatus",
    "ChatTokenUsage",
    # Result handlers
    "ChatResultContext",
    "ChatResultHandler",
    "ChainedResultHandler",
    "JsonResultHandler",
    "RawResultHandler",
    "DEFAULT_RESULT_HANDLER",
    "JSON_RESULT_HANDLER",
    # Exceptions
    "ChatResultHandlerError",
]
