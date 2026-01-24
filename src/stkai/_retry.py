"""
Retry utilities with exponential backoff.

Inspired by Tenacity's Retrying class, this module provides a context manager
for implementing retry logic with configurable backoff and exception handling.

Example:
    >>> from stkai._retry import Retrying
    >>> for attempt in Retrying(max_retries=3, backoff_factor=0.5):
    ...     with attempt:
    ...         response = http_client.post(url, data=payload)
    ...         response.raise_for_status()
    ...         return response.json()
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import requests

from stkai._utils import sleep_with_jitter

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RetryableError(Exception):
    """
    Base class for exceptions that should trigger automatic retry.

    Exceptions extending this class are automatically retried by the Retrying
    context manager without needing explicit configuration in retry_on_exceptions.

    This follows the Open/Closed principle - new retryable exceptions can be
    added by extending this class, without modifying the Retrying class.

    Example:
        >>> class MyTransientError(RetryableError):
        ...     '''Custom retryable error for my service.'''
        ...     pass
        >>>
        >>> for attempt in Retrying(max_retries=3):
        ...     with attempt:
        ...         if some_condition:
        ...             raise MyTransientError("Temporary failure")
        ...         break  # Success
    """

    pass


class MaxRetriesExceededError(Exception):
    """
    Raised when all retry attempts are exhausted.

    This exception wraps the last exception that occurred during retry attempts,
    providing access to the original error for debugging.

    Attributes:
        message: Human-readable error message.
        last_exception: The original exception from the last retry attempt.

    Example:
        >>> try:
        ...     for attempt in Retrying(max_retries=3):
        ...         with attempt:
        ...             raise ConnectionError("Server unavailable")
        ... except MaxRetriesExceededError as e:
        ...     print(f"Failed after retries: {e}")
        ...     print(f"Original error: {e.last_exception}")
    """

    def __init__(self, message: str, last_exception: Exception | None = None):
        super().__init__(message)
        self.last_exception = last_exception


@dataclass(frozen=True)
class RetryAttempt:
    """
    Represents a single retry attempt.

    This dataclass provides metadata about the current attempt within a retry loop,
    useful for logging and conditional logic.

    Attributes:
        attempt_number: Zero-based index of the current attempt (0 = first attempt).
        max_retries: Maximum number of retry attempts configured.

    Example:
        >>> for attempt_ctx in Retrying(max_retries=3):
        ...     with attempt_ctx as attempt:
        ...         print(f"Attempt {attempt.attempt_number + 1}/{attempt.max_retries + 1}")
        ...         if attempt.is_last_attempt:
        ...             print("This is the last attempt!")
    """

    attempt_number: int
    max_retries: int

    @property
    def is_last_attempt(self) -> bool:
        """Return True if this is the last retry attempt."""
        return self.attempt_number >= self.max_retries


class Retrying:
    """
    Context manager for retry with exponential backoff.

    This class provides a Tenacity-inspired interface for implementing retry logic.
    It supports configurable retry conditions based on HTTP status codes and
    exception types, with exponential backoff between attempts.

    Usage:
        >>> for attempt in Retrying(max_retries=3, backoff_factor=0.5):
        ...     with attempt:
        ...         response = http_client.post(url, data=payload)
        ...         response.raise_for_status()
        ...         return response.json()

    Args:
        max_retries: Maximum number of retry attempts (default: 3).
            Use 0 to disable retries (single attempt only).
        backoff_factor: Base multiplier for exponential backoff (default: 0.5).
            Sleep time = backoff_factor * (2 ** attempt_number)
            Example: With factor=0.5, delays are 0.5s, 1s, 2s, 4s...
        retry_on_status_codes: HTTP status codes that trigger retry.
            Only applies to RequestException with response attached.
            Default includes transient server errors:
            - 408 Request Timeout: Server closed connection (client took too long)
            - 429 Too Many Requests: Rate limited, respects Retry-After header
            - 500 Internal Server Error
            - 502 Bad Gateway
            - 503 Service Unavailable
            - 504 Gateway Timeout
        retry_on_exceptions: Exception types that trigger retry (default: Timeout, ConnectionError).
            These exceptions always trigger retry regardless of status code.
        skip_retry_on_exceptions: Exception types that never trigger retry.
            Takes precedence over retry_on_exceptions.
        logger_prefix: Prefix for log messages (e.g., "Agent(my-id)").

    Raises:
        MaxRetriesExceededError: When all retry attempts are exhausted.
            Contains the last exception in the `last_exception` attribute.

    Note:
        - Exceptions extending RetryableError are automatically retried (opt-in via inheritance)
        - By default, transient errors (408, 429, 5xx) trigger retry
        - HTTP 429 responses respect the Retry-After header when calculating wait time
        - The loop naturally exits on success (no exception raised)
        - Exceptions not matching retry conditions are re-raised immediately
    """

    # Maximum Retry-After value to respect (in seconds).
    # Protects against abusive or buggy servers sending unreasonably large values.
    MAX_RETRY_AFTER = 60.0

    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        retry_on_status_codes: tuple[int, ...] = (408, 429, 500, 502, 503, 504),
        retry_on_exceptions: tuple[type[Exception], ...] = (
            requests.Timeout,
            requests.ConnectionError,
        ),
        skip_retry_on_exceptions: tuple[type[Exception], ...] = (),
        logger_prefix: str = "",
    ):
        # Validate invariants
        assert max_retries >= 0, f"max_retries must be >= 0, got {max_retries}"
        assert backoff_factor > 0, f"backoff_factor must be > 0, got {backoff_factor}"
        assert retry_on_status_codes is not None, "retry_on_status_codes cannot be None"
        assert retry_on_exceptions is not None, "retry_on_exceptions cannot be None"
        assert skip_retry_on_exceptions is not None, "skip_retry_on_exceptions cannot be None"

        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.retry_on_status_codes = set(retry_on_status_codes)
        self.retry_on_exceptions = retry_on_exceptions
        self.skip_retry_on_exceptions = skip_retry_on_exceptions
        self.logger_prefix = logger_prefix

        self._current_attempt = 0
        self._last_exception: Exception | None = None

    def __iter__(self) -> Generator[_RetryContext, None, None]:
        """Yield retry contexts for each attempt."""
        for attempt in range(self.max_retries + 1):
            self._current_attempt = attempt
            yield _RetryContext(self, attempt)

    def _should_retry(self, exception: Exception) -> bool:
        """
        Determine if exception should trigger a retry.

        Args:
            exception: The exception that occurred during the attempt.

        Returns:
            True if the exception should trigger a retry, False otherwise.

        Logic:
            1. Skip retry for exceptions in skip_retry_on_exceptions
            2. For RequestException with response: retry if status code is in retry_on_status_codes
            3. Auto-retry if exception extends RetryableError (opt-in via inheritance)
            4. Retry on configured exception types (Timeout, ConnectionError, etc.)
        """
        # Skip retry for specific exceptions (highest priority)
        if isinstance(exception, self.skip_retry_on_exceptions):
            return False

        # Check HTTP status codes for RequestException
        if isinstance(exception, requests.RequestException):
            response = getattr(exception, "response", None)
            if response is not None:
                return response.status_code in self.retry_on_status_codes

        # Auto-retry if exception declares itself retryable via inheritance
        if isinstance(exception, RetryableError):
            return True

        # Retry on configured exception types (for external libs like requests)
        return isinstance(exception, self.retry_on_exceptions)

    def _handle_retry(self, exception: Exception) -> None:
        """
        Handle retry: log, sleep, prepare for next attempt.

        For HTTP 429 responses, respects the Retry-After header if present.

        Args:
            exception: The exception that triggered the retry.
        """
        self._last_exception = exception
        sleep_time = self._calculate_wait_time(exception)

        prefix = f"{self.logger_prefix} | " if self.logger_prefix else ""
        logger.warning(
            f"{prefix}Attempt {self._current_attempt + 1}/{self.max_retries + 1} failed: {exception}"
        )
        logger.warning(
            f"{prefix}Retrying in {sleep_time:.1f}s..."
        )
        sleep_with_jitter(sleep_time)

    def _calculate_wait_time(self, exception: Exception) -> float:
        """
        Calculate wait time, respecting Retry-After header if present.

        For HTTP 429 responses with a valid Retry-After header, uses the
        maximum of the header value and the exponential backoff time.

        Args:
            exception: The exception that occurred during the attempt.

        Returns:
            The wait time in seconds before the next retry attempt.
        """
        base_wait: float = self.backoff_factor * (2 ** self._current_attempt)

        # Check for Retry-After header on 429 responses
        if isinstance(exception, requests.HTTPError):
            response: requests.Response | None = getattr(exception, "response", None)
            if response is not None and response.status_code == 429:
                retry_after = self._parse_retry_after(response)
                if retry_after is not None:
                    # Use the larger of Retry-After and exponential backoff
                    return float(max(retry_after, base_wait))

        return base_wait

    def _parse_retry_after(self, response: requests.Response) -> float | None:
        """
        Parse Retry-After header from response.

        Supports numeric seconds format. HTTP-date format is not supported.
        Values exceeding MAX_RETRY_AFTER are ignored to protect against
        abusive or buggy servers.

        Args:
            response: The HTTP response to parse.

        Returns:
            The Retry-After value in seconds, or None if not present/invalid.
        """
        header = response.headers.get("Retry-After")
        if not header:
            return None

        # Try parsing as seconds
        try:
            seconds = float(header)
            # Cap at MAX_RETRY_AFTER to protect against abusive values
            if seconds <= self.MAX_RETRY_AFTER:
                return seconds
            else:
                prefix = f"{self.logger_prefix} | " if self.logger_prefix else ""
                logger.warning(
                    f"{prefix}Retry-After header ({seconds}s) exceeds MAX_RETRY_AFTER "
                    f"({self.MAX_RETRY_AFTER}s). Using exponential backoff instead."
                )
                return None
        except (TypeError, ValueError):
            # Retry-After value might be an HTTP-date string, which we don't support
            return None

    def _handle_exhausted(self, exception: Exception) -> None:
        """
        Handle when all retries are exhausted.

        Args:
            exception: The exception from the last attempt.

        Raises:
            MaxRetriesExceededError: Always raised with the last exception.
        """
        self._last_exception = exception
        prefix = f"{self.logger_prefix} | " if self.logger_prefix else ""
        logger.error(
            f"{prefix}Max retries ({self.max_retries}) exceeded. Last error: {exception}"
        )
        raise MaxRetriesExceededError(
            message=f"Max retries exceeded. Last error: {exception}",
            last_exception=exception,
        ) from exception


class _RetryContext:
    """
    Context for a single retry attempt (internal).

    This class is yielded by `Retrying.__iter__()` and implements the context
    manager protocol to handle exceptions within the retry loop.

    On success (no exception): exits normally, loop continues to natural end
    On retryable exception: suppresses exception, loop continues
    On non-retryable exception: re-raises exception, loop exits
    On exhausted retries: raises MaxRetriesExceededError
    """

    def __init__(self, retrying: Retrying, attempt: int):
        self._retrying = retrying
        self.attempt = attempt

    def __enter__(self) -> RetryAttempt:
        """Enter context and return attempt metadata."""
        return RetryAttempt(
            attempt_number=self.attempt,
            max_retries=self._retrying.max_retries,
        )

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        """
        Handle exception (if any) and decide whether to retry.

        Returns:
            True to suppress exception and continue loop (retry)
            False to propagate exception (no retry)
        """
        if exc_val is None:
            # Success - caller should break/return to exit loop
            return False

        # Only handle Exception, not BaseException (KeyboardInterrupt, etc.)
        if not isinstance(exc_val, Exception):
            return False

        if not self._retrying._should_retry(exc_val):
            # Don't retry - re-raise exception
            return False

        # If max_retries is 0, retries are disabled - let original exception propagate
        # without wrapping in MaxRetriesExceededError
        if self._retrying.max_retries == 0:
            return False

        if self.attempt >= self._retrying.max_retries:
            # Exhausted - raise MaxRetriesExceededError
            self._retrying._handle_exhausted(exc_val)
            return False  # Never reached

        # Retry - suppress exception and continue loop
        self._retrying._handle_retry(exc_val)
        return True  # Suppress exception
