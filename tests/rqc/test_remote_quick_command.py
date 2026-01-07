"""Tests for Remote Quick Command client."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests

from stkai.rqc import (
    CreateExecutionOptions,
    GetResultOptions,
    RemoteQuickCommand,
    RqcHttpClient,
    RqcRequest,
    RqcResponseStatus,
)

# ======================
# Helper functions
# ======================

def make_response(json_data, status_code=200):
    """Creates a mock that behaves like requests.Response"""
    resp = Mock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.side_effect = None
    if 400 <= status_code < 500:
        err = requests.HTTPError(f"{status_code} Client Error")
        err.response = resp
        resp.raise_for_status.side_effect = err
    elif 500 <= status_code < 600:
        err = requests.HTTPError(f"{status_code} Server Error")
        err.response = resp
        resp.raise_for_status.side_effect = err
    return resp


class TestRemoteQuickCommandExecute(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.slug_name = "test-slug"

        # Mock of the client respecting the interface signature
        self.http_client = Mock(spec=RqcHttpClient)

        # Instance with small intervals to run fast
        self.rqc = RemoteQuickCommand(
            slug_name=self.slug_name,
            create_execution_options=CreateExecutionOptions(
                max_retries=3,
                backoff_factor=0.1,
            ),
            get_result_options=GetResultOptions(
                poll_interval=0.01,
                poll_max_duration=0.1,
            ),
            http_client=self.http_client,
            listeners=[],  # Disable default FileLoggingListener
        )

    # ---------------------------------------------------------
    # Scenario: Successful execution (status COMPLETED)
    # ---------------------------------------------------------
    def test_execute_when_successful_completed(self):
        # Scenario
        request = RqcRequest(payload={"x": 1})
        execution_id = "exec-123"

        post_resp = make_response(json_data=execution_id)
        get_resp = make_response(json_data={
            "progress": {"status": "COMPLETED"},
            "result": json.dumps({
                "answer": "LLM does not anything",
                "happiness": 1.0,
            })
        })

        self.http_client.post_with_authorization.return_value = post_resp
        self.http_client.get_with_authorization.return_value = get_resp

        # Action
        response = self.rqc.execute(request=request)

        # Validation
        self.assertEqual(response.status, RqcResponseStatus.COMPLETED)
        self.assertEqual(response.result, {"answer": "LLM does not anything", "happiness": 1.0,})
        self.http_client.post_with_authorization.assert_called_once_with(
            slug_name=self.slug_name,
            data=request.to_input_data(),
            timeout=30
        )
        self.http_client.get_with_authorization.assert_called_with(execution_id=execution_id, timeout=30)

    # ---------------------------------------------------------
    # Scenario: Error when creating execution (raise in POST)
    # ---------------------------------------------------------
    def test_execute_when_create_execution_raises_unexpected_error(self):
        # Scenario
        request = RqcRequest(payload={"x": 1})
        self.http_client.post_with_authorization.side_effect = Exception("Boom")

        # Action
        response = self.rqc.execute(request)

        # Validation
        self.assertEqual(response.status, RqcResponseStatus.ERROR)
        self.assertIn("Failed to create execution: Boom", response.error)
        self.http_client.post_with_authorization.assert_called_once()

    # ---------------------------------------------------------
    # Scenario: Execution returns FAILURE
    # ---------------------------------------------------------
    def test_execute_when_polling_fails_with_status_failure(self):
        # Scenario
        request = RqcRequest(payload={"x": 1})
        execution_id = "exec-456"

        post_resp = make_response(json_data=execution_id)
        fail_resp = make_response(json_data={
            "progress": {"status": "FAILURE"},
            "result": None
        })

        self.http_client.post_with_authorization.return_value = post_resp
        self.http_client.get_with_authorization.return_value = fail_resp

        # Action
        response = self.rqc.execute(request)

        # Validation
        self.assertEqual(response.status, RqcResponseStatus.FAILURE)
        self.assertTrue(response.error)
        self.http_client.post_with_authorization.assert_called_once_with(
            slug_name=self.slug_name,
            data=request.to_input_data(),
            timeout=30
        )
        self.http_client.get_with_authorization.assert_called_once_with(execution_id=execution_id, timeout=30)

    # ---------------------------------------------------------
    # Scenario: Polling exceeds max duration (TIMEOUT)
    # ---------------------------------------------------------
    def test_execute_when_polling_times_out(self):
        # Scenario
        request = RqcRequest(payload={"x": 1})
        execution_id = "exec-789"

        post_resp = make_response(json_data=execution_id)
        running_resp = make_response(json_data={"progress": {"status": "RUNNING"}})

        self.http_client.post_with_authorization.return_value = post_resp
        self.http_client.get_with_authorization.return_value = running_resp

        # Action
        response = self.rqc.execute(request)

        # Validation
        self.assertEqual(response.status, RqcResponseStatus.TIMEOUT)
        self.assertIn("Timeout after 0.1 seconds waiting for RQC execution to complete. Last status: `RUNNING`", response.error)
        self.http_client.post_with_authorization.assert_called_once()
        self.assertGreaterEqual(self.http_client.get_with_authorization.call_count, 1)

    # ---------------------------------------------------------
    # Scenario: Unexpected error during polling
    # ---------------------------------------------------------
    def test_execute_when_polling_raises_unexpected_error(self):
        # Scenario
        request = RqcRequest(payload={"x": 1})
        execution_id = "exec-999"

        post_resp = make_response(json_data=execution_id)
        self.http_client.post_with_authorization.return_value = post_resp
        self.http_client.get_with_authorization.side_effect = RuntimeError("broken pipe")

        # Action
        response = self.rqc.execute(request)

        # Validation
        self.assertEqual(response.status, RqcResponseStatus.ERROR)
        self.assertIn("Error during polling: broken pipe", response.error)
        self.http_client.post_with_authorization.assert_called_once_with(
            slug_name=self.slug_name,
            data=request.to_input_data(),
            timeout=30
        )
        self.http_client.get_with_authorization.assert_called_once_with(execution_id=execution_id, timeout=30)

    # ---------------------------------------------------------
    # Scenario: Polling stuck on CREATED and hits timeout
    # ---------------------------------------------------------
    def test_execute_when_polling_fails_on_server_is_overloaded(self):
        # Scenario
        request = RqcRequest(payload={"job": "long-running"})
        execution_id = "exec-created-123"

        post_resp = make_response(json_data=execution_id)
        created_resp = make_response(json_data={
            "progress": {"status": "CREATED"},
            "result": None
        })

        self.http_client.post_with_authorization.return_value = post_resp
        self.http_client.get_with_authorization.return_value = created_resp

        # Use short overload_timeout to trigger overload detection before poll_max_duration
        rqc_for_created_test = RemoteQuickCommand(
            slug_name=self.slug_name,
            create_execution_options=CreateExecutionOptions(
                max_retries=3,
                backoff_factor=0.1,
            ),
            get_result_options=GetResultOptions(
                poll_interval=0.01,
                poll_max_duration=1.0,
                overload_timeout=0.05,  # Short timeout to trigger overload detection
            ),
            http_client=self.http_client,
            listeners=[],  # Disable default FileLoggingListener
        )

        # Action
        result = rqc_for_created_test.execute(request)

        # Validation
        self.assertEqual(result.status, RqcResponseStatus.TIMEOUT)
        self.assertIn("CREATED status", result.error)
        self.assertIn("overloaded", result.error)
        self.http_client.post_with_authorization.assert_called_once_with(
            slug_name=self.slug_name,
            data=request.to_input_data(),
            timeout=30
        )
        # Should have made multiple GET attempts before overload timeout
        self.assertGreaterEqual(self.http_client.get_with_authorization.call_count, 1)

    # ---------------------------------------------------------
    # Scenario 1: 4xx error when creating execution (POST)
    # ---------------------------------------------------------
    def test_execute_when_create_execution_fails_on_4xx(self):
        # Scenario
        request = RqcRequest(payload={"job": "fail-create"})
        error_response = make_response(json_data={}, status_code=401)
        self.http_client.post_with_authorization.return_value = error_response

        # Action
        result = self.rqc.execute(request)

        # Validation
        self.assertEqual(result.status, RqcResponseStatus.ERROR)
        self.assertIn("Failed to create execution: 401 Client Error", result.error)
        self.http_client.post_with_authorization.assert_called_once_with(
            slug_name=self.slug_name,
            data=request.to_input_data(),
            timeout=30
        )
        self.http_client.get_with_authorization.assert_not_called()

    # ---------------------------------------------------------
    # Scenario 2: 4xx error during polling (GET)
    # ---------------------------------------------------------
    def test_execute_when_polling_fails_on_4xx(self):
        # Scenario
        request = RqcRequest(payload={"job": "fail-polling"})
        execution_id = "exec-1234"

        post_resp = make_response(json_data=execution_id)
        poll_resp = make_response(json_data={}, status_code=403)

        self.http_client.post_with_authorization.return_value = post_resp
        self.http_client.get_with_authorization.return_value = poll_resp

        # Action
        result = self.rqc.execute(request)

        # Validation
        self.assertEqual(result.status, RqcResponseStatus.ERROR)
        self.assertIn("Error during polling: 403 Client Error", result.error)
        self.http_client.post_with_authorization.assert_called_once()
        self.http_client.get_with_authorization.assert_called_once_with(
            execution_id=execution_id,
            timeout=30
        )

    # ---------------------------------------------------------
    # Scenario: POST returns 200 but no execution_id in the body
    # ---------------------------------------------------------
    def test_execute_when_create_execution_fails_on_execution_id_not_returned_by_server(self):
        # Scenario
        request = RqcRequest(payload={"job": "missing-exec-id"})
        # Simulate OK response but without ID in body (e.g., {}, None, or empty string)
        post_resp = make_response(json_data={})

        self.http_client.post_with_authorization.return_value = post_resp

        # Action
        result = self.rqc.execute(request)

        # Validation
        self.assertEqual(result.status, RqcResponseStatus.ERROR)
        self.assertIn(
            "Failed to create execution: No `execution_id` returned in the create execution response by server.",
            result.error)
        self.http_client.post_with_authorization.assert_called_once_with(
            slug_name=self.slug_name,
            data=request.to_input_data(),
            timeout=30
        )
        # Should not attempt polling
        self.http_client.get_with_authorization.assert_not_called()

    # ---------------------------------------------------------
    # Scenario: all attempts to create execution fail (e.g., ConnectionError)
    # ---------------------------------------------------------
    def test_execute_when_create_execution_fails_on_max_retries_exceeded(self):
        # Scenario
        request = RqcRequest(payload={"job": "network-fail"})
        # Simulate consecutive connection failures
        self.http_client.post_with_authorization.side_effect = requests.ConnectionError(
            "Simulated connection failure"
        )

        # Action
        result = self.rqc.execute(request)

        # Validation
        self.assertEqual(result.status, RqcResponseStatus.ERROR)
        self.assertIn(
            "Max retries exceeded while creating execution. Last error: Simulated connection failure",
            result.error
        )
        # Verify multiple attempts (depending on internal retry logic)
        self.assertGreaterEqual(self.http_client.post_with_authorization.call_count, self.rqc.create_execution_options.max_retries)
        # Should not perform polling
        self.http_client.get_with_authorization.assert_not_called()

    # ---------------------------------------------------------
    # Scenario: Polling has temporary HTTP 503 failures and finishes with COMPLETED
    # ---------------------------------------------------------
    def test_execute_when_polling_succeeds_after_temporary_polling_http_503_failures(self):
        # 1. POST (create execution) OK
        execution_id = "exec-503"
        post_resp = make_response(json_data=execution_id)
        self.http_client.post_with_authorization.return_value = post_resp

        # 2. GET (polling): 503 -> 503 -> RUNNING -> COMPLETED
        http_503_error = make_response(json_data={}, status_code=503)
        running_resp = make_response(json_data={"progress": {"status": "RUNNING"}})
        completed_resp = make_response(
            json_data={
                "progress": {"status": "COMPLETED"},
                "result": {"value": "success"},
            }
        )

        self.http_client.get_with_authorization.side_effect = [
            http_503_error,
            http_503_error,
            running_resp,
            completed_resp,
        ]

        # 3. Execute
        request = RqcRequest(payload={"job": "resilient-http-503"})
        result = self.rqc.execute(request)

        # 4. Validate
        self.assertEqual(RqcResponseStatus.COMPLETED, result.status)
        self.assertIn("success", str(result.result))
        self.assertGreaterEqual(self.http_client.get_with_authorization.call_count, 4)

        self.http_client.post_with_authorization.assert_called_once_with(
            slug_name=self.slug_name,
            data=request.to_input_data(),
            timeout=30,
        )

    # ---------------------------------------------------------
    # Scenario: error in result handler during polling (status COMPLETED)
    # ---------------------------------------------------------
    def test_execute_when_polling_fails_on_result_handler_error(self):
        # Scenario
        execution_id = "exec-handler-error"

        # Create execution (POST) OK
        post_resp = make_response(json_data=execution_id)
        self.http_client.post_with_authorization.return_value = post_resp

        # Polling sequence: RUNNING -> COMPLETED (with result)
        running_resp = make_response(json_data={"progress": {"status": "RUNNING"}})
        completed_resp = make_response(
            json_data={
                "progress": {"status": "COMPLETED"},
                "result": '{ "answer": "large text" ... broken due to LLM output window',  # Invalid JSON format
            }
        )
        self.http_client.get_with_authorization.side_effect = [
            running_resp,
            completed_resp,
        ]

        # Action
        request = RqcRequest(payload={"job": "result-handler-error"})
        result = self.rqc.execute(
            request=request,
        )

        # Validation
        self.assertEqual(RqcResponseStatus.ERROR, result.status)
        self.assertEqual(
            "Error during polling: Error while processing the response in the result handler (JsonResultHandler): "
            "Expecting ',' delimiter: line 1 column 26 (char 25)",
            result.error
        )
        self.assertGreaterEqual(self.http_client.get_with_authorization.call_count, 2)
        self.http_client.post_with_authorization.assert_called_once()

    def test_execute_many_when_all_responses_are_completed(self):
        # Scenario: 10 requests that complete successfully in parallel
        num_requests = 10

        # post_with_authorization should return a response whose .json() is the execution_id string
        def delayed_post(slug_name, data, timeout=30):
            # use the request id embedded in payload to build execution id
            exec_id = f"exec-{data['input_data']['id']}"
            # simulate small stagger to mimic network latency
            time.sleep(0.01)
            return make_response(json_data=exec_id)

        # get_with_authorization should return COMPLETED for each execution_id
        def delayed_get(execution_id, timeout=30):
            # small sleep to allow concurrency effects
            time.sleep(0.005)
            return make_response(json_data={
                "progress": {"status": "COMPLETED"},
                "result": {"execution_id": execution_id}
            })

        self.http_client.post_with_authorization.side_effect = delayed_post
        self.http_client.get_with_authorization.side_effect = delayed_get

        # prepare requests list
        requests_list = [RqcRequest(payload={"id": i}) for i in range(num_requests)]

        # Action
        results = self.rqc.execute_many(
            request_list=requests_list
        )

        # Validation 1: every response status is COMPLETED
        for resp in results:
            self.assertEqual(resp.status, RqcResponseStatus.COMPLETED, f"Expected COMPLETED but got {resp.status}")

        # Validation 2: number of requests == number of responses
        self.assertEqual(len(results), len(requests_list))

        # Validation 3: each response references its respective request (by identity and order)
        for req, resp in zip(requests_list, results, strict=True):
            self.assertIs(resp.request, req, "Response does not reference its respective request (identity mismatch)")

    def test_execute_many_when_request_list_is_empty(self):
        # Scenario
        requests_list = []

        # Action
        responses = self.rqc.execute_many(
            request_list=requests_list
        )

        # Validation
        self.assertEqual(0, len(requests_list))
        self.assertEqual(len(requests_list), len(responses))

    def test_execute_many_with_exceptions_and_mixed_statuses(self):
        num_requests = 10

        # Definition of polling behavior types
        # 7 COMPLETED, 1 FAILURE, 1 TIMEOUT (simulated via timeout), 1 ERROR (simulated via HTTP 500)
        behavior_by_id = {
            **dict.fromkeys(range(7), "COMPLETED"),
            7: "FAILURE",
            8: "TIMEOUT",
            9: "ERROR",
        }

        def post_with_authorization(slug_name, data, timeout=30):
            exec_id = f"exec-{data['input_data']['id']}"
            return make_response(json_data=exec_id)

        def get_with_authorization(execution_id, timeout=30):
            req_id = int(execution_id.split("-")[1])
            behavior = behavior_by_id[req_id]

            if behavior == "TIMEOUT":
                # Simulate long polling until poll_max_duration is reached
                time.sleep(self.rqc.get_result_options.poll_max_duration + 0.1)
                return make_response(json_data={"progress": {"status": "PENDING"}})

            elif behavior == "ERROR":
                # Simulate 4xx server error
                err = requests.HTTPError("HTTP 403 Forbidden")
                err.response = make_response(json_data={}, status_code=403)
                raise err

            elif behavior == "FAILURE":
                return make_response(json_data={"progress": {"status": "FAILURE"}})

            else:  # COMPLETED
                return make_response(json_data={"progress": {"status": "COMPLETED"}})

        self.http_client.post_with_authorization.side_effect = post_with_authorization
        self.http_client.get_with_authorization.side_effect = get_with_authorization

        # Prepare requests
        requests_list = [RqcRequest(payload={"id": i}) for i in range(num_requests)]

        # Action
        results = self.rqc.execute_many(
            request_list=requests_list
        )

        # Validation 1: total number of responses = number of requests
        self.assertEqual(len(results), num_requests)

        # Validation 2: each response references its respective request
        for req, resp in zip(requests_list, results, strict=True):
            self.assertIs(resp.request, req)

        # Validation 3: final statuses
        statuses = [r.status for r in results]

        self.assertEqual(sum(s == RqcResponseStatus.COMPLETED for s in statuses), 7)
        self.assertEqual(sum(s == RqcResponseStatus.FAILURE for s in statuses), 1)
        self.assertEqual(sum(s == RqcResponseStatus.TIMEOUT for s in statuses), 1)
        self.assertEqual(sum(s == RqcResponseStatus.ERROR for s in statuses), 1)


if __name__ == "__main__":
    unittest.main()
