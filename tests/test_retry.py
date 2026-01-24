"""Tests for retry utilities."""

import unittest
from unittest.mock import MagicMock, patch

import requests

from stkai._retry import MaxRetriesExceededError, RetryAttempt, Retrying


class TestRetryAttempt(unittest.TestCase):
    """Tests for RetryAttempt dataclass."""

    def test_is_last_attempt_false_when_not_last(self):
        """Should return False when not on last attempt."""
        attempt = RetryAttempt(attempt_number=0, max_retries=3)
        self.assertFalse(attempt.is_last_attempt)

        attempt = RetryAttempt(attempt_number=2, max_retries=3)
        self.assertFalse(attempt.is_last_attempt)

    def test_is_last_attempt_true_when_last(self):
        """Should return True when on last attempt."""
        attempt = RetryAttempt(attempt_number=3, max_retries=3)
        self.assertTrue(attempt.is_last_attempt)

    def test_is_frozen(self):
        """Should be immutable."""
        attempt = RetryAttempt(attempt_number=0, max_retries=3)
        with self.assertRaises(AttributeError):
            attempt.attempt_number = 1  # type: ignore


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
                backoff_factor=1.0,
                retry_on_exceptions=(ValueError,),
            ):
                with attempt:
                    raise ValueError("Test")

        # Verify backoff: 1.0 * 2^0, 1.0 * 2^1, 1.0 * 2^2
        calls = [call[0][0] for call in mock_sleep.call_args_list]
        self.assertEqual(calls, [1.0, 2.0, 4.0])

    @patch("stkai._retry.sleep_with_jitter")
    def test_custom_backoff_factor(self, mock_sleep: MagicMock):
        """Should use custom backoff factor."""
        with self.assertRaises(MaxRetriesExceededError):
            for attempt in Retrying(
                max_retries=2,
                backoff_factor=0.5,
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
        """Should provide correct attempt number in each iteration."""
        attempt_numbers = []

        for attempt_ctx in Retrying(max_retries=2, retry_on_exceptions=()):
            with attempt_ctx as attempt:
                attempt_numbers.append(attempt.attempt_number)
                break  # Exit after first attempt

        self.assertEqual(attempt_numbers, [0])

    @patch("stkai._retry.sleep_with_jitter")
    def test_attempt_metadata_available_in_loop(self, mock_sleep: MagicMock):
        """Should provide attempt metadata in the retry loop."""
        attempts = []

        with self.assertRaises(MaxRetriesExceededError):
            for attempt_ctx in Retrying(
                max_retries=2,
                retry_on_exceptions=(ValueError,),
            ):
                with attempt_ctx as attempt:
                    attempts.append({
                        "number": attempt.attempt_number,
                        "is_last": attempt.is_last_attempt,
                    })
                    raise ValueError("Test")

        self.assertEqual(
            attempts,
            [
                {"number": 0, "is_last": False},
                {"number": 1, "is_last": False},
                {"number": 2, "is_last": True},
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


if __name__ == "__main__":
    unittest.main()
