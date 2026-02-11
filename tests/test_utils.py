"""Tests for internal utilities."""

import unittest
from unittest.mock import Mock

import requests

from stkai._rate_limit import TokenAcquisitionTimeoutError
from stkai._retry import MaxRetriesExceededError
from stkai._utils import is_timeout_exception


class TestIsTimeoutException(unittest.TestCase):
    """Tests for is_timeout_exception()."""

    # ---- True cases ----

    def test_requests_timeout(self):
        self.assertTrue(is_timeout_exception(requests.Timeout("timed out")))

    def test_python_builtin_timeout_error(self):
        self.assertTrue(is_timeout_exception(TimeoutError("polling timeout")))

    def test_token_acquisition_timeout_error(self):
        self.assertTrue(is_timeout_exception(TokenAcquisitionTimeoutError(waited=5.0, max_wait_time=3.0)))

    def test_http_408_request_timeout(self):
        response = Mock(spec=requests.Response)
        response.status_code = 408
        exc = requests.HTTPError("408 Request Timeout", response=response)
        exc.response = response
        self.assertTrue(is_timeout_exception(exc))

    def test_http_504_gateway_timeout(self):
        response = Mock(spec=requests.Response)
        response.status_code = 504
        exc = requests.HTTPError("504 Gateway Timeout", response=response)
        exc.response = response
        self.assertTrue(is_timeout_exception(exc))

    def test_max_retries_exceeded_wrapping_timeout(self):
        timeout = requests.Timeout("timed out")
        exc = MaxRetriesExceededError("Max retries exceeded", last_exception=timeout)
        self.assertTrue(is_timeout_exception(exc))

    def test_max_retries_exceeded_wrapping_http_504(self):
        response = Mock(spec=requests.Response)
        response.status_code = 504
        http_exc = requests.HTTPError("504 Gateway Timeout", response=response)
        http_exc.response = response
        exc = MaxRetriesExceededError("Max retries exceeded", last_exception=http_exc)
        self.assertTrue(is_timeout_exception(exc))

    # ---- False cases ----

    def test_generic_exception(self):
        self.assertFalse(is_timeout_exception(Exception("boom")))

    def test_runtime_error(self):
        self.assertFalse(is_timeout_exception(RuntimeError("broken pipe")))

    def test_http_500_is_not_timeout(self):
        response = Mock(spec=requests.Response)
        response.status_code = 500
        exc = requests.HTTPError("500 Server Error", response=response)
        exc.response = response
        self.assertFalse(is_timeout_exception(exc))

    def test_http_429_is_not_timeout(self):
        response = Mock(spec=requests.Response)
        response.status_code = 429
        exc = requests.HTTPError("429 Too Many Requests", response=response)
        exc.response = response
        self.assertFalse(is_timeout_exception(exc))

    def test_connection_error_is_not_timeout(self):
        self.assertFalse(is_timeout_exception(requests.ConnectionError("refused")))

    def test_max_retries_exceeded_wrapping_non_timeout(self):
        exc = MaxRetriesExceededError(
            "Max retries exceeded",
            last_exception=requests.ConnectionError("refused"),
        )
        self.assertFalse(is_timeout_exception(exc))


if __name__ == "__main__":
    unittest.main()
