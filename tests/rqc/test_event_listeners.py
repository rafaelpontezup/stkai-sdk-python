"""Tests for Event Listeners."""

import json
import tempfile
import unittest
from pathlib import Path

from stkai.rqc import (
    FileLoggingListener,
    RqcExecutionStatus,
    RqcPhasedEventListener,
    RqcRequest,
    RqcResponse,
)


class TestFileLoggingListenerInit(unittest.TestCase):
    """Tests for FileLoggingListener initialization."""

    def test_init_creates_output_directory_if_not_exists(self):
        """Should create output directory (including parents) if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "nested" / "output" / "dir"
            self.assertFalse(output_dir.exists())

            listener = FileLoggingListener(output_dir)

            self.assertTrue(output_dir.exists())
            self.assertTrue(output_dir.is_dir())
            self.assertEqual(listener.output_dir, output_dir)

    def test_init_works_with_existing_directory(self):
        """Should work when output directory already exists."""
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            self.assertTrue(output_dir.exists())

            listener = FileLoggingListener(output_dir)

            self.assertEqual(listener.output_dir, output_dir)

    def test_init_accepts_string_path(self):
        """Should accept str and convert to Path internally."""
        with tempfile.TemporaryDirectory() as tmp:
            output_dir_str = f"{tmp}/string_path"

            listener = FileLoggingListener(output_dir_str)

            self.assertIsInstance(listener.output_dir, Path)
            self.assertEqual(listener.output_dir, Path(output_dir_str))
            self.assertTrue(listener.output_dir.exists())

    def test_init_fails_when_output_dir_is_none(self):
        """Should fail when output_dir is None."""
        with self.assertRaises(AssertionError):
            FileLoggingListener(None)  # type: ignore

    def test_init_fails_when_output_dir_is_empty_string(self):
        """Should fail when output_dir is empty string."""
        with self.assertRaises(AssertionError):
            FileLoggingListener("")

    def test_init_fails_when_path_is_a_file(self):
        """Should fail when output_dir path exists but is a file, not a directory."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            file_path = Path(tmp_file.name)
            try:
                # mkdir() raises FileExistsError when trying to create a dir where a file exists
                with self.assertRaises(FileExistsError):
                    FileLoggingListener(file_path)
            finally:
                file_path.unlink()


class TestFileLoggingListenerOnStatusChange(unittest.TestCase):
    """Tests for FileLoggingListener.on_status_change() method."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.listener = FileLoggingListener(self.tmp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_writes_request_file_when_status_transitions_from_pending_to_created(self):
        """Should write request payload to JSON file when status changes from PENDING to CREATED."""
        request = RqcRequest(payload={"prompt": "Hello"}, id="req-123")
        request.mark_as_submitted(execution_id="exec-456")

        self.listener.on_status_change(
            request=request,
            old_status=RqcExecutionStatus.PENDING,
            new_status=RqcExecutionStatus.CREATED,
            context={},
        )

        request_file = self.tmp_dir / "exec-456-request.json"
        self.assertTrue(request_file.exists())
        with open(request_file) as f:
            content = json.load(f)
        self.assertEqual(content, {"input_data": {"prompt": "Hello"}})

    def test_writes_request_file_when_status_transitions_from_pending_to_error(self):
        """Should write request payload to JSON file when status changes from PENDING to ERROR."""
        request = RqcRequest(payload={"prompt": "Failed request"}, id="req-failed")
        # Note: not calling mark_as_submitted, so execution_id is None (create-execution failed)

        self.listener.on_status_change(
            request=request,
            old_status=RqcExecutionStatus.PENDING,
            new_status=RqcExecutionStatus.ERROR,
            context={},
        )

        # Should use request.id as tracking_id since execution_id is not available
        request_file = self.tmp_dir / "req-failed-request.json"
        self.assertTrue(request_file.exists())
        with open(request_file) as f:
            content = json.load(f)
        self.assertEqual(content, {"input_data": {"prompt": "Failed request"}})

    def test_does_not_write_request_file_for_non_pending_transitions(self):
        """Should not write any files when old_status is not PENDING."""
        request = RqcRequest(payload={"x": 1}, id="test")
        request.mark_as_submitted(execution_id="exec-789")

        self.listener.on_status_change(
            request=request,
            old_status=RqcExecutionStatus.CREATED,
            new_status=RqcExecutionStatus.RUNNING,
            context={},
        )

        files = list(self.tmp_dir.glob("*.json"))
        self.assertEqual(len(files), 0)

    def test_uses_request_id_when_execution_id_not_available(self):
        """Should use request.id as tracking_id when execution_id is not set."""
        request = RqcRequest(payload={"x": 1}, id="my-request-id")
        # Note: not calling mark_as_submitted, so execution_id is None

        self.listener.on_status_change(
            request=request,
            old_status=RqcExecutionStatus.PENDING,
            new_status=RqcExecutionStatus.CREATED,
            context={},
        )

        request_file = self.tmp_dir / "my-request-id-request.json"
        self.assertTrue(request_file.exists())

    def test_sanitizes_special_characters_in_tracking_id(self):
        """Should sanitize special characters in tracking_id for safe filenames."""
        request = RqcRequest(payload={"x": 1}, id="req/with:special*chars?")
        request.mark_as_submitted(execution_id="exec/id:with*special?chars")

        self.listener.on_status_change(
            request=request,
            old_status=RqcExecutionStatus.PENDING,
            new_status=RqcExecutionStatus.CREATED,
            context={},
        )

        files = list(self.tmp_dir.glob("*.json"))
        self.assertEqual(len(files), 1)
        filename = files[0].name
        self.assertNotIn("/", filename)
        self.assertNotIn(":", filename)
        self.assertNotIn("*", filename)
        self.assertNotIn("?", filename)

    def test_context_parameter_is_ignored(self):
        """Should work regardless of context content (context is for other listeners)."""
        request = RqcRequest(payload={"x": 1}, id="req-ctx")
        request.mark_as_submitted(execution_id="exec-ctx")

        context = {"start_time": 123.45, "custom_data": {"nested": True}}
        self.listener.on_status_change(
            request=request,
            old_status=RqcExecutionStatus.PENDING,
            new_status=RqcExecutionStatus.CREATED,
            context=context,
        )

        request_file = self.tmp_dir / "exec-ctx-request.json"
        self.assertTrue(request_file.exists())


class TestFileLoggingListenerOnAfterExecute(unittest.TestCase):
    """Tests for FileLoggingListener.on_after_execute() method."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.listener = FileLoggingListener(self.tmp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_writes_only_response_file(self):
        """Should only write response file (request is written by on_status_change)."""
        request = RqcRequest(payload={"prompt": "Hello"}, id="req-123")
        request.mark_as_submitted(execution_id="exec-456")
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.COMPLETED,
            result="response result",
            raw_response={"result": "response result"},
        )

        self.listener.on_after_execute(request=request, response=response, context={})

        files = list(self.tmp_dir.glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertIn("response", files[0].name)

    def test_writes_response_file_for_completed_status(self):
        """Should write raw_response to JSON file when status is COMPLETED."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        request.mark_as_submitted(execution_id="exec-789")
        raw_response = {"result": "success", "metadata": {"duration": 1.5}}
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.COMPLETED,
            result="success",
            raw_response=raw_response,
        )

        self.listener.on_after_execute(request=request, response=response, context={})

        response_file = self.tmp_dir / "exec-789-response-COMPLETED.json"
        self.assertTrue(response_file.exists())
        with open(response_file) as f:
            content = json.load(f)
        self.assertEqual(content, raw_response)

    def test_writes_response_file_for_failure_status(self):
        """Should write error details to JSON file when status is FAILURE."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        request.mark_as_submitted(execution_id="exec-fail")
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.FAILURE,
            error="Server error occurred",
            raw_response={"error": "internal"},
        )

        self.listener.on_after_execute(request=request, response=response, context={})

        response_file = self.tmp_dir / "exec-fail-response-FAILURE.json"
        self.assertTrue(response_file.exists())
        with open(response_file) as f:
            content = json.load(f)
        self.assertEqual(content["status"], "FAILURE")
        self.assertEqual(content["error_message"], "Server error occurred")

    def test_writes_response_file_for_error_status(self):
        """Should write error details to JSON file when status is ERROR."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        request.mark_as_submitted(execution_id="exec-err")
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.ERROR,
            error="Network timeout",
        )

        self.listener.on_after_execute(request=request, response=response, context={})

        response_file = self.tmp_dir / "exec-err-response-ERROR.json"
        self.assertTrue(response_file.exists())
        with open(response_file) as f:
            content = json.load(f)
        self.assertEqual(content["status"], "ERROR")
        self.assertEqual(content["error_message"], "Network timeout")

    def test_writes_response_file_for_timeout_status(self):
        """Should write error details to JSON file when status is TIMEOUT."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        request.mark_as_submitted(execution_id="exec-timeout")
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.TIMEOUT,
            error="Exceeded 600s",
        )

        self.listener.on_after_execute(request=request, response=response, context={})

        response_file = self.tmp_dir / "exec-timeout-response-TIMEOUT.json"
        self.assertTrue(response_file.exists())
        with open(response_file) as f:
            content = json.load(f)
        self.assertEqual(content["status"], "TIMEOUT")
        self.assertEqual(content["error_message"], "Exceeded 600s")

    def test_uses_request_id_when_execution_id_not_available(self):
        """Should use request.id as tracking_id when execution_id is not set."""
        request = RqcRequest(payload={"x": 1}, id="my-request-id")
        # Note: not calling mark_as_submitted, so execution_id is None
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.ERROR,
            error="Failed before execution",
        )

        self.listener.on_after_execute(request=request, response=response, context={})

        response_file = self.tmp_dir / "my-request-id-response-ERROR.json"
        self.assertTrue(response_file.exists())

    def test_sanitizes_special_characters_in_tracking_id(self):
        """Should sanitize special characters in tracking_id for safe filenames."""
        request = RqcRequest(payload={"x": 1}, id="req/with:special*chars?")
        request.mark_as_submitted(execution_id="exec/id:with*special?chars")
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.COMPLETED,
            result="ok",
            raw_response={"result": "ok"},
        )

        self.listener.on_after_execute(request=request, response=response, context={})

        # Special chars should be replaced with underscore
        files = list(self.tmp_dir.glob("*.json"))
        self.assertEqual(len(files), 1)
        filename = files[0].name
        self.assertNotIn("/", filename)
        self.assertNotIn(":", filename)
        self.assertNotIn("*", filename)
        self.assertNotIn("?", filename)

    def test_context_parameter_is_ignored(self):
        """Should work regardless of context content (context is for other listeners)."""
        request = RqcRequest(payload={"x": 1}, id="req-ctx")
        request.mark_as_submitted(execution_id="exec-ctx")
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.COMPLETED,
            result="ok",
            raw_response={"result": "ok"},
        )

        # Context with various data should not affect file writing
        context = {"start_time": 123.45, "custom_data": {"nested": True}}
        self.listener.on_after_execute(request=request, response=response, context=context)

        response_file = self.tmp_dir / "exec-ctx-response-COMPLETED.json"
        self.assertTrue(response_file.exists())


class TestFileLoggingListenerInheritance(unittest.TestCase):
    """Tests for FileLoggingListener event listener interface."""

    def test_on_before_execute_does_nothing(self):
        """Should have no-op implementation for on_before_execute (inherited)."""
        with tempfile.TemporaryDirectory() as tmp:
            listener = FileLoggingListener(Path(tmp))
            request = RqcRequest(payload={"x": 1}, id="test")

            # Should not raise and should not create any files
            listener.on_before_execute(request=request, context={})

            files = list(Path(tmp).glob("*.json"))
            self.assertEqual(len(files), 0)


class TestRqcPhasedEventListenerDelegation(unittest.TestCase):
    """Tests for RqcPhasedEventListener delegation logic."""

    def setUp(self):
        """Create a test listener that records all hook calls."""
        self.calls: list[tuple[str, dict]] = []

        class RecordingListener(RqcPhasedEventListener):
            def __init__(inner_self):
                pass

            def on_before_create_execution(inner_self, request, context):
                self.calls.append(("on_before_create_execution", {
                    "request_id": request.id,
                    "context": dict(context),
                }))

            def on_after_create_execution(inner_self, request, status, response, context):
                self.calls.append(("on_after_create_execution", {
                    "request_id": request.id,
                    "status": status,
                    "response": response,
                    "context": dict(context),
                }))

            def on_before_get_result(inner_self, request, context):
                self.calls.append(("on_before_get_result", {
                    "request_id": request.id,
                    "execution_id": request.execution_id,
                    "context": dict(context),
                }))

            def on_after_get_result(inner_self, request, response, context):
                self.calls.append(("on_after_get_result", {
                    "request_id": request.id,
                    "response_status": response.status,
                    "context": dict(context),
                }))

        self.listener = RecordingListener()

    def test_on_before_execute_delegates_to_on_before_create_execution(self):
        """on_before_execute should delegate to on_before_create_execution."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        context = {"key": "value"}

        self.listener.on_before_execute(request=request, context=context)

        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], "on_before_create_execution")
        self.assertEqual(self.calls[0][1]["request_id"], "req-123")
        self.assertEqual(self.calls[0][1]["context"], {"key": "value"})

    def test_on_status_change_pending_to_created_triggers_success_hooks(self):
        """PENDING→CREATED should call on_after_create_execution (success) and on_before_get_result."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        request.mark_as_submitted(execution_id="exec-456")
        context = {"start_time": 123.45}

        self.listener.on_status_change(
            request=request,
            old_status=RqcExecutionStatus.PENDING,
            new_status=RqcExecutionStatus.CREATED,
            context=context,
        )

        self.assertEqual(len(self.calls), 2)
        # First: on_after_create_execution with success (response=None)
        self.assertEqual(self.calls[0][0], "on_after_create_execution")
        self.assertEqual(self.calls[0][1]["status"], RqcExecutionStatus.CREATED)
        self.assertIsNone(self.calls[0][1]["response"])
        # Second: on_before_get_result
        self.assertEqual(self.calls[1][0], "on_before_get_result")
        self.assertEqual(self.calls[1][1]["execution_id"], "exec-456")

    def test_on_status_change_other_transitions_do_not_trigger_hooks(self):
        """Non-PENDING transitions should not trigger phase hooks."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        request.mark_as_submitted(execution_id="exec-456")

        self.listener.on_status_change(
            request=request,
            old_status=RqcExecutionStatus.CREATED,
            new_status=RqcExecutionStatus.RUNNING,
            context={},
        )

        self.assertEqual(len(self.calls), 0)

    def test_on_status_change_running_to_completed_does_not_trigger_hooks(self):
        """RUNNING→COMPLETED should not trigger phase hooks (handled by on_after_execute)."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        request.mark_as_submitted(execution_id="exec-456")

        self.listener.on_status_change(
            request=request,
            old_status=RqcExecutionStatus.RUNNING,
            new_status=RqcExecutionStatus.COMPLETED,
            context={},
        )

        self.assertEqual(len(self.calls), 0)

    def test_on_after_execute_with_execution_id_delegates_to_on_after_get_result(self):
        """When execution_id exists, on_after_execute should delegate to on_after_get_result."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        request.mark_as_submitted(execution_id="exec-456")
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.COMPLETED,
            result="success",
        )

        self.listener.on_after_execute(request=request, response=response, context={})

        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], "on_after_get_result")
        self.assertEqual(self.calls[0][1]["response_status"], RqcExecutionStatus.COMPLETED)

    def test_on_after_execute_without_execution_id_delegates_to_on_after_create_execution(self):
        """When execution_id is None (create failed), should delegate to on_after_create_execution."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        # Note: NOT calling mark_as_submitted, so execution_id is None
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.ERROR,
            error="Network error during create",
        )

        self.listener.on_after_execute(request=request, response=response, context={})

        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], "on_after_create_execution")
        self.assertEqual(self.calls[0][1]["status"], RqcExecutionStatus.ERROR)
        self.assertIsNotNone(self.calls[0][1]["response"])
        self.assertEqual(self.calls[0][1]["response"].error, "Network error during create")

    def test_on_after_execute_with_timeout_during_create_delegates_correctly(self):
        """TIMEOUT during create (no execution_id) should delegate to on_after_create_execution."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        # Note: NOT calling mark_as_submitted, so execution_id is None
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.TIMEOUT,
            error="Connection timeout",
        )

        self.listener.on_after_execute(request=request, response=response, context={})

        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], "on_after_create_execution")
        self.assertEqual(self.calls[0][1]["status"], RqcExecutionStatus.TIMEOUT)


class TestRqcPhasedEventListenerFullFlow(unittest.TestCase):
    """Tests for RqcPhasedEventListener simulating full execution flows."""

    def setUp(self):
        """Create a test listener that records call order."""
        self.call_order: list[str] = []

        class OrderRecordingListener(RqcPhasedEventListener):
            def __init__(inner_self):
                pass

            def on_before_create_execution(inner_self, request, context):
                self.call_order.append("before_create")

            def on_after_create_execution(inner_self, request, status, response, context):
                self.call_order.append(f"after_create:{status.value}")

            def on_before_get_result(inner_self, request, context):
                self.call_order.append("before_get_result")

            def on_after_get_result(inner_self, request, response, context):
                self.call_order.append(f"after_get_result:{response.status.value}")

        self.listener = OrderRecordingListener()

    def test_successful_execution_flow_calls_all_hooks_in_order(self):
        """Simulate successful execution: all 4 hooks should be called in correct order."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        context: dict = {}

        # Step 1: on_before_execute (start of execution)
        self.listener.on_before_execute(request=request, context=context)

        # Step 2: Create execution succeeds
        request.mark_as_submitted(execution_id="exec-456")
        self.listener.on_status_change(
            request=request,
            old_status=RqcExecutionStatus.PENDING,
            new_status=RqcExecutionStatus.CREATED,
            context=context,
        )

        # Step 3: Polling transitions (these don't trigger phase hooks)
        self.listener.on_status_change(
            request=request,
            old_status=RqcExecutionStatus.CREATED,
            new_status=RqcExecutionStatus.RUNNING,
            context=context,
        )

        # Step 4: Execution completes
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.COMPLETED,
            result="success",
        )
        self.listener.on_after_execute(request=request, response=response, context=context)

        # Verify call order
        self.assertEqual(self.call_order, [
            "before_create",
            "after_create:CREATED",
            "before_get_result",
            "after_get_result:COMPLETED",
        ])

    def test_create_execution_failure_flow_calls_only_create_hooks(self):
        """When create-execution fails, only create phase hooks should be called."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        context: dict = {}

        # Step 1: on_before_execute (start of execution)
        self.listener.on_before_execute(request=request, context=context)

        # Step 2: Create execution fails (no execution_id set)
        # Note: on_status_change PENDING→ERROR is called by RemoteQuickCommand
        self.listener.on_status_change(
            request=request,
            old_status=RqcExecutionStatus.PENDING,
            new_status=RqcExecutionStatus.ERROR,
            context=context,
        )

        # Step 3: on_after_execute with error response
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.ERROR,
            error="Network error",
        )
        self.listener.on_after_execute(request=request, response=response, context=context)

        # Verify: only create hooks, no polling hooks
        self.assertEqual(self.call_order, [
            "before_create",
            "after_create:ERROR",
        ])

    def test_polling_failure_flow_calls_all_hooks(self):
        """When polling fails (after successful create), all hooks should be called."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        context: dict = {}

        # Step 1: on_before_execute
        self.listener.on_before_execute(request=request, context=context)

        # Step 2: Create execution succeeds
        request.mark_as_submitted(execution_id="exec-456")
        self.listener.on_status_change(
            request=request,
            old_status=RqcExecutionStatus.PENDING,
            new_status=RqcExecutionStatus.CREATED,
            context=context,
        )

        # Step 3: Polling fails with FAILURE status
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.FAILURE,
            error="Server-side failure",
        )
        self.listener.on_after_execute(request=request, response=response, context=context)

        # Verify: all hooks called, with FAILURE in polling phase
        self.assertEqual(self.call_order, [
            "before_create",
            "after_create:CREATED",
            "before_get_result",
            "after_get_result:FAILURE",
        ])

    def test_polling_timeout_flow_calls_all_hooks(self):
        """When polling times out (after successful create), all hooks should be called."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        context: dict = {}

        # Step 1: on_before_execute
        self.listener.on_before_execute(request=request, context=context)

        # Step 2: Create execution succeeds
        request.mark_as_submitted(execution_id="exec-456")
        self.listener.on_status_change(
            request=request,
            old_status=RqcExecutionStatus.PENDING,
            new_status=RqcExecutionStatus.CREATED,
            context=context,
        )

        # Step 3: Polling times out
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.TIMEOUT,
            error="Exceeded 600s",
        )
        self.listener.on_after_execute(request=request, response=response, context=context)

        # Verify: all hooks called, with TIMEOUT in polling phase
        self.assertEqual(self.call_order, [
            "before_create",
            "after_create:CREATED",
            "before_get_result",
            "after_get_result:TIMEOUT",
        ])


class TestRqcPhasedEventListenerDefaultImplementation(unittest.TestCase):
    """Tests for RqcPhasedEventListener default (no-op) implementations."""

    def test_all_hooks_have_default_noop_implementation(self):
        """All phase hooks should have default no-op implementation (don't raise)."""
        # Create instance directly (not subclass) to test default implementations
        listener = RqcPhasedEventListener()
        request = RqcRequest(payload={"x": 1}, id="req-123")
        request.mark_as_submitted(execution_id="exec-456")
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.COMPLETED,
            result="ok",
        )
        context: dict = {}

        # None of these should raise
        listener.on_before_create_execution(request, context)
        listener.on_after_create_execution(request, RqcExecutionStatus.CREATED, None, context)
        listener.on_before_get_result(request, context)
        listener.on_after_get_result(request, response, context)

    def test_base_methods_delegate_correctly_even_with_default_hooks(self):
        """Base methods should work correctly even when hooks are not overridden."""
        listener = RqcPhasedEventListener()
        request = RqcRequest(payload={"x": 1}, id="req-123")
        request.mark_as_submitted(execution_id="exec-456")
        response = RqcResponse(
            request=request,
            status=RqcExecutionStatus.COMPLETED,
            result="ok",
        )
        context: dict = {}

        # None of these should raise
        listener.on_before_execute(request, context)
        listener.on_status_change(
            request, RqcExecutionStatus.PENDING, RqcExecutionStatus.CREATED, context
        )
        listener.on_after_execute(request, response, context)


if __name__ == "__main__":
    unittest.main()
