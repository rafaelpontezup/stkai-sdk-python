"""Tests for RQC data models."""

import logging
import unittest

from stkai.rqc._models import (
    _VALID_TRANSITIONS,
    RqcExecution,
    RqcExecutionStatus,
    RqcRequest,
    RqcResponse,
)


class TestRqcRequestIsFrozen(unittest.TestCase):
    """Tests that RqcRequest is immutable (frozen dataclass)."""

    def test_cannot_set_attribute_on_frozen_request(self):
        """Setting an attribute on a frozen RqcRequest should raise FrozenInstanceError."""
        request = RqcRequest(payload={"x": 1}, id="req-123")

        with self.assertRaises(AttributeError):
            request.id = "new-id"  # type: ignore[misc]

    def test_cannot_set_payload_on_frozen_request(self):
        """Setting payload on a frozen RqcRequest should raise FrozenInstanceError."""
        request = RqcRequest(payload={"x": 1})

        with self.assertRaises(AttributeError):
            request.payload = {"y": 2}  # type: ignore[misc]


class TestValidTransitions(unittest.TestCase):
    """Tests for _VALID_TRANSITIONS dict."""

    def test_terminal_states_have_no_transitions(self):
        """Terminal states (FAILURE, ERROR, TIMEOUT) should have empty transition sets."""
        terminal_states = [
            RqcExecutionStatus.FAILURE,
            RqcExecutionStatus.ERROR,
            RqcExecutionStatus.TIMEOUT,
        ]
        for state in terminal_states:
            self.assertEqual(
                _VALID_TRANSITIONS[state], frozenset(),
                f"Terminal state {state} should have no valid transitions"
            )

    def test_completed_allows_transition_to_error(self):
        """COMPLETED can transition to ERROR when a result handler fails client-side."""
        self.assertEqual(
            _VALID_TRANSITIONS[RqcExecutionStatus.COMPLETED],
            frozenset({RqcExecutionStatus.ERROR}),
        )

    def test_non_terminal_states_have_at_least_one_transition(self):
        """Non-terminal states (PENDING, CREATED, RUNNING) should have at least one transition."""
        non_terminal_states = [
            RqcExecutionStatus.PENDING,
            RqcExecutionStatus.CREATED,
            RqcExecutionStatus.RUNNING,
        ]
        for state in non_terminal_states:
            self.assertGreater(
                len(_VALID_TRANSITIONS[state]), 0,
                f"Non-terminal state {state} should have at least one valid transition"
            )

    def test_all_statuses_are_covered(self):
        """Every RqcExecutionStatus should be a key in _VALID_TRANSITIONS."""
        for status in RqcExecutionStatus:
            self.assertIn(status, _VALID_TRANSITIONS, f"Status {status} is not covered in _VALID_TRANSITIONS")


class TestRqcExecution(unittest.TestCase):
    """Tests for RqcExecution lifecycle tracker."""

    def test_initial_state_is_pending(self):
        """New execution should start in PENDING status."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)

        self.assertEqual(execution.status, RqcExecutionStatus.PENDING)
        self.assertIsNone(execution.execution_id)
        self.assertIsNone(execution.submitted_at)

    def test_mark_as_submitted_sets_execution_id_and_timestamp(self):
        """mark_as_submitted should set execution_id and submitted_at."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)

        execution.mark_as_submitted("exec-123")

        self.assertEqual(execution.execution_id, "exec-123")
        self.assertIsNotNone(execution.submitted_at)

    def test_mark_as_submitted_fails_with_empty_id(self):
        """mark_as_submitted should fail with empty execution_id."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)

        with self.assertRaises(AssertionError):
            execution.mark_as_submitted("")

    def test_valid_transition(self):
        """transition_to should work for valid transitions."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)

        execution.transition_to(RqcExecutionStatus.CREATED)
        self.assertEqual(execution.status, RqcExecutionStatus.CREATED)

        execution.transition_to(RqcExecutionStatus.RUNNING)
        self.assertEqual(execution.status, RqcExecutionStatus.RUNNING)

        execution.transition_to(RqcExecutionStatus.COMPLETED)
        self.assertEqual(execution.status, RqcExecutionStatus.COMPLETED)

    def test_unexpected_transition_logs_warning_but_updates(self):
        """Unexpected transitions should log a warning but still update status."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)

        # PENDING → COMPLETED is not in valid transitions
        with self.assertLogs("stkai.rqc._models", level="WARNING") as cm:
            execution.transition_to(RqcExecutionStatus.COMPLETED)

        self.assertEqual(execution.status, RqcExecutionStatus.COMPLETED)
        self.assertIn("Unexpected status transition", cm.output[0])
        self.assertIn("PENDING", cm.output[0])
        self.assertIn("COMPLETED", cm.output[0])

    def test_same_status_transition_is_noop(self):
        """Transitioning to the same status should be a no-op (no warning, no error change)."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)
        execution.transition_to(RqcExecutionStatus.CREATED)
        execution.transition_to(RqcExecutionStatus.RUNNING)
        execution.transition_to(RqcExecutionStatus.ERROR, error="original error")

        # ERROR → ERROR should be ignored
        with self.assertLogs("stkai.rqc._models", level="WARNING") as cm:
            logging.getLogger("stkai.rqc._models").warning("dummy")
            execution.transition_to(RqcExecutionStatus.ERROR, error="should be ignored")

        self.assertEqual(execution.status, RqcExecutionStatus.ERROR)
        self.assertEqual(execution.error, "original error")
        unexpected_warnings = [msg for msg in cm.output if "Unexpected status transition" in msg]
        self.assertEqual(unexpected_warnings, [])

    def test_transition_from_terminal_state_logs_warning(self):
        """Transitioning from a terminal state should log a warning."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)
        execution.transition_to(RqcExecutionStatus.CREATED)
        execution.transition_to(RqcExecutionStatus.COMPLETED)

        # COMPLETED → RUNNING is invalid (terminal state)
        with self.assertLogs("stkai.rqc._models", level="WARNING") as cm:
            execution.transition_to(RqcExecutionStatus.RUNNING)

        self.assertEqual(execution.status, RqcExecutionStatus.RUNNING)
        self.assertIn("Unexpected status transition", cm.output[0])

    def test_error_is_none_initially(self):
        """New execution should have no error."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)

        self.assertIsNone(execution.error)

    def test_transition_to_with_error_sets_error(self):
        """transition_to with error parameter should set the error message."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)

        execution.transition_to(RqcExecutionStatus.ERROR, error="Something went wrong")

        self.assertEqual(execution.status, RqcExecutionStatus.ERROR)
        self.assertEqual(execution.error, "Something went wrong")

    def test_transition_to_without_error_preserves_existing_error(self):
        """transition_to without error should not clear an existing error."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)
        execution.transition_to(RqcExecutionStatus.ERROR, error="First error")

        # Transition without error should preserve the existing one
        with self.assertLogs("stkai.rqc._models", level="WARNING"):
            execution.transition_to(RqcExecutionStatus.RUNNING)

        self.assertEqual(execution.error, "First error")

    def test_transition_to_with_error_overwrites_previous_error(self):
        """transition_to with a new error should overwrite the previous one."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)
        execution.transition_to(RqcExecutionStatus.ERROR, error="First error")

        with self.assertLogs("stkai.rqc._models", level="WARNING"):
            execution.transition_to(RqcExecutionStatus.TIMEOUT, error="Second error")

        self.assertEqual(execution.error, "Second error")


class TestRqcExecutionToResponse(unittest.TestCase):
    """Tests for RqcExecution.to_response() method."""

    def test_to_response_for_completed_status(self):
        """to_response should create a COMPLETED response with result and raw_response."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)
        execution.mark_as_submitted("exec-123")
        execution.transition_to(RqcExecutionStatus.CREATED)
        execution.transition_to(RqcExecutionStatus.COMPLETED)

        response = execution.to_response(
            result={"answer": "42"},
            raw_response={"result": '{"answer": "42"}'},
        )

        self.assertIsInstance(response, RqcResponse)
        self.assertIs(response.request, request)
        self.assertEqual(response.status, RqcExecutionStatus.COMPLETED)
        self.assertEqual(response.result, {"answer": "42"})
        self.assertIsNone(response.error)
        self.assertEqual(response.raw_response, {"result": '{"answer": "42"}'})
        self.assertEqual(response.execution_id, "exec-123")

    def test_to_response_for_error_status(self):
        """to_response should create an ERROR response with error message."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)
        execution.transition_to(RqcExecutionStatus.ERROR, error="Connection refused")

        response = execution.to_response()

        self.assertEqual(response.status, RqcExecutionStatus.ERROR)
        self.assertEqual(response.error, "Connection refused")
        self.assertIsNone(response.result)
        self.assertIsNone(response.raw_response)
        self.assertIsNone(response.execution_id)

    def test_to_response_for_failure_with_raw_response(self):
        """to_response should include raw_response for FAILURE status."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)
        execution.mark_as_submitted("exec-456")
        execution.transition_to(RqcExecutionStatus.CREATED)
        execution.transition_to(
            RqcExecutionStatus.FAILURE,
            error="Server-side failure",
        )
        raw = {"progress": {"status": "FAILURE"}, "result": None}

        response = execution.to_response(raw_response=raw)

        self.assertEqual(response.status, RqcExecutionStatus.FAILURE)
        self.assertEqual(response.error, "Server-side failure")
        self.assertEqual(response.raw_response, raw)
        self.assertEqual(response.execution_id, "exec-456")

    def test_to_response_for_timeout_status(self):
        """to_response should create a TIMEOUT response with error message."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)
        execution.mark_as_submitted("exec-789")
        execution.transition_to(RqcExecutionStatus.CREATED)
        execution.transition_to(RqcExecutionStatus.RUNNING)
        execution.transition_to(RqcExecutionStatus.TIMEOUT, error="Timed out after 600s")

        response = execution.to_response()

        self.assertEqual(response.status, RqcExecutionStatus.TIMEOUT)
        self.assertEqual(response.error, "Timed out after 600s")
        self.assertEqual(response.execution_id, "exec-789")

    def test_to_response_for_pending_status(self):
        """to_response should work for PENDING (initial) status."""
        request = RqcRequest(payload={"x": 1})
        execution = RqcExecution(request=request)

        response = execution.to_response()

        self.assertEqual(response.status, RqcExecutionStatus.PENDING)
        self.assertIsNone(response.error)
        self.assertIsNone(response.execution_id)


if __name__ == "__main__":
    unittest.main()
