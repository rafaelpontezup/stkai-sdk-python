"""Tests for retry utilities."""

import unittest
from unittest.mock import MagicMock, patch

import requests

from stkai._retry import MaxRetriesExceededError, RetryableError, RetryAttemptContext, Retrying


class TestRetryAttemptContext(unittest.TestCase):
    """Tests for RetryAttemptContext dataclass."""

    def test_is_last_attempt_false_when_not_last(self):
        """Should return False when not on last attempt."""
        # max_attempts=4 means attempts 1, 2, 3, 4 (where 4 is last)
        retrying = Retrying(max_retries=3)  # max_attempts=4
        attempt = RetryAttemptContext(_retrying=retrying, attempt_number=1)
        self.assertFalse(attempt.is_last_attempt)

        attempt = RetryAttemptContext(_retrying=retrying, attempt_number=3)
        self.assertFalse(attempt.is_last_attempt)

    def test_is_last_attempt_true_when_last(self):
        """Should return True when on last attempt."""
        # max_attempts=4 means attempt 4 is the last
        retrying = Retrying(max_retries=3)  # max_attempts=4
        attempt = RetryAttemptContext(_retrying=retrying, attempt_number=4)
        self.assertTrue(attempt.is_last_attempt)

    def test_is_frozen(self):
        """Should be immutable."""
        retrying = Retrying(max_retries=3)
        attempt = RetryAttemptContext(_retrying=retrying, attempt_number=1)
        with self.assertRaises(AttributeError):
            attempt.attempt_number = 2  # type: ignore

    def test_max_attempts_property(self):
        """Should return max_attempts from Retrying."""
        retrying = Retrying(max_retries=5)  # max_attempts=6
        attempt = RetryAttemptContext(_retrying=retrying, attempt_number=1)
        self.assertEqual(attempt.max_attempts, 6)


class TestMaxRetriesExceededError(unittest.TestCase):
    """Tests for MaxRetriesExceededError exception."""

    def test_message_is_set(self):
        """Should set the message correctly."""
        error = MaxRetriesExceededError("Test message")
        self.assertEqual(str(error), "Test message")

    def test_last_exception_is_set(self):
        """Should set the last_exception correctly."""
        original = ValueError("Original error")
        error = MaxRetriesExceededError("Test message", last_exception=original)
        self.assertEqual(error.last_exception, original)

    def test_last_exception_is_none_by_default(self):
        """Should have None as default last_exception."""
        error = MaxRetriesExceededError("Test message")
        self.assertIsNone(error.last_exception)


class TestRetryingBasicUsage(unittest.TestCase):
    """Tests for basic Retrying usage."""

    def test_success_on_first_attempt(self):
        """Should succeed on first attempt without retry."""
        call_count = 0

        for attempt in Retrying(max_retries=3):
            with attempt:
                call_count += 1
                # Success - break out of retry loop
                break

        self.assertEqual(call_count, 1)

    def test_no_retry_when_max_retries_is_zero(self):
        """Should not retry when max_retries is 0."""
        call_count = 0

        with self.assertRaises(ValueError):
            for attempt in Retrying(max_retries=0):
                with attempt:
                    call_count += 1
                    raise ValueError("Test error")

        self.assertEqual(call_count, 1)

    @patch("stkai._retry.sleep_with_jitter")
    def test_retry_on_configured_exception(self, mock_sleep: MagicMock):
        """Should retry on configured exception types."""
        call_count = 0

        for attempt in Retrying(
            max_retries=3,
            retry_on_exceptions=(ValueError,),
        ):
            with attempt:
                call_count += 1
                if call_count < 3:
                    raise ValueError("Temporary error")
                # Success on 3rd attempt - break out of retry loop
                break

        self.assertEqual(call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)  # 2 retries

    @patch("stkai._retry.sleep_with_jitter")
    def test_raises_max_retries_exceeded_when_exhausted(self, mock_sleep: MagicMock):
        """Should raise MaxRetriesExceededError when all retries exhausted."""
        call_count = 0

        with self.assertRaises(MaxRetriesExceededError) as ctx:
            for attempt in Retrying(
                max_retries=3,
                retry_on_exceptions=(ValueError,),
            ):
                with attempt:
                    call_count += 1
                    raise ValueError("Persistent error")

        self.assertEqual(call_count, 4)  # 1 original + 3 retries
        self.assertIsInstance(ctx.exception.last_exception, ValueError)
        self.assertEqual(mock_sleep.call_count, 3)

    def test_does_not_retry_on_non_configured_exception(self):
        """Should not retry on exceptions not in retry_on_exceptions."""
        call_count = 0

        with self.assertRaises(TypeError):
            for attempt in Retrying(
                max_retries=3,
                retry_on_exceptions=(ValueError,),  # Only ValueError
            ):
                with attempt:
                    call_count += 1
                    raise TypeError("Different error")

        self.assertEqual(call_count, 1)

    def test_does_not_retry_on_skip_exceptions(self):
        """Should not retry on exceptions in skip_retry_on_exceptions."""
        call_count = 0

        with self.assertRaises(ValueError):
            for attempt in Retrying(
                max_retries=3,
                retry_on_exceptions=(ValueError, TypeError),
                skip_retry_on_exceptions=(ValueError,),  # Skip ValueError
            ):
                with attempt:
                    call_count += 1
                    raise ValueError("Skip this one")

        self.assertEqual(call_count, 1)


class TestRetryingHttpStatusCodes(unittest.TestCase):
    """Tests for Retrying with HTTP status codes."""

    @patch("stkai._retry.sleep_with_jitter")
    def test_retry_on_408_request_timeout(self, mock_sleep: MagicMock):
        """Should retry on 408 Request Timeout (transient error) by default."""
        call_count = 0

        def make_http_error(status_code: int) -> requests.HTTPError:
            response = MagicMock()
            response.status_code = status_code
            error = requests.HTTPError()
            error.response = response
            return error

        # Using default retry_on_status_codes which includes 408
        for attempt in Retrying(max_retries=2):
            with attempt:
                call_count += 1
                if call_count < 3:
                    raise make_http_error(408)
                # Success on 3rd attempt
                break

        self.assertEqual(call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("stkai._retry.sleep_with_jitter")
    def test_retry_on_429_status_code(self, mock_sleep: MagicMock):
        """Should retry on 429 Too Many Requests by default."""
        call_count = 0

        def make_http_error(status_code: int, headers: dict | None = None) -> requests.HTTPError:
            response = MagicMock()
            response.status_code = status_code
            response.headers = headers or {}
            error = requests.HTTPError()
            error.response = response
            return error

        # Using default retry_on_status_codes which now includes 429
        for attempt in Retrying(max_retries=2):
            with attempt:
                call_count += 1
                if call_count < 3:
                    raise make_http_error(429)
                # Success on 3rd attempt
                break

        self.assertEqual(call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("stkai._retry.sleep_with_jitter")
    def test_retry_on_5xx_status_codes(self, mock_sleep: MagicMock):
        """Should retry on configured 5xx status codes."""
        call_count = 0

        def make_http_error(status_code: int) -> requests.HTTPError:
            response = MagicMock()
            response.status_code = status_code
            error = requests.HTTPError()
            error.response = response
            return error

        for attempt in Retrying(
            max_retries=2,
            retry_on_status_codes=(500, 503),
        ):
            with attempt:
                call_count += 1
                if call_count < 3:
                    raise make_http_error(503)
                # Success on 3rd attempt
                break

        self.assertEqual(call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    def test_no_retry_on_4xx_status_codes(self):
        """Should not retry on 4xx status codes (client errors)."""
        call_count = 0

        def make_http_error(status_code: int) -> requests.HTTPError:
            response = MagicMock()
            response.status_code = status_code
            error = requests.HTTPError()
            error.response = response
            return error

        with self.assertRaises(requests.HTTPError):
            for attempt in Retrying(max_retries=3):
                with attempt:
                    call_count += 1
                    raise make_http_error(400)

        self.assertEqual(call_count, 1)

    def test_no_retry_on_401_unauthorized(self):
        """Should not retry on 401 Unauthorized."""
        call_count = 0

        def make_http_error(status_code: int) -> requests.HTTPError:
            response = MagicMock()
            response.status_code = status_code
            error = requests.HTTPError()
            error.response = response
            return error

        with self.assertRaises(requests.HTTPError):
            for attempt in Retrying(max_retries=3):
                with attempt:
                    call_count += 1
                    raise make_http_error(401)

        self.assertEqual(call_count, 1)

    def test_no_retry_on_404_not_found(self):
        """Should not retry on 404 Not Found."""
        call_count = 0

        def make_http_error(status_code: int) -> requests.HTTPError:
            response = MagicMock()
            response.status_code = status_code
            error = requests.HTTPError()
            error.response = response
            return error

        with self.assertRaises(requests.HTTPError):
            for attempt in Retrying(max_retries=3):
                with attempt:
                    call_count += 1
                    raise make_http_error(404)

        self.assertEqual(call_count, 1)


class TestRetryingNetworkErrors(unittest.TestCase):
    """Tests for Retrying with network errors."""

    @patch("stkai._retry.sleep_with_jitter")
    def test_retry_on_timeout(self, mock_sleep: MagicMock):
        """Should retry on requests.Timeout by default."""
        call_count = 0

        for attempt in Retrying(max_retries=2):
            with attempt:
                call_count += 1
                if call_count < 3:
                    raise requests.Timeout("Connection timed out")
                # Success on 3rd attempt
                break

        self.assertEqual(call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("stkai._retry.sleep_with_jitter")
    def test_retry_on_connection_error(self, mock_sleep: MagicMock):
        """Should retry on requests.ConnectionError by default."""
        call_count = 0

        for attempt in Retrying(max_retries=2):
            with attempt:
                call_count += 1
                if call_count < 3:
                    raise requests.ConnectionError("Connection refused")
                # Success on 3rd attempt
                break

        self.assertEqual(call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)


class TestRetryingBackoff(unittest.TestCase):
    """Tests for exponential backoff calculation."""

    @patch("stkai._retry.sleep_with_jitter")
    def test_exponential_backoff(self, mock_sleep: MagicMock):
        """Should use exponential backoff for sleep times."""
        with self.assertRaises(MaxRetriesExceededError):
            for attempt in Retrying(
                max_retries=3,
                initial_delay=1.0,
                retry_on_exceptions=(ValueError,),
            ):
                with attempt:
                    raise ValueError("Test")

        # Verify backoff: 1.0 * 2^0, 1.0 * 2^1, 1.0 * 2^2
        calls = [call[0][0] for call in mock_sleep.call_args_list]
        self.assertEqual(calls, [1.0, 2.0, 4.0])

    @patch("stkai._retry.sleep_with_jitter")
    def test_custom_initial_delay(self, mock_sleep: MagicMock):
        """Should use custom backoff factor."""
        with self.assertRaises(MaxRetriesExceededError):
            for attempt in Retrying(
                max_retries=2,
                initial_delay=0.5,
                retry_on_exceptions=(ValueError,),
            ):
                with attempt:
                    raise ValueError("Test")

        # Verify backoff: 0.5 * 2^0, 0.5 * 2^1
        calls = [call[0][0] for call in mock_sleep.call_args_list]
        self.assertEqual(calls, [0.5, 1.0])


class TestRetryingAttemptMetadata(unittest.TestCase):
    """Tests for attempt metadata in retry loop."""

    def test_attempt_number_increments(self):
        """Should provide correct attempt number in each iteration (1-indexed)."""
        attempt_numbers = []

        for attempt in Retrying(max_retries=2, retry_on_exceptions=()):
            with attempt:
                attempt_numbers.append(attempt.attempt_number)
                break  # Exit after first attempt

        self.assertEqual(attempt_numbers, [1])  # 1-indexed

    @patch("stkai._retry.sleep_with_jitter")
    def test_attempt_metadata_available_in_loop(self, mock_sleep: MagicMock):
        """Should provide attempt metadata in the retry loop (1-indexed)."""
        attempts = []

        with self.assertRaises(MaxRetriesExceededError):
            for attempt in Retrying(
                max_retries=2,
                retry_on_exceptions=(ValueError,),
            ):
                with attempt:
                    attempts.append({
                        "number": attempt.attempt_number,
                        "is_last": attempt.is_last_attempt,
                    })
                    raise ValueError("Test")

        # max_retries=2 → max_attempts=3 (attempts 1, 2, 3)
        self.assertEqual(
            attempts,
            [
                {"number": 1, "is_last": False},
                {"number": 2, "is_last": False},
                {"number": 3, "is_last": True},
            ],
        )


class TestRetryingLogging(unittest.TestCase):
    """Tests for retry logging."""

    @patch("stkai._retry.sleep_with_jitter")
    @patch("stkai._retry.logger")
    def test_logs_retry_with_prefix(self, mock_logger: MagicMock, mock_sleep: MagicMock):
        """Should log retries with the configured prefix."""
        for attempt in Retrying(
            max_retries=1,
            logger_prefix="Agent(test)",
            retry_on_exceptions=(ValueError,),
        ):
            with attempt:
                if mock_sleep.call_count == 0:
                    raise ValueError("Test error")
                # Success on 2nd attempt
                break

        # Verify warning was logged with prefix
        warning_calls = [call[0][0] for call in mock_logger.warning.call_args_list]
        self.assertTrue(any("Agent(test)" in call for call in warning_calls))

    @patch("stkai._retry.sleep_with_jitter")
    @patch("stkai._retry.logger")
    def test_logs_exhausted_error(self, mock_logger: MagicMock, mock_sleep: MagicMock):
        """Should log error when retries are exhausted."""
        with self.assertRaises(MaxRetriesExceededError):
            for attempt in Retrying(
                max_retries=1,
                retry_on_exceptions=(ValueError,),
            ):
                with attempt:
                    raise ValueError("Test error")

        # Verify error was logged
        self.assertTrue(mock_logger.error.called)
        error_msg = mock_logger.error.call_args[0][0]
        self.assertIn("Max retries", error_msg)


class TestRetryableError(unittest.TestCase):
    """Tests for RetryableError base class."""

    def test_retryable_error_is_exception(self):
        """RetryableError should be an Exception."""
        self.assertTrue(issubclass(RetryableError, Exception))

    def test_custom_retryable_error_can_extend(self):
        """Custom exceptions can extend RetryableError."""
        class MyCustomError(RetryableError):
            pass

        error = MyCustomError("test")
        self.assertIsInstance(error, RetryableError)
        self.assertIsInstance(error, Exception)

    @patch("stkai._retry.sleep_with_jitter")
    def test_retryable_error_is_automatically_retried(self, mock_sleep: MagicMock):
        """Exceptions extending RetryableError should be automatically retried."""
        class MyRetryableError(RetryableError):
            pass

        call_count = 0

        for attempt in Retrying(max_retries=2):
            with attempt:
                call_count += 1
                if call_count < 3:
                    raise MyRetryableError("Temporary failure")
                # Success on 3rd attempt
                break

        self.assertEqual(call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("stkai._retry.sleep_with_jitter")
    def test_retryable_error_exhausts_retries(self, mock_sleep: MagicMock):
        """RetryableError should exhaust retries and raise MaxRetriesExceededError."""
        class MyRetryableError(RetryableError):
            pass

        call_count = 0

        with self.assertRaises(MaxRetriesExceededError) as ctx:
            for attempt in Retrying(max_retries=2):
                with attempt:
                    call_count += 1
                    raise MyRetryableError("Persistent failure")

        self.assertEqual(call_count, 3)  # 1 original + 2 retries
        self.assertIsInstance(ctx.exception.last_exception, MyRetryableError)

    def test_retryable_error_not_retried_when_in_skip_list(self):
        """RetryableError should not retry when in skip_retry_on_exceptions."""
        class MyRetryableError(RetryableError):
            pass

        call_count = 0

        with self.assertRaises(MyRetryableError):
            for attempt in Retrying(
                max_retries=3,
                skip_retry_on_exceptions=(MyRetryableError,),
            ):
                with attempt:
                    call_count += 1
                    raise MyRetryableError("Should not retry")

        self.assertEqual(call_count, 1)  # No retry

    def test_retryable_error_no_config_needed(self):
        """RetryableError does not need to be in retry_on_exceptions."""
        class MyRetryableError(RetryableError):
            pass

        # Empty retry_on_exceptions - but RetryableError should still work
        retrying = Retrying(
            max_retries=3,
            retry_on_exceptions=(),  # Empty!
        )

        self.assertTrue(retrying._should_retry(MyRetryableError("test")))


class TestTokenAcquisitionTimeoutErrorRetry(unittest.TestCase):
    """Tests for TokenAcquisitionTimeoutError retry behavior."""

    def test_rate_limit_timeout_error_is_retryable(self):
        """TokenAcquisitionTimeoutError should extend RetryableError."""
        from stkai._rate_limit import TokenAcquisitionTimeoutError

        self.assertTrue(issubclass(TokenAcquisitionTimeoutError, RetryableError))

    def test_rate_limit_timeout_error_is_automatically_retried(self):
        """TokenAcquisitionTimeoutError should be automatically retried by Retrying."""
        from stkai._rate_limit import TokenAcquisitionTimeoutError

        retrying = Retrying(max_retries=3)
        error = TokenAcquisitionTimeoutError(waited=5.0, max_wait_time=10.0)

        self.assertTrue(retrying._should_retry(error))

    @patch("stkai._retry.sleep_with_jitter")
    def test_rate_limit_timeout_error_retry_integration(self, mock_sleep: MagicMock):
        """TokenAcquisitionTimeoutError should work with Retrying context manager."""
        from stkai._rate_limit import TokenAcquisitionTimeoutError

        call_count = 0

        for attempt in Retrying(max_retries=2):
            with attempt:
                call_count += 1
                if call_count < 3:
                    raise TokenAcquisitionTimeoutError(waited=5.0, max_wait_time=10.0)
                # Success on 3rd attempt
                break

        self.assertEqual(call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)


class TestServerSideRateLimitErrorRetry(unittest.TestCase):
    """Tests for ServerSideRateLimitError retry behavior."""

    def test_server_side_rate_limit_error_is_retryable(self):
        """ServerSideRateLimitError should extend RetryableError."""
        from stkai._rate_limit import ServerSideRateLimitError

        self.assertTrue(issubclass(ServerSideRateLimitError, RetryableError))

    def test_server_side_rate_limit_error_is_automatically_retried(self):
        """ServerSideRateLimitError should be automatically retried by Retrying."""
        from stkai._rate_limit import ServerSideRateLimitError

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}

        retrying = Retrying(max_retries=3)
        error = ServerSideRateLimitError(mock_response)

        self.assertTrue(retrying._should_retry(error))

    @patch("stkai._retry.sleep_with_jitter")
    def test_server_side_rate_limit_error_retry_integration(self, mock_sleep: MagicMock):
        """ServerSideRateLimitError should work with Retrying context manager."""
        from stkai._rate_limit import ServerSideRateLimitError

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}

        call_count = 0

        for attempt in Retrying(max_retries=2):
            with attempt:
                call_count += 1
                if call_count < 3:
                    raise ServerSideRateLimitError(mock_response)
                # Success on 3rd attempt
                break

        self.assertEqual(call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("stkai._retry.sleep_with_jitter")
    def test_server_side_rate_limit_error_respects_retry_after(self, mock_sleep: MagicMock):
        """ServerSideRateLimitError should respect Retry-After header."""
        from stkai._rate_limit import ServerSideRateLimitError

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "15"}

        call_count = 0

        for attempt in Retrying(max_retries=1, initial_delay=0.5):
            with attempt:
                call_count += 1
                if call_count < 2:
                    raise ServerSideRateLimitError(mock_response)
                # Success on 2nd attempt
                break

        self.assertEqual(call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)

        # Should use max(Retry-After=15, backoff=0.5) = 15
        actual_sleep_time = mock_sleep.call_args[0][0]
        self.assertEqual(actual_sleep_time, 15.0)


class TestRetryingRetryAfterHeader(unittest.TestCase):
    """Tests for Retry-After header handling in Retrying."""

    @patch("stkai._retry.sleep_with_jitter")
    def test_retry_respects_retry_after_header(self, mock_sleep: MagicMock):
        """Should respect Retry-After header when calculating wait time."""
        call_count = 0

        def make_http_error_with_retry_after(retry_after: str) -> requests.HTTPError:
            response = MagicMock()
            response.status_code = 429
            response.headers = {"Retry-After": retry_after}
            error = requests.HTTPError()
            error.response = response
            return error

        for attempt in Retrying(max_retries=1, initial_delay=0.5):
            with attempt:
                call_count += 1
                if call_count < 2:
                    raise make_http_error_with_retry_after("10")  # 10 seconds
                # Success on 2nd attempt
                break

        self.assertEqual(call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)

        # Should use max(Retry-After, exponential_backoff) = max(10, 0.5) = 10
        actual_sleep_time = mock_sleep.call_args[0][0]
        self.assertEqual(actual_sleep_time, 10.0)

    @patch("stkai._retry.sleep_with_jitter")
    def test_retry_uses_backoff_when_greater_than_retry_after(self, mock_sleep: MagicMock):
        """Should use exponential backoff when it's greater than Retry-After."""
        call_count = 0

        def make_http_error_with_retry_after(retry_after: str) -> requests.HTTPError:
            response = MagicMock()
            response.status_code = 429
            response.headers = {"Retry-After": retry_after}
            error = requests.HTTPError()
            error.response = response
            return error

        # With initial_delay=5.0 and attempt=0, backoff = 5.0 * 2^0 = 5.0
        for attempt in Retrying(max_retries=1, initial_delay=5.0):
            with attempt:
                call_count += 1
                if call_count < 2:
                    raise make_http_error_with_retry_after("1")  # 1 second
                # Success on 2nd attempt
                break

        self.assertEqual(call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)

        # Should use max(Retry-After, exponential_backoff) = max(1, 5.0) = 5.0
        actual_sleep_time = mock_sleep.call_args[0][0]
        self.assertEqual(actual_sleep_time, 5.0)

    @patch("stkai._retry.sleep_with_jitter")
    def test_retry_caps_retry_after_at_max(self, mock_sleep: MagicMock):
        """Should ignore Retry-After values exceeding MAX_RETRY_AFTER."""
        call_count = 0

        def make_http_error_with_retry_after(retry_after: str) -> requests.HTTPError:
            response = MagicMock()
            response.status_code = 429
            response.headers = {"Retry-After": retry_after}
            error = requests.HTTPError()
            error.response = response
            return error

        for attempt in Retrying(max_retries=1, initial_delay=0.5):
            with attempt:
                call_count += 1
                if call_count < 2:
                    raise make_http_error_with_retry_after("3600")  # 1 hour - abusive!
                # Success on 2nd attempt
                break

        self.assertEqual(call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)

        # Should use exponential backoff instead of 3600
        actual_sleep_time = mock_sleep.call_args[0][0]
        self.assertLess(actual_sleep_time, Retrying.MAX_RETRY_AFTER)
        self.assertEqual(actual_sleep_time, 0.5)  # initial_delay * 2^0

    @patch("stkai._retry.sleep_with_jitter")
    def test_retry_uses_backoff_when_no_retry_after(self, mock_sleep: MagicMock):
        """Should use exponential backoff when Retry-After header is not present."""
        call_count = 0

        def make_http_error_without_header() -> requests.HTTPError:
            response = MagicMock()
            response.status_code = 429
            response.headers = {}  # No Retry-After
            error = requests.HTTPError()
            error.response = response
            return error

        for attempt in Retrying(max_retries=1, initial_delay=2.0):
            with attempt:
                call_count += 1
                if call_count < 2:
                    raise make_http_error_without_header()
                # Success on 2nd attempt
                break

        self.assertEqual(call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)

        # Should use exponential backoff: 2.0 * 2^0 = 2.0
        actual_sleep_time = mock_sleep.call_args[0][0]
        self.assertEqual(actual_sleep_time, 2.0)

    @patch("stkai._retry.sleep_with_jitter")
    def test_retry_ignores_invalid_retry_after_format(self, mock_sleep: MagicMock):
        """Should ignore non-numeric Retry-After values (e.g., HTTP-date)."""
        call_count = 0

        def make_http_error_with_date_retry_after() -> requests.HTTPError:
            response = MagicMock()
            response.status_code = 429
            # HTTP-date format (not supported)
            response.headers = {"Retry-After": "Wed, 21 Oct 2025 07:28:00 GMT"}
            error = requests.HTTPError()
            error.response = response
            return error

        for attempt in Retrying(max_retries=1, initial_delay=1.5):
            with attempt:
                call_count += 1
                if call_count < 2:
                    raise make_http_error_with_date_retry_after()
                # Success on 2nd attempt
                break

        self.assertEqual(call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)

        # Should fall back to exponential backoff: 1.5 * 2^0 = 1.5
        actual_sleep_time = mock_sleep.call_args[0][0]
        self.assertEqual(actual_sleep_time, 1.5)

    def test_429_in_default_retry_on_status_codes(self):
        """HTTP 429 should be in the default retry_on_status_codes."""
        retrying = Retrying()
        self.assertIn(429, retrying.retry_on_status_codes)

    def test_max_retry_after_constant_exists(self):
        """MAX_RETRY_AFTER constant should be defined."""
        self.assertTrue(hasattr(Retrying, "MAX_RETRY_AFTER"))
        self.assertEqual(Retrying.MAX_RETRY_AFTER, 60.0)


if __name__ == "__main__":
    unittest.main()
