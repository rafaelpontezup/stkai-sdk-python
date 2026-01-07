"""Tests for Result Handlers."""

import json
import unittest
from typing import Any
from unittest.mock import Mock

from stkai.rqc import (
    RqcRequest,
    RqcResultContext,
    RqcResultHandler,
)
from stkai.rqc._handlers import (
    DEFAULT_RESULT_HANDLER,
    RAW_RESULT_HANDLER,
    ChainedResultHandler,
    JsonResultHandler,
    RawResultHandler,
)


def make_context(raw_result: Any, handled: bool = False) -> RqcResultContext:
    """Helper to create a valid RqcResultContext for testing."""
    request = RqcRequest(payload={"test": True}, id="test-req-id")
    request.mark_as_submitted(execution_id="test-exec-id")
    return RqcResultContext(request=request, raw_result=raw_result, handled=handled)


# ======================
# RawResultHandler Tests
# ======================

class TestRawResultHandler(unittest.TestCase):
    """Tests for RawResultHandler."""

    def setUp(self):
        self.handler = RawResultHandler()

    def test_returns_string_as_is(self):
        """Should return string result without transformation."""
        context = make_context(raw_result="hello world")
        result = self.handler.handle_result(context)
        self.assertEqual(result, "hello world")

    def test_returns_dict_as_is(self):
        """Should return dict result without transformation."""
        context = make_context(raw_result={"key": "value"})
        result = self.handler.handle_result(context)
        self.assertEqual(result, {"key": "value"})

    def test_returns_list_as_is(self):
        """Should return list result without transformation."""
        context = make_context(raw_result=[1, 2, 3])
        result = self.handler.handle_result(context)
        self.assertEqual(result, [1, 2, 3])

    def test_returns_none_as_is(self):
        """Should return None without transformation."""
        context = make_context(raw_result=None)
        result = self.handler.handle_result(context)
        self.assertIsNone(result)

    def test_returns_number_as_is(self):
        """Should return numeric result without transformation."""
        context = make_context(raw_result=42)
        result = self.handler.handle_result(context)
        self.assertEqual(result, 42)

    def test_raw_result_handler_singleton_exists(self):
        """RAW_RESULT_HANDLER constant should be a RawResultHandler instance."""
        self.assertIsInstance(RAW_RESULT_HANDLER, RawResultHandler)


# ======================
# JsonResultHandler Tests
# ======================

class TestJsonResultHandler(unittest.TestCase):
    """Tests for JsonResultHandler."""

    def setUp(self):
        self.handler = JsonResultHandler()

    def test_returns_none_for_empty_result(self):
        """Should return None when raw_result is empty/falsy."""
        context = make_context(raw_result=None)
        result = self.handler.handle_result(context)
        self.assertIsNone(result)

    def test_returns_empty_string_for_empty_string(self):
        """Should return None when raw_result is an empty string."""
        context = make_context(raw_result="")
        result = self.handler.handle_result(context)
        self.assertEqual("", result)

    def test_parses_json_string_to_dict(self):
        """Should parse valid JSON string into Python dict."""
        context = make_context(raw_result='{"name": "test", "value": 123}')
        result = self.handler.handle_result(context)
        self.assertEqual(result, {"name": "test", "value": 123})

    def test_parses_json_string_to_list(self):
        """Should parse valid JSON array string into Python list."""
        context = make_context(raw_result='[1, 2, 3]')
        result = self.handler.handle_result(context)
        self.assertEqual(result, [1, 2, 3])

    def test_parses_json_string_with_nested_objects(self):
        """Should parse nested JSON structures correctly."""
        json_str = '{"outer": {"inner": [1, 2, {"deep": true}]}}'
        context = make_context(raw_result=json_str)
        result = self.handler.handle_result(context)
        self.assertEqual(result, {"outer": {"inner": [1, 2, {"deep": True}]}})

    def test_returns_deep_copy_of_dict(self):
        """Should return a deep copy when raw_result is already a dict."""
        original = {"key": {"nested": "value"}}
        context = make_context(raw_result=original)
        result = self.handler.handle_result(context)

        # Should be equal but not the same object
        self.assertEqual(result, original)
        self.assertIsNot(result, original)

        # Modifying result should not affect original
        result["key"]["nested"] = "modified"
        self.assertEqual(original["key"]["nested"], "value")

    def test_removes_markdown_json_code_block(self):
        """Should strip markdown ```json code block wrapper."""
        json_with_markdown = '```json\n{"parsed": true}\n```'
        context = make_context(raw_result=json_with_markdown)
        result = self.handler.handle_result(context)
        self.assertEqual(result, {"parsed": True})

    def test_removes_markdown_code_block_without_language(self):
        """Should strip markdown ``` code block wrapper without language specifier."""
        json_with_markdown = '```\n{"parsed": true}\n```'
        context = make_context(raw_result=json_with_markdown)
        result = self.handler.handle_result(context)
        self.assertEqual(result, {"parsed": True})

    def test_handles_json_with_whitespace(self):
        """Should handle JSON with leading/trailing whitespace."""
        context = make_context(raw_result='  \n  {"key": "value"}  \n  ')
        result = self.handler.handle_result(context)
        self.assertEqual(result, {"key": "value"})

    def test_raises_type_error_for_integer_input(self):
        """Should raise TypeError when raw_result is an integer."""
        context = make_context(raw_result=123)
        with self.assertRaises(TypeError) as ctx:
            self.handler.handle_result(context)
        self.assertIn("non-string", str(ctx.exception))
        self.assertIn("int", str(ctx.exception))

    def test_raises_type_error_for_list_input(self):
        """Should raise TypeError when raw_result is a list."""
        context = make_context(raw_result=[1, 2, 3])
        with self.assertRaises(TypeError) as ctx:
            self.handler.handle_result(context)
        self.assertIn("non-string", str(ctx.exception))
        self.assertIn("list", str(ctx.exception))

    def test_raises_json_decode_error_for_invalid_json(self):
        """Should raise JSONDecodeError for invalid JSON string."""
        context = make_context(raw_result="not valid json")
        with self.assertRaises(json.JSONDecodeError):
            self.handler.handle_result(context)

    def test_raises_json_decode_error_for_malformed_json(self):
        """Should raise JSONDecodeError for malformed JSON."""
        context = make_context(raw_result='{"key": }')
        with self.assertRaises(json.JSONDecodeError):
            self.handler.handle_result(context)

    def test_default_result_handler_is_json_handler(self):
        """DEFAULT_RESULT_HANDLER constant should be a JsonResultHandler instance."""
        self.assertIsInstance(DEFAULT_RESULT_HANDLER, JsonResultHandler)


class TestJsonResultHandlerChainWith(unittest.TestCase):
    """Tests for JsonResultHandler.chain_with() static method."""

    def test_chain_with_creates_chained_handler(self):
        """Should create a ChainedResultHandler with JSON handler first."""
        other_handler = Mock(spec=RqcResultHandler)
        other_handler.handle_result.return_value = "transformed"

        chained = JsonResultHandler.chain_with(other_handler)

        self.assertIsInstance(chained, ChainedResultHandler)

    def test_chain_with_parses_json_then_applies_other_handler(self):
        """Should parse JSON first, then apply the other handler."""
        class UppercaseHandler(RqcResultHandler):
            def handle_result(self, context: RqcResultContext) -> Any:
                # Expects the raw_result to be already parsed dict
                return {k: v.upper() if isinstance(v, str) else v
                        for k, v in context.raw_result.items()}

        chained = JsonResultHandler.chain_with(UppercaseHandler())
        context = make_context(raw_result='{"name": "test"}')

        result = chained.handle_result(context)

        self.assertEqual(result, {"name": "TEST"})


# ======================
# ChainedResultHandler Tests
# ======================

class TestChainedResultHandler(unittest.TestCase):
    """Tests for ChainedResultHandler."""

    def test_executes_single_handler(self):
        """Should work correctly with a single handler in the chain."""
        handler = ChainedResultHandler([RawResultHandler()])
        context = make_context(raw_result="test")

        result = handler.handle_result(context)

        self.assertEqual(result, "test")

    def test_executes_handlers_in_sequence(self):
        """Should execute handlers in order, passing results through."""
        class AddPrefixHandler(RqcResultHandler):
            def handle_result(self, context: RqcResultContext) -> Any:
                return f"prefix_{context.raw_result}"

        class AddSuffixHandler(RqcResultHandler):
            def handle_result(self, context: RqcResultContext) -> Any:
                return f"{context.raw_result}_suffix"

        handler = ChainedResultHandler([AddPrefixHandler(), AddSuffixHandler()])
        context = make_context(raw_result="value")

        result = handler.handle_result(context)

        self.assertEqual(result, "prefix_value_suffix")

    def test_json_then_custom_transformation(self):
        """Should parse JSON then apply custom transformation."""
        class ExtractFieldHandler(RqcResultHandler):
            def handle_result(self, context: RqcResultContext) -> Any:
                return context.raw_result.get("data")

        handler = ChainedResultHandler([JsonResultHandler(), ExtractFieldHandler()])
        context = make_context(raw_result='{"data": "extracted", "other": "ignored"}')

        result = handler.handle_result(context)

        self.assertEqual(result, "extracted")

    def test_updates_handled_flag_after_first_handler(self):
        """Should set handled=True in context after first handler processes."""
        handled_flags = []

        class TrackingHandler(RqcResultHandler):
            def handle_result(self, ctx: RqcResultContext) -> Any:
                handled_flags.append(ctx.handled)
                return ctx.raw_result

        handler = ChainedResultHandler([TrackingHandler(), TrackingHandler(), TrackingHandler()])
        context = make_context(raw_result="test", handled=False)

        handler.handle_result(context)

        # First handler receives False, subsequent handlers receive True
        self.assertEqual(handled_flags, [False, True, True])

    def test_empty_chain_returns_raw_result(self):
        """Should return raw_result when chain is empty."""
        handler = ChainedResultHandler([])
        context = make_context(raw_result="original")

        result = handler.handle_result(context)

        self.assertEqual(result, "original")


class TestChainedResultHandlerOf(unittest.TestCase):
    """Tests for ChainedResultHandler.of() factory method."""

    def test_of_with_single_handler(self):
        """Should wrap single handler in a ChainedResultHandler."""
        single_handler = RawResultHandler()
        chained = ChainedResultHandler.of(single_handler)

        self.assertIsInstance(chained, ChainedResultHandler)
        self.assertEqual(len(chained.chained_handlers), 1)
        self.assertIs(chained.chained_handlers[0], single_handler)

    def test_of_with_list_of_handlers(self):
        """Should wrap list of handlers in a ChainedResultHandler."""
        handlers = [RawResultHandler(), JsonResultHandler()]
        chained = ChainedResultHandler.of(handlers)

        self.assertIsInstance(chained, ChainedResultHandler)
        self.assertEqual(len(chained.chained_handlers), 2)

    def test_of_with_tuple_of_handlers(self):
        """Should wrap tuple of handlers in a ChainedResultHandler."""
        handlers = (RawResultHandler(), JsonResultHandler())
        chained = ChainedResultHandler.of(handlers)

        self.assertIsInstance(chained, ChainedResultHandler)
        self.assertEqual(len(chained.chained_handlers), 2)

    def test_of_single_handler_executes_correctly(self):
        """Single handler wrapped by of() should execute correctly."""
        chained = ChainedResultHandler.of(RawResultHandler())
        context = make_context(raw_result="test value")

        result = chained.handle_result(context)

        self.assertEqual(result, "test value")

    def test_of_multiple_handlers_executes_in_order(self):
        """Multiple handlers wrapped by of() should execute in order."""
        class DoubleHandler(RqcResultHandler):
            def handle_result(self, context: RqcResultContext) -> Any:
                return context.raw_result * 2

        chained = ChainedResultHandler.of([DoubleHandler(), DoubleHandler()])
        context = make_context(raw_result=5)

        # First doubles 5 to 10, second doubles 10 to 20
        # Note: RawResultHandler behavior - each handler receives the previous result
        result = chained.handle_result(context)

        self.assertEqual(result, 20)


if __name__ == "__main__":
    unittest.main()
