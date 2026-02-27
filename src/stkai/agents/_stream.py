"""
Streaming support for StackSpot AI Agents.

This module provides the streaming API for Agent chat, allowing real-time
consumption of SSE (Server-Sent Events) responses via a context manager.

Example:
    >>> with agent.chat_stream(ChatRequest(user_prompt="Hello")) as stream:
    ...     for event in stream:
    ...         if event.is_delta:
    ...             print(event.text, end="", flush=True)
    ...     print(f"\\nTokens: {stream.response.tokens.total}")

    >>> # Convenience helper for text-only iteration
    >>> with agent.chat_stream(ChatRequest(user_prompt="Hello")) as stream:
    ...     for text in stream.text_stream:
    ...         print(text, end="", flush=True)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import requests

from stkai.agents._handlers import ChatResultHandler
from stkai.agents._models import ChatRequest, ChatResponse, ChatStatus

logger = logging.getLogger(__name__)


class ChatResponseStreamEventType(StrEnum):
    """Type of a streaming event from the Agent API."""

    DELTA = "delta"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True)
class ChatResponseStreamEvent:
    """
    A single event from a streaming Agent response.

    Attributes:
        type: The event type (DELTA, DONE, ERROR).
        text: Text content for DELTA events.
        raw_data: Raw parsed SSE data dictionary.
        error: Error message for ERROR events.
    """

    type: ChatResponseStreamEventType
    text: str = ""
    raw_data: dict[str, Any] | None = None
    error: str | None = None

    @property
    def is_delta(self) -> bool:
        """Returns True if this is a text delta event."""
        return self.type == ChatResponseStreamEventType.DELTA

    @property
    def is_done(self) -> bool:
        """Returns True if the stream is complete."""
        return self.type == ChatResponseStreamEventType.DONE

    @property
    def is_error(self) -> bool:
        """Returns True if this is an error event."""
        return self.type == ChatResponseStreamEventType.ERROR


class ChatResponseStream:
    """
    Context manager and iterator for streaming Agent responses.

    Wraps an HTTP response with ``stream=True`` and parses SSE events,
    providing auto-accumulation and a final ``ChatResponse`` after iteration.

    Must be used as a context manager to ensure proper cleanup of the
    underlying HTTP connection::

        with agent.chat_stream(request) as stream:
            for event in stream:
                ...
            response = stream.response

    **Error handling:** following the SDK principle of "requests in,
    responses out", errors during streaming (SSE failures, handler errors)
    never propagate as exceptions. Instead, ``response`` is always
    available after iteration with an appropriate status:

    - **SUCCESS** — stream completed and handler (if any) succeeded.
    - **ERROR** — SSE connection failed or handler raised an exception.
    - **TIMEOUT** — SSE connection timed out.

    On error, ``response.result`` contains the raw accumulated text
    (partial on SSE failure, complete on handler failure) so the caller
    can still inspect what the Agent returned.

    Attributes:
        request: The original ChatRequest.
        response: The final ChatResponse (available after iteration completes).
        accumulated_text: Text accumulated so far during iteration.
    """

    def __init__(
        self,
        request: ChatRequest,
        http_response: requests.Response,
        result_handler: ChatResultHandler | None = None,
    ) -> None:
        self._request = request
        self._http_response = http_response
        self._result_handler = result_handler
        self._accumulated_parts: list[str] = []
        self._response: ChatResponse | None = None
        self._raw_done_data: dict[str, Any] | None = None
        self._closed = False
        self._iterated = False

    @property
    def request(self) -> ChatRequest:
        """The original ChatRequest."""
        return self._request

    @property
    def response(self) -> ChatResponse:
        """
        The final ChatResponse, available after iteration completes.

        Always present after iteration, even on errors. Check
        ``response.is_success()`` / ``response.is_error()`` /
        ``response.is_timeout()`` to determine the outcome.
        On non-success, ``response.result`` holds the raw accumulated
        text and ``response.error`` describes what went wrong.

        Raises:
            RuntimeError: If accessed before the stream is fully consumed.
        """
        if self._response is None:
            raise RuntimeError(
                "ChatResponseStream.response is not available until the stream is fully consumed. "
                "Iterate over the stream first."
            )
        return self._response

    @property
    def accumulated_text(self) -> str:
        """Text accumulated so far (useful during iteration)."""
        return "".join(self._accumulated_parts)

    def __enter__(self) -> ChatResponseStream:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __iter__(self) -> Iterator[ChatResponseStreamEvent]:
        """
        Iterate SSE events from the streaming response.

        Consumable only once. Yields ``ChatResponseStreamEvent`` objects parsed
        from the SSE stream. After iteration completes, ``self.response``
        becomes available.

        Following the SDK design principle of "requests in, responses out",
        iteration **never** propagates exceptions to the caller. Any error
        (SSE or handler) is captured in the final ``ChatResponse`` with an
        appropriate status (ERROR or TIMEOUT). In both cases, ``result``
        holds the raw accumulated text so the caller can inspect partial
        or full content regardless of the outcome.

        Yields:
            ChatResponseStreamEvent for each SSE event.

        Raises:
            RuntimeError: If iterated more than once.
        """
        if self._iterated:
            raise RuntimeError("ChatResponseStream can only be iterated once.")
        self._iterated = True

        try:
            yield from self._parse_sse_stream()
        except Exception as e:
            # SSE failed: build an error response with partial text (no handler).
            self._build_error_response(e)
            return
        # SSE completed: build a success response (handler runs here).
        self._build_response()

    @property
    def text_stream(self) -> Iterator[str]:
        """
        Convenience iterator that yields only text chunks from DELTA events.

        Example:
            >>> with agent.chat_stream(request) as stream:
            ...     for text in stream.text_stream:
            ...         print(text, end="", flush=True)
        """
        for event in self:
            if event.is_delta and event.text:
                yield event.text

    def until_done(self) -> None:
        """Consume the stream silently, discarding all events.

        After this call, ``self.response`` is available.

        Example:
            >>> with agent.chat_stream(request) as stream:
            ...     stream.until_done()
            ...     print(stream.response.result)
        """
        for _ in self:
            pass

    def get_final_response(self) -> ChatResponse:
        """Consume the stream and return the final ``ChatResponse``.

        Equivalent to calling ``until_done()`` followed by ``self.response``.
        The returned response is always present — check its status to
        determine whether the stream completed successfully.

        Example:
            >>> with agent.chat_stream(request) as stream:
            ...     response = stream.get_final_response()
            ...     if response.is_success():
            ...         print(response.result)
            ...     else:
            ...         print(f"Error: {response.error}")
        """
        self.until_done()
        return self.response

    def close(self) -> None:
        """Close the underlying HTTP connection."""
        if not self._closed:
            self._closed = True
            self._http_response.close()

    def _parse_sse_stream(self) -> Iterator[ChatResponseStreamEvent]:
        """Parse the SSE stream from the HTTP response."""
        event_type: str | None = None
        data_buffer: list[str] = []

        for line in self._http_response.iter_lines(decode_unicode=True):
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
        if text:
            self._accumulated_parts.append(text)

        return ChatResponseStreamEvent(
            type=ChatResponseStreamEventType.DELTA,
            text=text,
            raw_data=parsed_data if isinstance(parsed_data, dict) else {"raw": data},
        )

    @staticmethod
    def _extract_delta_text(data: dict[str, Any]) -> str:
        """Extract text content from a delta event.

        Supports the LiteLLM/OpenAI-compatible format
        (``choices[0].delta.content``) used by StackSpot AI,
        with fallback to flat fields for forward-compatibility.
        """
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
        for field in ("conversation_id", "tokens", "knowledge_source_id"):
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

    def _build_response(self) -> None:
        """Build the final ``ChatResponse`` after successful SSE iteration.

        If a ``result_handler`` was provided, the accumulated text is
        processed through it (same as ``Agent.chat()``).
        If the handler fails, the response is built with ERROR status and
        ``result`` is set to the raw accumulated text so the caller can
        still inspect what the Agent returned.
        """
        if self._response is not None:
            return

        accumulated = self.accumulated_text
        raw_response = self._build_raw_response(accumulated)

        # Apply result handler (same pattern as Agent._do_chat)
        result: Any = accumulated
        if self._result_handler:
            from stkai.agents._handlers import ChatResultContext
            context = ChatResultContext(request=self._request, raw_result=accumulated)
            try:
                result = self._result_handler.handle_result(context)
            except Exception as e:
                handler_name = type(self._result_handler).__name__
                error_msg = f"Result handler '{handler_name}' failed: {e}"
                logger.error(f"{self._request.id} | Agent | ❌ {error_msg}")
                self._response = ChatResponse(
                    request=self._request,
                    status=ChatStatus.ERROR,
                    result=accumulated,
                    error=error_msg,
                    raw_response=raw_response,
                )
                return

        self._response = ChatResponse(
            request=self._request,
            status=ChatStatus.SUCCESS,
            result=result,
            raw_response=raw_response,
        )

    def _build_error_response(self, error: Exception) -> None:
        """Build an error ``ChatResponse`` from an SSE failure.

        The result handler is intentionally **not** applied here because
        the accumulated text is likely incomplete (e.g. half a JSON payload)
        and feeding it to a handler would be misleading.

        ``result`` is set to the raw accumulated text so the caller can
        still recover whatever partial content was received before the failure.
        """
        if self._response is not None:
            return

        accumulated = self.accumulated_text
        raw_response = self._build_raw_response(accumulated)
        status = ChatStatus.from_exception(error)
        error_msg = f"Streaming failed: {error}"
        logger.error(f"{self._request.id} | Agent | ❌ {error_msg}")

        self._response = ChatResponse(
            request=self._request,
            status=status,
            result=accumulated,
            error=error_msg,
            raw_response=raw_response,
        )

    def _build_raw_response(self, accumulated: str) -> dict[str, Any]:
        """Build the raw_response dict from accumulated text and DONE metadata."""
        raw_response: dict[str, Any] = {"message": accumulated}
        if self._raw_done_data:
            for key in ("conversation_id", "tokens", "stop_reason", "knowledge_source_id"):
                if key in self._raw_done_data:
                    raw_response[key] = self._raw_done_data[key]
        return raw_response

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
