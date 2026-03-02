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

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from stkai.agents._sse_parser import SseEventParser

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
        event_parser: SseEventParser | None = None,
        on_response: Callable[[ChatResponse], None] | None = None,
    ) -> None:
        self._request = request
        self._http_response = http_response
        self._result_handler = result_handler
        self._on_response = on_response
        self._accumulated_parts: list[str] = []
        self._response: ChatResponse | None = None
        self._closed = False
        self._iterated = False

        if event_parser is not None:
            self._event_parser = event_parser
        else:
            # Lazy import to avoid circular dependency (_sse_parser imports from _stream)
            from stkai.agents._sse_parser import SseEventParser
            self._event_parser = SseEventParser()

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
            lines = self._http_response.iter_lines(decode_unicode=True)
            for event in self._event_parser.parse(lines):
                if event.is_delta and event.text:
                    self._accumulated_parts.append(event.text)
                yield event
        except Exception as e:
            # SSE failed: build an error response with partial text (no handler).
            self._build_error_response(e)
            return
        # SSE completed: build a success response (handler runs here).
        self._build_response()
        if self._on_response is not None and self._response is not None:
            self._on_response(self._response)

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
        metadata = self._event_parser.metadata
        if metadata:
            for key in ("conversation_id", "tokens", "stop_reason", "knowledge_source_id"):
                if key in metadata:
                    raw_response[key] = metadata[key]
        return raw_response
