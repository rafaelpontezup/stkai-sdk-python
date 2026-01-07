"""Tests for Event Listeners."""

import json
import tempfile
import unittest
from pathlib import Path

from stkai.rqc import (
    FileLoggingListener,
    RqcRequest,
    RqcResponse,
    RqcResponseStatus,
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


class TestFileLoggingListenerOnAfterExecute(unittest.TestCase):
    """Tests for FileLoggingListener.on_after_execute() method."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.listener = FileLoggingListener(self.tmp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_writes_request_file_with_correct_content(self):
        """Should write request payload to JSON file."""
        request = RqcRequest(payload={"prompt": "Hello"}, id="req-123")
        request.mark_as_submitted(execution_id="exec-456")
        response = RqcResponse(
            request=request,
            status=RqcResponseStatus.COMPLETED,
            result="response result",
            raw_response={"result": "response result"},
        )

        self.listener.on_after_execute(request=request, response=response, context={})

        request_file = self.tmp_dir / "exec-456-request.json"
        self.assertTrue(request_file.exists())
        with open(request_file) as f:
            content = json.load(f)
        self.assertEqual(content, {"input_data": {"prompt": "Hello"}})

    def test_writes_response_file_for_completed_status(self):
        """Should write raw_response to JSON file when status is COMPLETED."""
        request = RqcRequest(payload={"x": 1}, id="req-123")
        request.mark_as_submitted(execution_id="exec-789")
        raw_response = {"result": "success", "metadata": {"duration": 1.5}}
        response = RqcResponse(
            request=request,
            status=RqcResponseStatus.COMPLETED,
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
            status=RqcResponseStatus.FAILURE,
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
            status=RqcResponseStatus.ERROR,
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
            status=RqcResponseStatus.TIMEOUT,
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
            status=RqcResponseStatus.ERROR,
            error="Failed before execution",
        )

        self.listener.on_after_execute(request=request, response=response, context={})

        request_file = self.tmp_dir / "my-request-id-request.json"
        response_file = self.tmp_dir / "my-request-id-response-ERROR.json"
        self.assertTrue(request_file.exists())
        self.assertTrue(response_file.exists())

    def test_sanitizes_special_characters_in_tracking_id(self):
        """Should sanitize special characters in tracking_id for safe filenames."""
        request = RqcRequest(payload={"x": 1}, id="req/with:special*chars?")
        request.mark_as_submitted(execution_id="exec/id:with*special?chars")
        response = RqcResponse(
            request=request,
            status=RqcResponseStatus.COMPLETED,
            result="ok",
            raw_response={"result": "ok"},
        )

        self.listener.on_after_execute(request=request, response=response, context={})

        # Special chars should be replaced with underscore
        files = list(self.tmp_dir.glob("*.json"))
        self.assertEqual(len(files), 2)
        filenames = [f.name for f in files]
        # Verify no special characters in filenames
        for filename in filenames:
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
            status=RqcResponseStatus.COMPLETED,
            result="ok",
            raw_response={"result": "ok"},
        )

        # Context with various data should not affect file writing
        context = {"start_time": 123.45, "custom_data": {"nested": True}}
        self.listener.on_after_execute(request=request, response=response, context=context)

        request_file = self.tmp_dir / "exec-ctx-request.json"
        response_file = self.tmp_dir / "exec-ctx-response-COMPLETED.json"
        self.assertTrue(request_file.exists())
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

    def test_on_status_change_does_nothing(self):
        """Should have no-op implementation for on_status_change (inherited)."""
        with tempfile.TemporaryDirectory() as tmp:
            listener = FileLoggingListener(Path(tmp))
            request = RqcRequest(payload={"x": 1}, id="test")

            # Should not raise and should not create any files
            listener.on_status_change(
                request=request,
                old_status="CREATED",
                new_status="RUNNING",
                context={},
            )

            files = list(Path(tmp).glob("*.json"))
            self.assertEqual(len(files), 0)


if __name__ == "__main__":
    unittest.main()
