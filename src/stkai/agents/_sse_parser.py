"""
SSE (Server-Sent Events) parser for StackSpot AI Agent streaming responses.

This module provides a standalone parser that converts raw SSE lines into
typed ``ChatResponseStreamEvent`` objects. It supports two SSE formats:

1. **StackSpot native** — flat ``message`` field per chunk.
2. **LiteLLM/OpenAI-compatible** — ``choices[0].delta.content`` per chunk.

The parser does not accumulate delta text — it yields events and tracks
metadata. Text accumulation is the responsibility of ``ChatResponseStream``.

The parser can be subclassed to handle protocol changes without waiting
for a new SDK release::

    class MyParser(SseEventParser):
        @staticmethod
        def _extract_delta_text(data: dict) -> str:
            return data.get("response_text", "")

    with agent.chat_stream(request, event_parser=MyParser()) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)

Example:
    >>> parser = SseEventParser()
    >>> for event in parser.parse(response.iter_lines(decode_unicode=True)):
    ...     if event.is_delta:
    ...         print(event.text, end="", flush=True)
    >>> print(parser.metadata)  # conversation_id, tokens, etc.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from typing import Any

from stkai.agents._stream import ChatResponseStreamEvent, ChatResponseStreamEventType

logger = logging.getLogger(__name__)


class SseEventParser:
    """Parses SSE (Server-Sent Events) lines into ``ChatResponseStreamEvent`` objects.

    Call ``parse(lines)`` to iterate over parsed events. Metadata accumulated
    from chunks (conversation_id, tokens, stop_reason, etc.) is available via
    the ``metadata`` property after the returned iterator is fully consumed.

    The parser is safe to reuse — each ``parse()`` call resets internal state.
    Subclass and override ``_extract_delta_text`` or ``_track_chunk_metadata``
    to handle protocol changes.
    """

    def __init__(self) -> None:
        self._raw_done_data: dict[str, Any] | None = None

    @property
    def metadata(self) -> dict[str, Any] | None:
        """Accumulated metadata from chunks (conversation_id, tokens, etc.).

        Available after the iterator returned by ``parse()`` is fully consumed.
        Returns ``None`` if no metadata was found in any chunk.
        """
        return self._raw_done_data

    def parse(self, lines: Iterable[str | bytes]) -> Iterator[ChatResponseStreamEvent]:
        """Parse SSE lines and yield events.

        Each call resets internal state (including ``metadata``), making the
        parser safe to reuse across multiple streams.

        Args:
            lines: An iterable of SSE lines (typically from
                ``response.iter_lines(decode_unicode=True)``).

        Yields:
            ChatResponseStreamEvent for each parsed SSE event.
        """
        self._raw_done_data = None

        event_type: str | None = None
        data_buffer: list[str] = []

        for line in lines:
            if line is None:
                continue

            line = str(line)

            # Empty line = end of event
            if not line.strip():
                if data_buffer:
                    event = self._build_event(event_type, "\n".join(data_buffer))
                    if event is not None:
                        yield event
                    event_type = None
                    data_buffer = []
                continue

            # SSE field parsing
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_buffer.append(line[len("data:"):].strip())
            # Ignore comments (lines starting with :) and unknown fields

        # Handle last event if stream ends without trailing newline
        if data_buffer:
            event = self._build_event(event_type, "\n".join(data_buffer))
            if event is not None:
                yield event

    def _build_event(
        self, event_type: str | None, data: str,
    ) -> ChatResponseStreamEvent | None:
        """Build a ChatResponseStreamEvent from raw SSE fields.

        Supports the LiteLLM/OpenAI-compatible SSE format used by StackSpot AI::

            data: {"choices":[{"index":0,"delta":{"content":"Hello"}}]}
            data: [DONE]
        """
        # LiteLLM/OpenAI stream termination signal
        if data == "[DONE]":
            return ChatResponseStreamEvent(
                type=ChatResponseStreamEventType.DONE,
                raw_data=self._raw_done_data or {},
            )

        logger.debug(f"SSE raw | event_type={event_type!r} data={data!r}")
        parsed_data = self._try_parse_json(data)

        # Error events
        if event_type == "error" or (
            isinstance(parsed_data, dict) and parsed_data.get("type") == "error"
        ):
            error_msg = data
            if isinstance(parsed_data, dict):
                error_msg = str(parsed_data.get("message", parsed_data.get("error", data)))
            return ChatResponseStreamEvent(
                type=ChatResponseStreamEventType.ERROR,
                error=str(error_msg),
                raw_data=parsed_data if isinstance(parsed_data, dict) else {"raw": data},
            )

        # Explicit done event (non-LiteLLM servers)
        if event_type == "done" or (
            isinstance(parsed_data, dict) and parsed_data.get("type") == "done"
        ):
            self._raw_done_data = parsed_data if isinstance(parsed_data, dict) else {}
            return ChatResponseStreamEvent(
                type=ChatResponseStreamEventType.DONE,
                raw_data=self._raw_done_data,
            )

        # Delta event: extract text content
        text = ""
        if isinstance(parsed_data, dict):
            text = self._extract_delta_text(parsed_data)
            # Track metadata from the last chunk (finish_reason, usage, etc.)
            self._track_chunk_metadata(parsed_data)
        elif isinstance(parsed_data, str):
            text = parsed_data
        else:
            text = data

        text = str(text)

        return ChatResponseStreamEvent(
            type=ChatResponseStreamEventType.DELTA,
            text=text,
            raw_data=parsed_data if isinstance(parsed_data, dict) else {"raw": data},
        )

    @staticmethod
    def _extract_delta_text(data: dict[str, Any]) -> str:
        """Extract text content from a delta event.

        Supports two SSE formats (checked in order):

        1. **StackSpot native** — flat ``message`` field::

            data: {"message": "Hello", "knowledge_source_id": [], ...}

        2. **LiteLLM/OpenAI-compatible** — ``choices[0].delta.content``::

            data: {"choices":[{"index":0,"delta":{"content":"Hello"}}]}
        """
        # StackSpot native format: flat "message" field
        message = data.get("message")
        if message is not None and isinstance(message, str):
            return str(message)

        # LiteLLM/OpenAI format: choices[0].delta.content
        choices = data.get("choices")
        if isinstance(choices, list) and len(choices) > 0:
            choice = choices[0]
            if isinstance(choice, dict):
                delta = choice.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if content is not None:
                        return str(content)

        # Flat fallback (forward-compatibility)
        for field in ("content", "text", "delta"):
            value = data.get(field)
            if value is not None and isinstance(value, str):
                return str(value)

        return ""

    def _track_chunk_metadata(self, data: dict[str, Any]) -> None:
        """Track metadata from streaming chunks for the final response.

        The last chunk before ``[DONE]`` typically contains ``finish_reason``
        and may contain ``usage`` data. StackSpot-specific fields like
        ``conversation_id`` may also appear in chunks.
        """
        # StackSpot-specific fields (may appear in any chunk)
        for field in ("conversation_id", "tokens", "knowledge_source_id", "stop_reason"):
            if field in data:
                if self._raw_done_data is None:
                    self._raw_done_data = {}
                self._raw_done_data[field] = data[field]

        # LiteLLM/OpenAI: finish_reason from choices[0]
        choices = data.get("choices")
        if isinstance(choices, list) and len(choices) > 0:
            choice = choices[0]
            if isinstance(choice, dict):
                finish_reason = choice.get("finish_reason")
                if finish_reason is not None:
                    if self._raw_done_data is None:
                        self._raw_done_data = {}
                    self._raw_done_data["stop_reason"] = finish_reason

        # LiteLLM/OpenAI: usage from top-level
        usage = data.get("usage")
        if isinstance(usage, dict) and "tokens" not in (self._raw_done_data or {}):
            if self._raw_done_data is None:
                self._raw_done_data = {}
            # Map LiteLLM usage fields to StackSpot token format
            self._raw_done_data["tokens"] = {
                "user": usage.get("prompt_tokens", 0),
                "enrichment": 0,
                "output": usage.get("completion_tokens", 0),
            }

    @staticmethod
    def _try_parse_json(data: str) -> dict[str, Any] | str:
        """Try to parse data as JSON; return original string on failure."""
        try:
            parsed = json.loads(data)
            if isinstance(parsed, dict):
                return parsed
            return data
        except (json.JSONDecodeError, ValueError):
            return data
