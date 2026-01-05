"""
Result handlers implementations for Remote Quick Command responses.

This module contains concrete implementations of RqcResultHandler
for processing RQC execution results.
"""

import json
import logging
from copy import deepcopy
from typing import Any, override, Sequence

from stkai.rqc._remote_quick_command import RqcResultHandler, RqcResultContext


class ChainedResultHandler(RqcResultHandler):
    """Handler that chains multiple handlers in sequence."""

    def __init__(self, chained_handlers: Sequence[RqcResultHandler]):
        self.chained_handlers = chained_handlers

    @override
    def handle_result(self, context: RqcResultContext) -> Any:
        result = context.raw_result
        for next_handler in self.chained_handlers:
            result = next_handler.handle_result(context)
            context = RqcResultContext(request=context.request, raw_result=result, handled=True)
        return result

    @staticmethod
    def of(handlers: RqcResultHandler | Sequence[RqcResultHandler]) -> "ChainedResultHandler":
        """Create a ChainedResultHandler from a single handler or sequence of handlers."""
        return ChainedResultHandler(
            [handlers] if isinstance(handlers, RqcResultHandler) else list(handlers)
        )


class RawResultHandler(RqcResultHandler):
    """Handler that returns the raw result without transformation."""

    @override
    def handle_result(self, context: RqcResultContext) -> Any:
        return context.raw_result


class JsonResultHandler(RqcResultHandler):
    """Handler that parses JSON results into Python objects."""

    @override
    def handle_result(self, context: RqcResultContext) -> Any:
        """
        Attempts to parse the `result` attribute as JSON, sanitizing markdown-style code blocks if necessary.
        Returns a Python dict if parsing succeeds; raises JSONDecodeError otherwise.

        Examples:
            - result = '{"ok": true}' -> {'ok': True}
            - result = '```json\\n{"x":1}\\n```' -> {'x': 1}

        Raises:
            json.JSONDecodeError: if `result` is not valid JSON.
        """
        result = context.raw_result
        if not result:
            return None

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
            logging.warning(
                f"{context.execution_id} | RQC | ⚠️ Response result not in JSON format. Treating it as plain text. "
                f"Preview:\n | {' | '.join(preview)}"
            )
            raise

    @staticmethod
    def chain_with(other_handler: RqcResultHandler) -> RqcResultHandler:
        """Create a chained handler with JSON parsing followed by another handler."""
        json_handler = JsonResultHandler()
        return ChainedResultHandler.of([json_handler, other_handler])


DEFAULT_RESULT_HANDLER = JsonResultHandler()
RAW_RESULT_HANDLER = RawResultHandler()
