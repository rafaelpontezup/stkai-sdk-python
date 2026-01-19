"""
Result handlers for StackSpot AI Agent responses.

This module contains the ChatResultHandler abstract base class, ChatResultContext
dataclass, and concrete implementations for processing Agent chat results.

Available Handlers:
    - RawResultHandler: Returns the raw message without transformation (default).
    - JsonResultHandler: Parses JSON strings into Python objects.
    - ChainedResultHandler: Chains multiple handlers in sequence.

Module Constants:
    - DEFAULT_RESULT_HANDLER: RawResultHandler instance (used by default).
    - JSON_RESULT_HANDLER: JsonResultHandler instance for JSON parsing.

Example:
    >>> from stkai.agents import Agent, ChatRequest, JSON_RESULT_HANDLER
    >>> agent = Agent(agent_id="my-agent")
    >>> response = agent.chat(request, result_handler=JSON_RESULT_HANDLER)
    >>> print(response.result)  # Parsed JSON object
"""

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, override

from stkai.agents._models import ChatRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatResultContext:
    """
    Context passed to result handlers during processing.

    This immutable class provides result handlers with all the information
    needed to process a chat result, including the original request
    and the raw message from the API.

    Attributes:
        request: The original ChatRequest.
        raw_result: The unprocessed message from the Agent API.
        handled: Flag indicating if a previous handler has already processed this result.
    """
    request: ChatRequest
    raw_result: Any
    handled: bool = False

    def __post_init__(self) -> None:
        assert self.request, "ChatRequest can not be empty."
        assert self.handled is not None, "Context's handled flag can not be None."

    @property
    def request_id(self) -> str:
        """Returns the request ID from the associated request."""
        return self.request.id


class ChatResultHandler(ABC):
    """
    Abstract base class for chat result handlers.

    Result handlers are responsible for transforming the raw Agent message
    into a more useful format. Implement this class to create custom handlers.

    Example:
        >>> class MyHandler(ChatResultHandler):
        ...     def handle_result(self, context: ChatResultContext) -> Any:
        ...         return context.raw_result.upper()
    """

    @abstractmethod
    def handle_result(self, context: ChatResultContext) -> Any:
        """
        Process the result and return the transformed value.

        Args:
            context: The ChatResultContext containing the raw result and request info.

        Returns:
            The transformed result value.

        Note:
            Any exception raised will be wrapped in ChatResultHandlerError.
        """
        pass


class ChainedResultHandler(ChatResultHandler):
    """
    Handler that chains multiple handlers in sequence.

    Each handler processes the result from the previous handler,
    allowing for complex transformation pipelines.

    Example:
        >>> handler = ChainedResultHandler.of([JsonResultHandler(), MyCustomHandler()])
        >>> # First parses JSON, then applies custom transformation

    Attributes:
        chained_handlers: Sequence of handlers to execute in order.
    """

    def __init__(self, chained_handlers: Sequence[ChatResultHandler]):
        """
        Initialize with a sequence of handlers.

        Args:
            chained_handlers: Handlers to execute in order.
        """
        self.chained_handlers = chained_handlers

    @override
    def handle_result(self, context: ChatResultContext) -> Any:
        """Executes each handler in sequence, passing results through the chain."""
        result = context.raw_result
        for next_handler in self.chained_handlers:
            result = next_handler.handle_result(context)
            context = ChatResultContext(request=context.request, raw_result=result, handled=True)
        return result

    @staticmethod
    def of(handlers: ChatResultHandler | Sequence[ChatResultHandler]) -> "ChainedResultHandler":
        """
        Factory method to create a ChainedResultHandler.

        Args:
            handlers: A single handler or sequence of handlers.

        Returns:
            A ChainedResultHandler wrapping the provided handlers.
        """
        return ChainedResultHandler(
            [handlers] if isinstance(handlers, ChatResultHandler) else list(handlers)
        )


class RawResultHandler(ChatResultHandler):
    """
    Handler that returns the raw result without transformation.

    This is the default handler for Agent responses since they typically
    contain plain text messages, not structured JSON.
    """

    @override
    def handle_result(self, context: ChatResultContext) -> Any:
        """Returns the raw result as-is without any transformation."""
        return context.raw_result


class JsonResultHandler(ChatResultHandler):
    """
    Handler that parses JSON results into Python objects.

    This handler is useful when the Agent is configured to return JSON
    or when using prompts that request structured output. It handles
    common response formats including:

    - Raw JSON strings
    - JSON wrapped in markdown code blocks (```json ... ```)
    - Already-parsed dict objects (returns a deep copy)

    Example:
        >>> from stkai.agents import JSON_RESULT_HANDLER
        >>> response = agent.chat(request, result_handler=JSON_RESULT_HANDLER)
        >>> print(response.result)  # {'key': 'value'}
    """

    @override
    def handle_result(self, context: ChatResultContext) -> Any:
        """
        Parses the raw result as JSON.

        Handles markdown code block wrappers (```json ... ```) automatically.

        Args:
            context: The result context containing the raw result.

        Returns:
            Parsed Python object (dict, list, etc.) or None if result is empty.

        Raises:
            json.JSONDecodeError: If the result is not valid JSON.
            TypeError: If the result is neither a string nor a dict.

        Examples:
            - '{"ok": true}' -> {'ok': True}
            - '```json\\n{"x":1}\\n```' -> {'x': 1}
        """
        result = context.raw_result
        if not result:
            return result

        if isinstance(result, dict):
            return deepcopy(result)

        if not isinstance(result, str):
            _type_name = type(result).__name__
            raise TypeError(
                f"{context.request_id} | Agent | Cannot parse JSON from non-string result (type={_type_name})"
            )

        # Remove Markdown code block wrappers (```json ... ```)
        sanitized = result.replace("```json", "").replace("```", "").strip()

        # Tries to convert JSON to Python object
        try:
            return json.loads(sanitized)
        except json.JSONDecodeError:
            # Log contextual warning with a short preview of the raw text
            preview = result.strip().splitlines(keepends=True)[:3]
            logger.warning(
                f"{context.request_id} | Agent | Response message not in JSON format. Treating it as plain text. "
                f"Preview:\n | {' | '.join(preview)}"
            )
            raise

    @staticmethod
    def chain_with(other_handler: ChatResultHandler) -> ChatResultHandler:
        """
        Creates a chained handler with JSON parsing followed by another handler.

        This is a convenience method for the common pattern of first parsing
        JSON and then applying additional transformations.

        Args:
            other_handler: Handler to execute after JSON parsing.

        Returns:
            A ChainedResultHandler that first parses JSON, then applies other_handler.

        Example:
            >>> handler = JsonResultHandler.chain_with(MyCustomHandler())
        """
        json_handler = JsonResultHandler()
        return ChainedResultHandler.of([json_handler, other_handler])


# Pre-configured handler instances for common use cases
DEFAULT_RESULT_HANDLER = RawResultHandler()
"""Default handler that returns raw results. Used by Agent when no handler is specified."""

JSON_RESULT_HANDLER = JsonResultHandler()
"""Handler that parses JSON results. Useful when Agent returns structured data."""
