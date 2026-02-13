"""
Result handlers for Remote Quick Command responses.

This module contains the RqcResultHandler abstract base class, RqcResultContext
dataclass, and concrete implementations for processing RQC execution results.

Available Handlers:
    - JsonResultHandler: Parses JSON strings into Python objects (default).
    - RawResultHandler: Returns the raw result without transformation.
    - ChainedResultHandler: Chains multiple handlers in sequence.

Module Constants:
    - DEFAULT_RESULT_HANDLER: JsonResultHandler instance (used by default).
    - RAW_RESULT_HANDLER: RawResultHandler instance for raw results.

Example:
    >>> from stkai.rqc import RemoteQuickCommand, RqcRequest, RAW_RESULT_HANDLER
    >>> rqc = RemoteQuickCommand(slug_name="my-command")
    >>> response = rqc.execute(request, result_handler=RAW_RESULT_HANDLER)
"""

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, override

from stkai.rqc._models import RqcRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RqcResultContext:
    """
    Context passed to result handlers during processing.

    This immutable class provides result handlers with all the information
    needed to process an execution result, including the original request
    and the raw result from the API.

    Attributes:
        request: The original RqcRequest.
        raw_result: The unprocessed result from the StackSpot AI API.
        execution_id: The server-assigned execution ID for this execution.
        handled: Flag indicating if a previous handler has already processed this result.
    """
    request: RqcRequest
    raw_result: Any
    execution_id: str
    handled: bool = False

    def __post_init__(self) -> None:
        assert self.request, "RQC-Request can not be empty."
        assert self.execution_id, "Execution ID can not be empty."
        assert self.handled is not None, "Context's handled flag can not be None."

    def with_result(self, result: Any) -> "RqcResultContext":
        """Returns a new context with the given result and handled=True."""
        return replace(self, raw_result=result, handled=True)


class RqcResultHandlerError(RuntimeError):
    """
    Raised when the result handler fails to process the result.

    This exception wraps any error that occurs during result processing,
    providing access to the original cause and the handler that failed.

    Attributes:
        cause: The original exception that caused the handler to fail.
        result_handler: The handler instance that raised the error.
    """

    def __init__(self, message: str, cause: Exception | None = None, result_handler: "RqcResultHandler | None" = None):
        super().__init__(message)
        self.cause = cause
        self.result_handler = result_handler


class RqcResultHandler(ABC):
    """
    Abstract base class for result handlers.

    Result handlers are responsible for transforming the raw API response
    into a more useful format. Implement this class to create custom handlers.

    Example:
        >>> class MyHandler(RqcResultHandler):
        ...     def handle_result(self, context: RqcResultContext) -> Any:
        ...         return context.raw_result.upper()
    """

    @abstractmethod
    def handle_result(self, context: RqcResultContext) -> Any:
        """
        Process the result and return the transformed value.

        Args:
            context: The RqcResultContext containing the raw result and request info.

        Returns:
            The transformed result value.

        Note:
            Any exception raised will be wrapped in RqcResultHandlerError.
        """
        pass


class ChainedResultHandler(RqcResultHandler):
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

    def __init__(self, chained_handlers: Sequence[RqcResultHandler]):
        """
        Initialize with a sequence of handlers.

        Args:
            chained_handlers: Handlers to execute in order.
        """
        self.chained_handlers = chained_handlers

    @override
    def handle_result(self, context: RqcResultContext) -> Any:
        """Executes each handler in sequence, passing results through the chain."""
        total = len(self.chained_handlers)
        handler_names = [h.__class__.__name__ for h in self.chained_handlers]
        logger.debug(
            f"{context.execution_id} | RQC | Processing chain with {total} handler(s): {handler_names}"
        )

        result = context.raw_result
        for i, next_handler in enumerate(self.chained_handlers):
            handler_name = next_handler.__class__.__name__
            try:
                result = next_handler.handle_result(context)
            except RqcResultHandlerError:
                raise
            except Exception as e:
                raise RqcResultHandlerError(
                    cause=e,
                    result_handler=next_handler,
                    message=f"Handler '{handler_name}' failed in chain: {e}",
                ) from e
            # Only advance context on success; on error the exception propagates
            context = context.with_result(result)
            logger.debug(
                f"{context.execution_id} | RQC | Handler '{handler_name}' completed ({i + 1}/{total})"
            )
        return result

    @staticmethod
    def of(handlers: RqcResultHandler | Sequence[RqcResultHandler]) -> "ChainedResultHandler":
        """
        Factory method to create a ChainedResultHandler.

        Args:
            handlers: A single handler or sequence of handlers.

        Returns:
            A ChainedResultHandler wrapping the provided handlers.
        """
        return ChainedResultHandler(
            [handlers] if isinstance(handlers, RqcResultHandler) else list(handlers)
        )


class RawResultHandler(RqcResultHandler):
    """
    Handler that returns the raw result without transformation.

    Use this handler when you want to access the unprocessed API response,
    for example when debugging or when the result is not JSON.
    """

    @override
    def handle_result(self, context: RqcResultContext) -> Any:
        """Returns the raw result as-is without any transformation."""
        return context.raw_result


class JsonResultHandler(RqcResultHandler):
    """
    Handler that parses JSON results into Python objects.

    This is the default handler used by RemoteQuickCommand. It handles
    common response formats from StackSpot AI, including:

    - Raw JSON strings
    - JSON wrapped in markdown code blocks (```json ... ```)
    - Already-parsed dict objects (returns a deep copy)

    Example:
        >>> handler = JsonResultHandler()
        >>> context = RqcResultContext(request=req, raw_result='{"key": "value"}')
        >>> result = handler.handle_result(context)
        >>> print(result)  # {'key': 'value'}
    """

    @override
    def handle_result(self, context: RqcResultContext) -> Any:
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
                f"{context.execution_id} | RQC | Cannot parse JSON from non-string result (type={_type_name})"
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
                f"{context.execution_id} | RQC | ⚠️ Response result not in JSON format. Treating it as plain text. "
                f"Preview:\n | {' | '.join(preview)}"
            )
            raise

    @staticmethod
    def chain_with(other_handler: RqcResultHandler) -> RqcResultHandler:
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
DEFAULT_RESULT_HANDLER = JsonResultHandler()
"""Default handler that parses JSON results. Used by RemoteQuickCommand when no handler is specified."""

RAW_RESULT_HANDLER = RawResultHandler()
"""Handler that returns raw results without transformation. Useful for debugging or non-JSON responses."""
