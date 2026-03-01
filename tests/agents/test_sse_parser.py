"""Tests for SseEventParser — isolated SSE parsing with plain string lists."""

import json
import unittest
from typing import Any

from stkai.agents._sse_parser import SseEventParser
from stkai.agents._stream import ChatResponseStreamEventType

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


def make_litellm_chunk(content: str, finish_reason: str | None = None) -> str:
    """Build a LiteLLM/OpenAI-compatible SSE data payload."""
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


def make_stackspot_chunk(message: str, **extra: Any) -> str:
    """Build a StackSpot native SSE data payload."""
    base: dict[str, Any] = {
        "upload_ids": {},
        "knowledge_source_id": [],
        "source": [],
        "cross_account_source": [],
        "tools_id": [],
        "agent_info": [],
    }
    chunk = {**base, "message": message, **extra}
    return json.dumps(chunk)


def collect_events(lines: list[str]) -> list[Any]:
    """Parse SSE lines and return all events as a list."""
    parser = SseEventParser(lines)
    return list(parser)


# =============================================================================
# SSE Line Parsing Tests
# =============================================================================


class TestSseLineParsing(unittest.TestCase):
    """Tests for basic SSE line parsing (event boundaries, comments, fields)."""

    def test_empty_input(self):
        """Should yield no events for empty input."""
        events = collect_events([])
        self.assertEqual(events, [])

    def test_single_data_event(self):
        """Should parse a single data-only SSE event."""
        lines = ['data: {"content": "hello"}', ""]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_delta)
        self.assertEqual(events[0].text, "hello")

    def test_event_boundary_on_empty_line(self):
        """Empty lines should delimit SSE events."""
        lines = [
            'data: {"content": "A"}',
            "",
            'data: {"content": "B"}',
            "",
        ]
        events = collect_events(lines)

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].text, "A")
        self.assertEqual(events[1].text, "B")

    def test_event_with_event_type_field(self):
        """Should parse event: field and use it for event classification."""
        lines = [
            "event: done",
            'data: {"type": "done", "conversation_id": "conv-1"}',
            "",
        ]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_done)

    def test_comment_lines_ignored(self):
        """Lines starting with ':' should be ignored (SSE comments)."""
        lines = [
            ": this is a comment",
            'data: {"content": "Hello"}',
            "",
            ": another comment",
        ]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].text, "Hello")

    def test_unknown_fields_ignored(self):
        """Unknown SSE fields (not event:, data:, or :) should be ignored."""
        lines = [
            "id: 12345",
            "retry: 5000",
            'data: {"content": "Hello"}',
            "",
        ]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].text, "Hello")

    def test_multiline_data(self):
        """Multiple data: lines in one event should be joined with newlines."""
        lines = [
            "data: line1",
            "data: line2",
            "",
        ]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        # Both lines are joined with \n and treated as plain text
        self.assertTrue(events[0].is_delta)
        self.assertEqual(events[0].text, "line1\nline2")

    def test_none_lines_skipped(self):
        """None values in the iterable should be skipped."""
        lines = [None, 'data: {"content": "ok"}', None, ""]  # type: ignore[list-item]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].text, "ok")

    def test_last_event_without_trailing_newline(self):
        """Should handle last event if stream ends without trailing empty line."""
        lines = ['data: {"content": "last"}']
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].text, "last")

    def test_consecutive_empty_lines_do_not_produce_events(self):
        """Multiple consecutive empty lines should not produce empty events."""
        lines = [
            'data: {"content": "A"}',
            "",
            "",
            "",
            'data: {"content": "B"}',
            "",
        ]
        events = collect_events(lines)

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].text, "A")
        self.assertEqual(events[1].text, "B")


# =============================================================================
# LiteLLM/OpenAI Format Tests
# =============================================================================


class TestSseParserLiteLLMFormat(unittest.TestCase):
    """Tests for LiteLLM/OpenAI-compatible SSE format parsing."""

    def test_parses_delta_content(self):
        """Should extract text from choices[0].delta.content."""
        lines = [
            f"data: {make_litellm_chunk('Hello')}",
            "",
            f"data: {make_litellm_chunk(' world')}",
            "",
        ]
        events = collect_events(lines)

        deltas = [e for e in events if e.is_delta]
        self.assertEqual(len(deltas), 2)
        self.assertEqual(deltas[0].text, "Hello")
        self.assertEqual(deltas[1].text, " world")

    def test_done_signal(self):
        """Should recognize data: [DONE] as stream termination."""
        lines = [
            f"data: {make_litellm_chunk('Hi')}",
            "",
            "data: [DONE]",
            "",
        ]
        events = collect_events(lines)

        done_events = [e for e in events if e.is_done]
        self.assertEqual(len(done_events), 1)

    def test_finish_reason_tracked_as_stop_reason(self):
        """Should track finish_reason from chunk as stop_reason in metadata."""
        lines = [
            f"data: {make_litellm_chunk('Hello')}",
            "",
            f"data: {make_litellm_chunk('', finish_reason='stop')}",
            "",
            "data: [DONE]",
            "",
        ]
        parser = SseEventParser(lines)
        list(parser)

        self.assertIsNotNone(parser.metadata)
        self.assertEqual(parser.metadata["stop_reason"], "stop")

    def test_usage_tracked_from_chunk(self):
        """Should track usage data from chunks into metadata tokens."""
        chunk_with_usage = json.dumps({
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        })
        lines = [
            f"data: {make_litellm_chunk('Result')}",
            "",
            f"data: {chunk_with_usage}",
            "",
            "data: [DONE]",
            "",
        ]
        parser = SseEventParser(lines)
        list(parser)

        self.assertIsNotNone(parser.metadata)
        tokens = parser.metadata["tokens"]
        self.assertEqual(tokens["user"], 10)
        self.assertEqual(tokens["output"], 20)
        self.assertEqual(tokens["enrichment"], 0)

    def test_conversation_id_tracked_from_chunk(self):
        """Should track conversation_id from StackSpot-specific chunk fields."""
        chunk_with_conv = json.dumps({
            "id": "chatcmpl-test",
            "choices": [{"index": 0, "delta": {"content": "Hi"}}],
            "conversation_id": "conv-123",
        })
        lines = [f"data: {chunk_with_conv}", "", "data: [DONE]", ""]
        parser = SseEventParser(lines)
        list(parser)

        self.assertIsNotNone(parser.metadata)
        self.assertEqual(parser.metadata["conversation_id"], "conv-123")

    def test_empty_delta_yields_event_with_empty_text(self):
        """Empty delta (no content key) should yield a delta event with empty text."""
        chunk = json.dumps({
            "choices": [{"index": 0, "delta": {}}],
        })
        lines = [f"data: {chunk}", ""]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_delta)
        self.assertEqual(events[0].text, "")

    def test_done_event_carries_accumulated_metadata(self):
        """[DONE] event should carry metadata accumulated from previous chunks."""
        lines = [
            f"data: {make_litellm_chunk('Hi')}",
            "",
            f"data: {make_litellm_chunk('', finish_reason='stop')}",
            "",
            "data: [DONE]",
            "",
        ]
        events = collect_events(lines)

        done = [e for e in events if e.is_done][0]
        self.assertIsNotNone(done.raw_data)
        self.assertEqual(done.raw_data.get("stop_reason"), "stop")

    def test_full_litellm_stream(self):
        """End-to-end test simulating a full LiteLLM streaming response."""
        chunks = [
            {"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]},
            {"choices": [{"index": 0, "delta": {"content": "Hello"}}]},
            {"choices": [{"index": 0, "delta": {"content": "!"}}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}},
        ]

        lines: list[str] = []
        for chunk in chunks:
            lines.append(f"data: {json.dumps(chunk)}")
            lines.append("")
        lines.append("data: [DONE]")
        lines.append("")

        parser = SseEventParser(lines)
        events = list(parser)

        texts = [e.text for e in events if e.is_delta and e.text]
        self.assertEqual(texts, ["Hello", "!"])

        self.assertIsNotNone(parser.metadata)
        self.assertEqual(parser.metadata["stop_reason"], "stop")
        self.assertEqual(parser.metadata["tokens"]["user"], 5)
        self.assertEqual(parser.metadata["tokens"]["output"], 2)


# =============================================================================
# StackSpot Native Format Tests
# =============================================================================


class TestSseParserStackSpotFormat(unittest.TestCase):
    """Tests for StackSpot native SSE format (flat 'message' field)."""

    def test_extracts_text_from_message_field(self):
        """Should extract text from StackSpot's flat 'message' field."""
        lines: list[str] = []
        for msg in ["Olá", ", ", "mundo", "!"]:
            lines.append(f"data: {make_stackspot_chunk(msg)}")
            lines.append("")

        events = collect_events(lines)

        texts = [e.text for e in events if e.is_delta and e.text]
        self.assertEqual(texts, ["Olá", ", ", "mundo", "!"])

    def test_empty_message_yields_empty_text_delta(self):
        """Empty message field should yield a delta with empty text."""
        lines = [f"data: {make_stackspot_chunk('')}", ""]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_delta)
        self.assertEqual(events[0].text, "")

    def test_stop_reason_tracked_from_chunk(self):
        """Should capture stop_reason from a StackSpot chunk."""
        lines = [
            f"data: {make_stackspot_chunk('Hi')}",
            "",
            f"data: {make_stackspot_chunk('', stop_reason='stop')}",
            "",
        ]
        parser = SseEventParser(lines)
        list(parser)

        self.assertIsNotNone(parser.metadata)
        self.assertEqual(parser.metadata["stop_reason"], "stop")

    def test_tokens_tracked_from_chunk(self):
        """Should capture tokens from a StackSpot chunk."""
        lines = [
            f"data: {make_stackspot_chunk('Hi', tokens={'input': 10, 'output': 5})}",
            "",
        ]
        parser = SseEventParser(lines)
        list(parser)

        self.assertIsNotNone(parser.metadata)
        self.assertIn("tokens", parser.metadata)

    def test_conversation_id_tracked(self):
        """Should track conversation_id from StackSpot chunks."""
        lines = [
            f"data: {make_stackspot_chunk('Hi', conversation_id='conv-456')}",
            "",
        ]
        parser = SseEventParser(lines)
        list(parser)

        self.assertIsNotNone(parser.metadata)
        self.assertEqual(parser.metadata["conversation_id"], "conv-456")

    def test_knowledge_source_id_tracked(self):
        """Should track knowledge_source_id from StackSpot chunks."""
        lines = [
            f"data: {make_stackspot_chunk('Hi', knowledge_source_id=['ks-1', 'ks-2'])}",
            "",
        ]
        parser = SseEventParser(lines)
        list(parser)

        self.assertIsNotNone(parser.metadata)
        self.assertEqual(parser.metadata["knowledge_source_id"], ["ks-1", "ks-2"])

    def test_full_stackspot_flow(self):
        """End-to-end test mimicking the real StackSpot API output."""
        lines: list[str] = []
        for msg in ["", "Olá", ",", " estou", " funcionando", "!", "", ""]:
            lines.append(f"data: {make_stackspot_chunk(msg)}")
            lines.append("")

        # Final metadata chunk
        metadata_chunk = make_stackspot_chunk(
            "",
            stop_reason="stop",
            tokens={"input": 749, "output": 5},
            message_id="01KJJB4T9SP5V1SYDEYHTZ5N6Y",
        )
        lines.append(f"data: {metadata_chunk}")
        lines.append("")

        parser = SseEventParser(lines)
        events = list(parser)

        texts = [e.text for e in events if e.is_delta and e.text]
        self.assertEqual("".join(texts), "Olá, estou funcionando!")

        self.assertIsNotNone(parser.metadata)
        self.assertEqual(parser.metadata["stop_reason"], "stop")


# =============================================================================
# Error Event Tests
# =============================================================================


class TestSseParserErrorEvents(unittest.TestCase):
    """Tests for error event parsing."""

    def test_error_event_type(self):
        """Should yield ERROR event for event: error."""
        lines = [
            "event: error",
            'data: {"type": "error", "message": "server overloaded"}',
            "",
        ]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_error)
        self.assertEqual(events[0].error, "server overloaded")

    def test_error_from_data_type_field(self):
        """Should detect error from data type field without event: field."""
        lines = [
            'data: {"type": "error", "message": "rate limited"}',
            "",
        ]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_error)
        self.assertEqual(events[0].error, "rate limited")

    def test_error_with_error_field_instead_of_message(self):
        """Should fall back to 'error' field if 'message' is absent."""
        lines = [
            'data: {"type": "error", "error": "something bad"}',
            "",
        ]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].error, "something bad")

    def test_error_event_preserves_raw_data(self):
        """Error events should include raw_data."""
        lines = [
            "event: error",
            'data: {"type": "error", "message": "oops", "code": 500}',
            "",
        ]
        events = collect_events(lines)

        self.assertIsNotNone(events[0].raw_data)
        self.assertEqual(events[0].raw_data["code"], 500)

    def test_non_json_error(self):
        """Non-JSON error data should still produce an error event."""
        lines = [
            "event: error",
            "data: plain text error",
            "",
        ]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_error)
        self.assertEqual(events[0].error, "plain text error")


# =============================================================================
# Done Event Tests
# =============================================================================


class TestSseParserDoneEvents(unittest.TestCase):
    """Tests for done/completion event parsing."""

    def test_explicit_done_event(self):
        """Should recognize event: done as stream termination."""
        lines = [
            "event: done",
            'data: {"type": "done", "conversation_id": "conv-1"}',
            "",
        ]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_done)
        self.assertEqual(events[0].raw_data["conversation_id"], "conv-1")

    def test_done_from_data_type_field(self):
        """Should detect done from data type field without event: field."""
        lines = [
            'data: {"type": "done", "tokens": {"user": 10}}',
            "",
        ]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_done)

    def test_litellm_done_signal(self):
        """Should recognize data: [DONE] as LiteLLM stream termination."""
        lines = ["data: [DONE]", ""]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_done)

    def test_litellm_done_with_prior_metadata(self):
        """[DONE] event should carry metadata from prior chunks."""
        lines = [
            f"data: {make_litellm_chunk('x', finish_reason='stop')}",
            "",
            "data: [DONE]",
            "",
        ]
        events = collect_events(lines)

        done = [e for e in events if e.is_done][0]
        self.assertEqual(done.raw_data.get("stop_reason"), "stop")


# =============================================================================
# Plain Text / Edge Cases
# =============================================================================


class TestSseParserEdgeCases(unittest.TestCase):
    """Tests for edge cases and unusual inputs."""

    def test_plain_text_data(self):
        """Should handle plain text (non-JSON) data as delta text."""
        lines = ["data: Hello plain text", ""]
        events = collect_events(lines)

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_delta)
        self.assertEqual(events[0].text, "Hello plain text")

    def test_plain_text_raw_data(self):
        """Plain text data should have raw_data with 'raw' key."""
        lines = ["data: not json", ""]
        events = collect_events(lines)

        self.assertEqual(events[0].raw_data, {"raw": "not json"})

    def test_metadata_initially_none(self):
        """Metadata should be None before any chunks are processed."""
        parser = SseEventParser([])
        self.assertIsNone(parser.metadata)

    def test_metadata_none_when_no_metadata_fields(self):
        """Metadata should stay None if no metadata-bearing chunks appear."""
        lines = ["data: plain text", ""]
        parser = SseEventParser(lines)
        list(parser)

        self.assertIsNone(parser.metadata)

    def test_json_array_treated_as_plain_text(self):
        """JSON arrays should be treated as plain text (only dicts are parsed)."""
        lines = ['data: [1, 2, 3]', ""]
        events = collect_events(lines)

        # [1, 2, 3] is valid JSON but not a dict, so treated as text
        self.assertTrue(events[0].is_delta)
        self.assertEqual(events[0].text, "[1, 2, 3]")

    def test_flat_content_field_fallback(self):
        """Should extract text from flat 'content' field as fallback."""
        lines = ['data: {"content": "fallback text"}', ""]
        events = collect_events(lines)

        self.assertEqual(events[0].text, "fallback text")

    def test_flat_text_field_fallback(self):
        """Should extract text from flat 'text' field as fallback."""
        lines = ['data: {"text": "text field"}', ""]
        events = collect_events(lines)

        self.assertEqual(events[0].text, "text field")

    def test_message_field_takes_precedence_over_content(self):
        """StackSpot 'message' field should take precedence over 'content'."""
        lines = ['data: {"message": "msg", "content": "cnt"}', ""]
        events = collect_events(lines)

        self.assertEqual(events[0].text, "msg")

    def test_stackspot_tokens_take_precedence_over_litellm_usage(self):
        """StackSpot tokens in metadata should not be overwritten by LiteLLM usage."""
        chunk = json.dumps({
            "choices": [{"index": 0, "delta": {"content": "x"}}],
            "tokens": {"user": 100, "enrichment": 50, "output": 200},
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        })
        lines = [f"data: {chunk}", ""]
        parser = SseEventParser(lines)
        list(parser)

        # StackSpot tokens should be tracked (set first)
        # LiteLLM usage should NOT overwrite because "tokens" already exists
        tokens = parser.metadata["tokens"]
        self.assertEqual(tokens["user"], 100)
        self.assertEqual(tokens["enrichment"], 50)
        self.assertEqual(tokens["output"], 200)


# =============================================================================
# Iterator Protocol Tests
# =============================================================================


class TestSseParserIteratorProtocol(unittest.TestCase):
    """Tests for iterator behavior and protocol compliance."""

    def test_is_iterable(self):
        """SseEventParser should be iterable."""
        parser = SseEventParser([])
        self.assertTrue(hasattr(parser, "__iter__"))

    def test_yields_typed_events(self):
        """All yielded objects should be ChatResponseStreamEvent instances."""
        from stkai.agents._stream import ChatResponseStreamEvent

        lines = make_sse_lines([
            (None, '{"content": "hello"}'),
            ("done", '{"type": "done"}'),
        ])
        parser = SseEventParser(lines)

        for event in parser:
            self.assertIsInstance(event, ChatResponseStreamEvent)

    def test_event_types_are_correct_enum_values(self):
        """Event types should be valid ChatResponseStreamEventType values."""
        lines = make_sse_lines([
            (None, '{"content": "delta"}'),
            ("error", '{"type": "error", "message": "err"}'),
            ("done", '{"type": "done"}'),
        ])
        events = collect_events(lines)

        self.assertEqual(events[0].type, ChatResponseStreamEventType.DELTA)
        self.assertEqual(events[1].type, ChatResponseStreamEventType.ERROR)
        self.assertEqual(events[2].type, ChatResponseStreamEventType.DONE)


if __name__ == "__main__":
    unittest.main()
