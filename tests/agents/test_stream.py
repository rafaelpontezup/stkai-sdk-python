"""Tests for Agent streaming support."""

import unittest
from typing import Any
from unittest.mock import MagicMock

import requests

from stkai import HttpClient
from stkai.agents import (
    Agent,
    AgentOptions,
    ChatRequest,
    ChatResponseStream,
    ChatResponseStreamEvent,
    ChatResponseStreamEventType,
    UseConversation,
)

# =============================================================================
# Test Helpers
# =============================================================================


def make_sse_lines(events: list[tuple[str | None, str]]) -> list[str]:
    """
    Build raw SSE lines from a list of (event_type, data) tuples.

    Each event is separated by an empty line (as per SSE spec).
    """
    lines: list[str] = []
    for event_type, data in events:
        if event_type:
            lines.append(f"event: {event_type}")
        lines.append(f"data: {data}")
        lines.append("")  # empty line = event boundary
    return lines


def make_stream_response(
    sse_lines: list[str],
    status_code: int = 200,
) -> MagicMock:
    """Create a mock requests.Response with iter_lines returning SSE data."""
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.iter_lines.return_value = iter(sse_lines)
    response.raise_for_status.return_value = None
    return response


class StreamingMockHttpClient(HttpClient):
    """Mock HTTP client that supports post_stream()."""

    def __init__(
        self,
        stream_response: MagicMock | None = None,
        status_code: int = 200,
    ):
        self.stream_response = stream_response
        self.status_code = status_code
        self.stream_calls: list[tuple[str, dict | None, int]] = []
        self.post_calls: list[tuple[str, dict | None, int]] = []

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        raise NotImplementedError

    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        self.post_calls.append((url, data, timeout))
        response = MagicMock(spec=requests.Response)
        response.status_code = self.status_code
        response.json.return_value = {"message": "non-streaming"}
        response.text = "non-streaming"
        response.raise_for_status.return_value = None
        return response

    def post_stream(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        self.stream_calls.append((url, data, timeout))
        assert self.stream_response is not None, "stream_response not configured"
        return self.stream_response


# =============================================================================
# ChatResponseStreamEvent Tests
# =============================================================================


class TestChatResponseStreamEvent(unittest.TestCase):
    """Tests for ChatResponseStreamEvent data class."""

    def test_delta_event_properties(self):
        """DELTA event should have is_delta=True."""
        event = ChatResponseStreamEvent(type=ChatResponseStreamEventType.DELTA, text="hello")

        self.assertTrue(event.is_delta)
        self.assertFalse(event.is_done)
        self.assertFalse(event.is_error)
        self.assertEqual(event.text, "hello")

    def test_done_event_properties(self):
        """DONE event should have is_done=True."""
        event = ChatResponseStreamEvent(type=ChatResponseStreamEventType.DONE)

        self.assertTrue(event.is_done)
        self.assertFalse(event.is_delta)
        self.assertFalse(event.is_error)

    def test_error_event_properties(self):
        """ERROR event should have is_error=True."""
        event = ChatResponseStreamEvent(
            type=ChatResponseStreamEventType.ERROR, error="something went wrong"
        )

        self.assertTrue(event.is_error)
        self.assertFalse(event.is_delta)
        self.assertFalse(event.is_done)
        self.assertEqual(event.error, "something went wrong")

    def test_is_frozen(self):
        """Should be immutable."""
        event = ChatResponseStreamEvent(type=ChatResponseStreamEventType.DELTA, text="hello")

        with self.assertRaises(AttributeError):
            event.text = "world"  # type: ignore


class TestChatResponseStreamEventType(unittest.TestCase):
    """Tests for ChatResponseStreamEventType enum."""

    def test_values(self):
        self.assertEqual(ChatResponseStreamEventType.DELTA, "delta")
        self.assertEqual(ChatResponseStreamEventType.DONE, "done")
        self.assertEqual(ChatResponseStreamEventType.ERROR, "error")


# =============================================================================
# ChatResponseStream Tests
# =============================================================================


class TestChatResponseStream(unittest.TestCase):
    """Tests for ChatResponseStream context manager and iterator."""

    def test_iterates_delta_events(self):
        """Should yield DELTA events with text content."""
        sse_lines = make_sse_lines([
            (None, '{"content": "Hello"}'),
            (None, '{"content": " world"}'),
            ("done", '{"type": "done", "conversation_id": "conv-1"}'),
        ])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            events = list(stream)

        deltas = [e for e in events if e.is_delta]
        self.assertEqual(len(deltas), 2)
        self.assertEqual(deltas[0].text, "Hello")
        self.assertEqual(deltas[1].text, " world")

    def test_accumulated_text(self):
        """Should accumulate text from all DELTA events."""
        sse_lines = make_sse_lines([
            (None, '{"content": "Hello"}'),
            (None, '{"content": " world"}'),
            ("done", '{"type": "done"}'),
        ])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            for _ in stream:
                pass

        self.assertEqual(stream.accumulated_text, "Hello world")

    def test_accumulated_text_during_iteration(self):
        """Should show partial accumulation during iteration."""
        sse_lines = make_sse_lines([
            (None, '{"content": "A"}'),
            (None, '{"content": "B"}'),
            (None, '{"content": "C"}'),
            ("done", '{"type": "done"}'),
        ])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        accumulated_snapshots = []
        with ChatResponseStream(request=request, http_response=http_response) as stream:
            for event in stream:
                if event.is_delta:
                    accumulated_snapshots.append(stream.accumulated_text)

        self.assertEqual(accumulated_snapshots, ["A", "AB", "ABC"])

    def test_response_available_after_iteration(self):
        """Should build ChatResponse after iteration completes."""
        sse_lines = make_sse_lines([
            (None, '{"content": "Result"}'),
            ("done", '{"type": "done", "conversation_id": "conv-1", "tokens": {"user": 10, "enrichment": 5, "output": 20}, "stop_reason": "stop"}'),
        ])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            for _ in stream:
                pass

        response = stream.response
        self.assertTrue(response.is_success())
        self.assertEqual(response.result, "Result")
        self.assertEqual(response.raw_result, "Result")
        self.assertEqual(response.conversation_id, "conv-1")
        self.assertEqual(response.stop_reason, "stop")
        self.assertIsNotNone(response.tokens)
        self.assertEqual(response.tokens.total, 35)
        self.assertIs(response.request, request)

    def test_response_not_available_before_iteration(self):
        """Should raise RuntimeError if response accessed before iteration."""
        sse_lines = make_sse_lines([(None, '{"content": "Hello"}')])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        stream = ChatResponseStream(request=request, http_response=http_response)

        with self.assertRaises(RuntimeError) as ctx:
            _ = stream.response

        self.assertIn("not available", str(ctx.exception))

    def test_cannot_iterate_twice(self):
        """Should raise RuntimeError on second iteration."""
        sse_lines = make_sse_lines([
            (None, '{"content": "Hello"}'),
            ("done", '{"type": "done"}'),
        ])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        stream = ChatResponseStream(request=request, http_response=http_response)
        list(stream)  # first iteration

        with self.assertRaises(RuntimeError) as ctx:
            list(stream)

        self.assertIn("only be iterated once", str(ctx.exception))

    def test_context_manager_closes_connection(self):
        """Should close HTTP response on __exit__."""
        sse_lines = make_sse_lines([(None, '{"content": "Hello"}')])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            for _ in stream:
                pass

        http_response.close.assert_called_once()

    def test_context_manager_closes_on_exception(self):
        """Should close HTTP response even if an exception occurs."""
        sse_lines = make_sse_lines([(None, '{"content": "Hello"}')])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        try:
            with ChatResponseStream(request=request, http_response=http_response):
                raise ValueError("test error")
        except ValueError:
            pass

        http_response.close.assert_called_once()

    def test_context_manager_closes_on_break(self):
        """Should close HTTP response when caller breaks out of iteration."""
        sse_lines = make_sse_lines([
            (None, '{"content": "A"}'),
            (None, '{"content": "B"}'),
            (None, '{"content": "C"}'),
        ])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            for event in stream:
                if event.is_delta and event.text == "A":
                    break

        http_response.close.assert_called_once()

    def test_until_done_consumes_stream_silently(self):
        """until_done() should consume stream and make response available."""
        sse_lines = make_sse_lines([
            (None, '{"content": "Hello"}'),
            (None, '{"content": " world"}'),
            ("done", '{"type": "done", "conversation_id": "conv-1"}'),
        ])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            stream.until_done()

        self.assertEqual(stream.accumulated_text, "Hello world")
        self.assertTrue(stream.response.is_success())
        self.assertEqual(stream.response.result, "Hello world")

    def test_get_final_response_returns_chat_response(self):
        """get_final_response() should consume stream and return ChatResponse."""
        sse_lines = make_sse_lines([
            (None, '{"content": "Result"}'),
            ("done", '{"type": "done", "tokens": {"user": 10, "enrichment": 5, "output": 20}}'),
        ])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            response = stream.get_final_response()

        self.assertTrue(response.is_success())
        self.assertEqual(response.result, "Result")
        self.assertIsNotNone(response.tokens)
        self.assertEqual(response.tokens.total, 35)
        self.assertIs(response.request, request)

    def test_get_final_response_is_same_as_response_property(self):
        """get_final_response() should return the same object as .response."""
        sse_lines = make_sse_lines([
            (None, '{"content": "Hi"}'),
            ("done", '{"type": "done"}'),
        ])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            response = stream.get_final_response()

        self.assertIs(response, stream.response)

    def test_text_stream_yields_only_text(self):
        """text_stream should yield only text from DELTA events."""
        sse_lines = make_sse_lines([
            (None, '{"content": "Hello"}'),
            (None, '{"content": " world"}'),
            ("done", '{"type": "done"}'),
        ])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            texts = list(stream.text_stream)

        self.assertEqual(texts, ["Hello", " world"])

    def test_error_event_in_stream(self):
        """Should yield ERROR event for error SSE events."""
        sse_lines = make_sse_lines([
            (None, '{"content": "partial"}'),
            ("error", '{"type": "error", "message": "server overloaded"}'),
        ])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            events = list(stream)

        error_events = [e for e in events if e.is_error]
        self.assertEqual(len(error_events), 1)
        self.assertEqual(error_events[0].error, "server overloaded")

    def test_plain_text_data(self):
        """Should handle plain text (non-JSON) data as delta text."""
        sse_lines = make_sse_lines([
            (None, "Hello plain text"),
            ("done", '{"type": "done"}'),
        ])
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            events = list(stream)

        deltas = [e for e in events if e.is_delta]
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].text, "Hello plain text")

    def test_empty_stream(self):
        """Should handle empty stream gracefully."""
        http_response = make_stream_response([])
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            events = list(stream)

        self.assertEqual(events, [])
        self.assertEqual(stream.accumulated_text, "")
        response = stream.response
        self.assertTrue(response.is_success())
        self.assertEqual(response.result, "")

    def test_sse_comment_lines_ignored(self):
        """Should ignore SSE comment lines (starting with ':')."""
        lines = [
            ": this is a comment",
            'data: {"content": "Hello"}',
            "",
            ": another comment",
            "event: done",
            'data: {"type": "done"}',
            "",
        ]
        http_response = make_stream_response(lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            events = list(stream)

        deltas = [e for e in events if e.is_delta]
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].text, "Hello")


# =============================================================================
# ChatResponseStream Tests — LiteLLM/OpenAI Format (StackSpot AI)
# =============================================================================


class TestChatResponseStreamLiteLLMFormat(unittest.TestCase):
    """Tests for ChatResponseStream with LiteLLM/OpenAI-compatible SSE format.

    StackSpot AI uses LiteLLM under the hood, which produces SSE events in the
    OpenAI-compatible format: choices[0].delta.content for text chunks and
    data: [DONE] for stream termination.
    """

    def _make_litellm_chunk(self, content: str, finish_reason: str | None = None) -> str:
        """Build a LiteLLM/OpenAI-compatible SSE data payload."""
        import json
        chunk: dict[str, Any] = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "choices": [{
                "index": 0,
                "delta": {"content": content} if content else {},
                "finish_reason": finish_reason,
            }],
        }
        return json.dumps(chunk)

    def test_parses_litellm_delta_content(self):
        """Should extract text from choices[0].delta.content."""
        sse_lines = [
            f"data: {self._make_litellm_chunk('Hello')}",
            "",
            f"data: {self._make_litellm_chunk(' world')}",
            "",
            "data: [DONE]",
            "",
        ]
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            texts = list(stream.text_stream)

        self.assertEqual(texts, ["Hello", " world"])
        self.assertEqual(stream.accumulated_text, "Hello world")

    def test_done_signal(self):
        """Should recognize data: [DONE] as stream termination."""
        sse_lines = [
            f"data: {self._make_litellm_chunk('Hi')}",
            "",
            "data: [DONE]",
            "",
        ]
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            events = list(stream)

        done_events = [e for e in events if e.is_done]
        self.assertEqual(len(done_events), 1)

    def test_finish_reason_tracked_as_stop_reason(self):
        """Should track finish_reason from last chunk as stop_reason in response."""
        sse_lines = [
            f"data: {self._make_litellm_chunk('Hello')}",
            "",
            f"data: {self._make_litellm_chunk('', finish_reason='stop')}",
            "",
            "data: [DONE]",
            "",
        ]
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            for _ in stream:
                pass

        self.assertEqual(stream.response.stop_reason, "stop")

    def test_usage_tracked_from_chunk(self):
        """Should track usage data from chunks into response tokens."""
        import json
        chunk_with_usage = json.dumps({
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        })
        sse_lines = [
            f"data: {self._make_litellm_chunk('Result')}",
            "",
            f"data: {chunk_with_usage}",
            "",
            "data: [DONE]",
            "",
        ]
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            for _ in stream:
                pass

        tokens = stream.response.tokens
        self.assertIsNotNone(tokens)
        self.assertEqual(tokens.user, 10)
        self.assertEqual(tokens.output, 20)
        self.assertEqual(tokens.total, 30)

    def test_conversation_id_tracked_from_chunk(self):
        """Should track conversation_id from StackSpot-specific chunk fields."""
        import json
        chunk_with_conv = json.dumps({
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"content": "Hi"}}],
            "conversation_id": "conv-123",
        })
        sse_lines = [
            f"data: {chunk_with_conv}",
            "",
            "data: [DONE]",
            "",
        ]
        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        with ChatResponseStream(request=request, http_response=http_response) as stream:
            for _ in stream:
                pass

        self.assertEqual(stream.response.conversation_id, "conv-123")

    def test_full_litellm_stream_flow(self):
        """End-to-end test simulating a full LiteLLM streaming response."""
        import json

        chunks = [
            {"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]},
            {"choices": [{"index": 0, "delta": {"content": "Hello"}}]},
            {"choices": [{"index": 0, "delta": {"content": "!"}}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}},
        ]

        sse_lines = []
        for chunk in chunks:
            sse_lines.append(f"data: {json.dumps(chunk)}")
            sse_lines.append("")
        sse_lines.append("data: [DONE]")
        sse_lines.append("")

        http_response = make_stream_response(sse_lines)
        request = ChatRequest(user_prompt="Hi")

        collected_text = []
        with ChatResponseStream(request=request, http_response=http_response) as stream:
            for text in stream.text_stream:
                collected_text.append(text)

        self.assertEqual(collected_text, ["Hello", "!"])
        self.assertEqual(stream.accumulated_text, "Hello!")

        response = stream.response
        self.assertTrue(response.is_success())
        self.assertEqual(response.result, "Hello!")
        self.assertEqual(response.stop_reason, "stop")
        self.assertIsNotNone(response.tokens)
        self.assertEqual(response.tokens.user, 5)
        self.assertEqual(response.tokens.output, 2)


# =============================================================================
# Agent.chat_stream() Tests
# =============================================================================


class TestAgentChatResponseStream(unittest.TestCase):
    """Tests for Agent.chat_stream() method."""

    def test_chat_stream_returns_chat_stream(self):
        """Should return a ChatResponseStream instance."""
        sse_lines = make_sse_lines([
            (None, '{"content": "Hello"}'),
            ("done", '{"type": "done"}'),
        ])
        mock_client = StreamingMockHttpClient(
            stream_response=make_stream_response(sse_lines)
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        stream = agent.chat_stream(ChatRequest(user_prompt="Hi"))

        self.assertIsInstance(stream, ChatResponseStream)
        # Must close since we didn't use context manager
        stream.close()

    def test_chat_stream_sends_streaming_true_in_payload(self):
        """Should set streaming=True in the API payload."""
        sse_lines = make_sse_lines([
            (None, '{"content": "Hello"}'),
            ("done", '{"type": "done"}'),
        ])
        mock_client = StreamingMockHttpClient(
            stream_response=make_stream_response(sse_lines)
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        with agent.chat_stream(ChatRequest(user_prompt="Hi")) as stream:
            for _ in stream:
                pass

        _, payload, _ = mock_client.stream_calls[0]
        self.assertTrue(payload["streaming"])

    def test_chat_stream_sends_to_correct_url(self):
        """Should send request to the correct agent URL."""
        sse_lines = make_sse_lines([("done", '{"type": "done"}')])
        mock_client = StreamingMockHttpClient(
            stream_response=make_stream_response(sse_lines)
        )
        agent = Agent(agent_id="test-agent", http_client=mock_client)

        with agent.chat_stream(ChatRequest(user_prompt="Hi")) as stream:
            list(stream)

        url, _, _ = mock_client.stream_calls[0]
        self.assertIn("/v1/agent/test-agent/chat", url)

    def test_chat_stream_uses_custom_timeout(self):
        """Should use timeout from options."""
        sse_lines = make_sse_lines([("done", '{"type": "done"}')])
        mock_client = StreamingMockHttpClient(
            stream_response=make_stream_response(sse_lines)
        )
        options = AgentOptions(request_timeout=120)
        agent = Agent(agent_id="my-agent", options=options, http_client=mock_client)

        with agent.chat_stream(ChatRequest(user_prompt="Hi")) as stream:
            list(stream)

        _, _, timeout = mock_client.stream_calls[0]
        self.assertEqual(timeout, 120)

    def test_chat_stream_uses_post_stream_not_post(self):
        """Should use post_stream(), not post()."""
        sse_lines = make_sse_lines([("done", '{"type": "done"}')])
        mock_client = StreamingMockHttpClient(
            stream_response=make_stream_response(sse_lines)
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        with agent.chat_stream(ChatRequest(user_prompt="Hi")) as stream:
            list(stream)

        self.assertEqual(len(mock_client.stream_calls), 1)
        self.assertEqual(len(mock_client.post_calls), 0)

    def test_chat_stream_raises_on_http_error(self):
        """Should raise HTTPError on non-2xx status."""
        response = MagicMock(spec=requests.Response)
        response.status_code = 500
        response.text = "Internal Server Error"
        response.raise_for_status.side_effect = requests.HTTPError(response=response)

        mock_client = StreamingMockHttpClient(stream_response=response)
        options = AgentOptions(retry_max_retries=0)
        agent = Agent(agent_id="my-agent", options=options, http_client=mock_client)

        with self.assertRaises(requests.HTTPError):
            agent.chat_stream(ChatRequest(user_prompt="Hi"))

    def test_chat_stream_with_use_conversation(self):
        """Should capture conversation_id from stream DONE event."""
        sse_lines = make_sse_lines([
            (None, '{"content": "Hello"}'),
            ("done", '{"type": "done", "conversation_id": "conv-from-stream"}'),
        ])
        mock_client = StreamingMockHttpClient(
            stream_response=make_stream_response(sse_lines)
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        with UseConversation() as conv:
            with agent.chat_stream(ChatRequest(user_prompt="Hi")) as stream:
                for _ in stream:
                    pass

        self.assertEqual(conv.conversation_id, "conv-from-stream")

    def test_chat_stream_with_use_conversation_sends_conversation_id(self):
        """Should send conversation_id in payload when UseConversation has one."""
        sse_lines = make_sse_lines([("done", '{"type": "done"}')])
        mock_client = StreamingMockHttpClient(
            stream_response=make_stream_response(sse_lines)
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        with UseConversation(conversation_id="01JMEXAMPLE00000000000000"):
            with agent.chat_stream(ChatRequest(user_prompt="Hi")) as stream:
                list(stream)

        _, payload, _ = mock_client.stream_calls[0]
        self.assertTrue(payload["use_conversation"])
        self.assertEqual(payload["conversation_id"], "01JMEXAMPLE00000000000000")

    def test_chat_stream_explicit_conversation_id_takes_precedence(self):
        """Explicit conversation_id on ChatRequest should take precedence over UseConversation."""
        sse_lines = make_sse_lines([("done", '{"type": "done"}')])
        mock_client = StreamingMockHttpClient(
            stream_response=make_stream_response(sse_lines)
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        with UseConversation(conversation_id="01JMFROMCONVERSATION00000"):
            request = ChatRequest(
                user_prompt="Hi",
                conversation_id="explicit-id",
            )
            with agent.chat_stream(request) as stream:
                list(stream)

        _, payload, _ = mock_client.stream_calls[0]
        self.assertEqual(payload["conversation_id"], "explicit-id")

    def test_chat_stream_preserves_request_payload_fields(self):
        """Should preserve all ChatRequest fields in the payload."""
        sse_lines = make_sse_lines([("done", '{"type": "done"}')])
        mock_client = StreamingMockHttpClient(
            stream_response=make_stream_response(sse_lines)
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        request = ChatRequest(
            user_prompt="Hello!",
            use_knowledge_sources=False,
            return_knowledge_sources=True,
        )
        with agent.chat_stream(request) as stream:
            list(stream)

        _, payload, _ = mock_client.stream_calls[0]
        self.assertEqual(payload["user_prompt"], "Hello!")
        self.assertTrue(payload["streaming"])
        self.assertEqual(payload["stackspot_knowledge"], "false")
        self.assertTrue(payload["return_ks_in_response"])


# =============================================================================
# Result Handler Tests
# =============================================================================


class TestChatResponseStreamResultHandler(unittest.TestCase):
    """Tests for result_handler support in ChatResponseStream."""

    def test_result_handler_applied_to_final_response(self):
        """Result handler should transform accumulated text in the final response."""
        from stkai.agents import JSON_RESULT_HANDLER

        sse_lines = make_sse_lines([
            (None, '{"choices":[{"delta":{"content":"{\\"name\\": \\"Alice\\"}"}}]}'),
            (None, "[DONE]"),
        ])
        stream = ChatResponseStream(
            request=ChatRequest(user_prompt="Give me JSON"),
            http_response=make_stream_response(sse_lines),
            result_handler=JSON_RESULT_HANDLER,
        )

        with stream:
            stream.until_done()

        self.assertEqual(stream.response.result, {"name": "Alice"})

    def test_no_result_handler_returns_raw_text(self):
        """Without result handler, result should be the raw accumulated text."""
        sse_lines = make_sse_lines([
            (None, '{"choices":[{"delta":{"content":"Hello world"}}]}'),
            (None, "[DONE]"),
        ])
        stream = ChatResponseStream(
            request=ChatRequest(user_prompt="Hi"),
            http_response=make_stream_response(sse_lines),
        )

        with stream:
            response = stream.get_final_response()

        self.assertEqual(response.result, "Hello world")

    def test_result_handler_with_multipart_json(self):
        """Result handler should work with JSON accumulated across multiple chunks."""
        from stkai.agents import JSON_RESULT_HANDLER

        sse_lines = make_sse_lines([
            (None, '{"choices":[{"delta":{"content":"{\\"items\\": "}}]}'),
            (None, '{"choices":[{"delta":{"content":"[1, 2, 3]}"}}]}'),
            (None, "[DONE]"),
        ])
        stream = ChatResponseStream(
            request=ChatRequest(user_prompt="Give me list"),
            http_response=make_stream_response(sse_lines),
            result_handler=JSON_RESULT_HANDLER,
        )

        with stream:
            stream.until_done()

        self.assertEqual(stream.response.result, {"items": [1, 2, 3]})

    def test_result_handler_receives_correct_context(self):
        """Result handler should receive the original request and accumulated text."""
        from stkai.agents import ChatResultContext, ChatResultHandler

        captured_contexts: list[ChatResultContext] = []

        class SpyHandler(ChatResultHandler):
            def handle_result(self, context: ChatResultContext) -> str:
                captured_contexts.append(context)
                return context.raw_result.upper()

        request = ChatRequest(user_prompt="Hello spy")
        sse_lines = make_sse_lines([
            (None, '{"choices":[{"delta":{"content":"hello"}}]}'),
            (None, "[DONE]"),
        ])
        stream = ChatResponseStream(
            request=request,
            http_response=make_stream_response(sse_lines),
            result_handler=SpyHandler(),
        )

        with stream:
            stream.until_done()

        self.assertEqual(len(captured_contexts), 1)
        self.assertIs(captured_contexts[0].request, request)
        self.assertEqual(captured_contexts[0].raw_result, "hello")
        self.assertEqual(stream.response.result, "HELLO")

    def test_result_handler_error_produces_error_response(self):
        """Handler errors should produce an ERROR response, not raise exceptions."""
        from stkai.agents import ChatResultHandler

        class FailingHandler(ChatResultHandler):
            def handle_result(self, context: Any) -> None:
                raise ValueError("handler failed")

        sse_lines = make_sse_lines([
            (None, '{"choices":[{"delta":{"content":"data"}}]}'),
            (None, "[DONE]"),
        ])
        stream = ChatResponseStream(
            request=ChatRequest(user_prompt="Hi"),
            http_response=make_stream_response(sse_lines),
            result_handler=FailingHandler(),
        )

        with stream:
            response = stream.get_final_response()

        self.assertTrue(response.is_error())
        self.assertIn("FailingHandler", response.error)
        self.assertIn("handler failed", response.error)
        # Partial (raw) text is still available as the result
        self.assertEqual(response.result, "data")

    def test_sse_error_produces_error_response_without_running_handler(self):
        """SSE errors should produce an ERROR response; handler should NOT run."""
        from stkai.agents import ChatResultHandler

        handler_called = False

        class SpyHandler(ChatResultHandler):
            def handle_result(self, context: Any) -> str:
                nonlocal handler_called
                handler_called = True
                return context.raw_result

        # Create a response whose iter_lines raises mid-stream
        response = MagicMock(spec=requests.Response)
        response.status_code = 200
        response.raise_for_status.return_value = None

        def exploding_iter(*args: Any, **kwargs: Any) -> Any:
            yield 'data: {"choices":[{"delta":{"content":"partial"}}]}'
            yield ""
            raise ConnectionError("connection lost")

        response.iter_lines = exploding_iter

        stream = ChatResponseStream(
            request=ChatRequest(user_prompt="Hi"),
            http_response=response,
            result_handler=SpyHandler(),
        )

        with stream:
            for _ in stream:
                pass

        self.assertFalse(handler_called, "Handler should NOT run on SSE error")
        self.assertTrue(stream.response.is_error())
        self.assertIn("connection lost", stream.response.error)
        # Partial text is still available
        self.assertEqual(stream.response.result, "partial")

    def test_sse_timeout_produces_timeout_response(self):
        """Timeout during SSE should produce a TIMEOUT status response."""
        response = MagicMock(spec=requests.Response)
        response.status_code = 200
        response.raise_for_status.return_value = None

        def timeout_iter(*args: Any, **kwargs: Any) -> Any:
            yield 'data: {"choices":[{"delta":{"content":"before timeout"}}]}'
            yield ""
            raise requests.exceptions.ReadTimeout("read timed out")

        response.iter_lines = timeout_iter

        stream = ChatResponseStream(
            request=ChatRequest(user_prompt="Hi"),
            http_response=response,
        )

        with stream:
            for _ in stream:
                pass

        self.assertTrue(stream.response.is_timeout())
        self.assertIn("read timed out", stream.response.error)
        self.assertEqual(stream.response.result, "before timeout")

    def test_accumulated_text_unaffected_by_result_handler(self):
        """accumulated_text should return raw text regardless of result handler."""
        from stkai.agents import JSON_RESULT_HANDLER

        sse_lines = make_sse_lines([
            (None, '{"choices":[{"delta":{"content":"{\\"ok\\": true}"}}]}'),
            (None, "[DONE]"),
        ])
        stream = ChatResponseStream(
            request=ChatRequest(user_prompt="JSON please"),
            http_response=make_stream_response(sse_lines),
            result_handler=JSON_RESULT_HANDLER,
        )

        with stream:
            stream.until_done()
            # accumulated_text is always raw string
            self.assertEqual(stream.accumulated_text, '{"ok": true}')
            # result is parsed dict
            self.assertEqual(stream.response.result, {"ok": True})


class TestAgentChatStreamResultHandler(unittest.TestCase):
    """Tests for result_handler passed via Agent.chat_stream()."""

    def test_chat_stream_with_json_result_handler(self):
        """Agent.chat_stream() should pass result_handler to ChatResponseStream."""
        from stkai.agents import JSON_RESULT_HANDLER

        sse_lines = make_sse_lines([
            (None, '{"choices":[{"delta":{"content":"{\\"status\\": \\"ok\\"}"}}]}'),
            (None, "[DONE]"),
        ])
        mock_client = StreamingMockHttpClient(
            stream_response=make_stream_response(sse_lines)
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        with agent.chat_stream(
            ChatRequest(user_prompt="JSON"),
            result_handler=JSON_RESULT_HANDLER,
        ) as stream:
            response = stream.get_final_response()

        self.assertEqual(response.result, {"status": "ok"})

    def test_chat_stream_without_result_handler(self):
        """Agent.chat_stream() without result_handler returns raw text."""
        sse_lines = make_sse_lines([
            (None, '{"choices":[{"delta":{"content":"plain text"}}]}'),
            (None, "[DONE]"),
        ])
        mock_client = StreamingMockHttpClient(
            stream_response=make_stream_response(sse_lines)
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        with agent.chat_stream(ChatRequest(user_prompt="Hi")) as stream:
            response = stream.get_final_response()

        self.assertEqual(response.result, "plain text")

    def test_chat_stream_result_handler_with_use_conversation(self):
        """result_handler should work alongside UseConversation."""
        from stkai.agents import JSON_RESULT_HANDLER

        sse_lines = make_sse_lines([
            (None, '{"choices":[{"delta":{"content":"{\\"answer\\": 42}"}}]}'),
            ("done", '{"type": "done", "conversation_id": "conv-123"}'),
        ])
        mock_client = StreamingMockHttpClient(
            stream_response=make_stream_response(sse_lines)
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        with UseConversation() as conv:
            with agent.chat_stream(
                ChatRequest(user_prompt="Answer"),
                result_handler=JSON_RESULT_HANDLER,
            ) as stream:
                response = stream.get_final_response()

        self.assertEqual(response.result, {"answer": 42})
        self.assertEqual(conv.conversation_id, "conv-123")


if __name__ == "__main__":
    unittest.main()
