"""
Retry utilities with exponential backoff.

Inspired by Tenacity's Retrying class, this module provides a context manager
for implementing retry logic with configurable backoff and exception handling.

Example:
    >>> from stkai._retry import Retrying
    >>> for attempt in Retrying(max_retries=3, initial_delay=0.5):
    ...     with attempt:
    ...         print(f"Attempt {attempt.attempt_number}/{attempt.max_attempts}")
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
class RetryAttemptContext:
    """
    Context manager for a single retry attempt.

    This class is yielded by `Retrying.__iter__()` and implements the context
    manager protocol to handle exceptions within the retry loop. It also provides
    metadata about the current attempt for logging and conditional logic.

    Attributes:
        attempt_number: One-based index of the current attempt (1 = first attempt).

    Properties:
        max_attempts: Total number of attempts (1 + max_retries).
        is_last_attempt: True if this is the final attempt.

    Behavior:
        On success (no exception): exits normally, loop continues to natural end
        On retryable exception: suppresses exception, loop continues
        On non-retryable exception: re-raises exception, loop exits
        On exhausted retries: raises MaxRetriesExceededError

    Example:
        >>> for attempt in Retrying(max_retries=3):
        ...     with attempt:
        ...         print(f"Attempt {attempt.attempt_number}/{attempt.max_attempts}")
        ...         response = http_client.post(url, data=payload)
        ...         response.raise_for_status()
        ...         return response.json()
    """

    _retrying: Retrying
    attempt_number: int

    def __post_init__(self) -> None:
        """Validate invariants."""
        assert self.max_attempts >= 1, \
            f"max_attempts must be >= 1, got {self.max_attempts}"
        assert self.attempt_number >= 1, \
            f"attempt_number must be >= 1 (1-indexed), got {self.attempt_number}"
        assert self.attempt_number <= self.max_attempts, \
            f"attempt_number ({self.attempt_number}) cannot exceed max_attempts ({self.max_attempts})"

    @property
    def max_attempts(self) -> int:
        """Total number of attempts (1 original + max_retries)."""
        return self._retrying.max_attempts

    @property
    def is_last_attempt(self) -> bool:
        """Return True if this is the last retry attempt."""
        return self.attempt_number >= self.max_attempts

    def __enter__(self) -> None:
        """Enter context. Attempt metadata is available on the object itself."""
        return None

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

        # If retry is disabled, let original exception propagate
        # without wrapping in MaxRetriesExceededError
        if not self._retrying.enabled:
            return False

        if self.attempt_number > self._retrying.max_retries:
            # Exhausted - raise MaxRetriesExceededError
            self._retrying._handle_exhausted(exc_val)
            return False  # Never reached

        # Retry - suppress exception and continue loop
        self._retrying._handle_retry(exc_val)
        return True  # Suppress exception


class Retrying:
    """
    Context manager for retry with exponential backoff.

    This class provides a Tenacity-inspired interface for implementing retry logic.
    It supports configurable retry conditions based on HTTP status codes and
    exception types, with exponential backoff between attempts.

    Usage:
        >>> for attempt in Retrying(max_retries=3, initial_delay=0.5):
        ...     with attempt:
        ...         response = http_client.post(url, data=payload)
        ...         response.raise_for_status()
        ...         return response.json()

    Args:
        max_retries: Maximum number of retry attempts (default: 3).
            Use 0 to disable retries (single attempt only).
        initial_delay: Initial delay in seconds for the first retry (default: 0.5).
            Subsequent retries use exponential backoff (delay doubles each attempt).
            Sleep time = initial_delay * (2 ** (attempt_number - 1))
            Example: With initial_delay=0.5, delays are 0.5s, 1s, 2s, 4s...
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
        initial_delay: float = 0.5,
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
        assert initial_delay > 0, f"initial_delay must be > 0, got {initial_delay}"
        assert retry_on_status_codes is not None, "retry_on_status_codes cannot be None"
        assert retry_on_exceptions is not None, "retry_on_exceptions cannot be None"
        assert skip_retry_on_exceptions is not None, "skip_retry_on_exceptions cannot be None"

        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.retry_on_status_codes = set(retry_on_status_codes)
        self.retry_on_exceptions = retry_on_exceptions
        self.skip_retry_on_exceptions = skip_retry_on_exceptions
        self.logger_prefix = logger_prefix

        self._current_attempt = 0
        self._last_exception: Exception | None = None

    @property
    def max_attempts(self) -> int:
        """Total number of attempts (1 original + max_retries)."""
        return self.max_retries + 1

    @property
    def enabled(self) -> bool:
        """Return True if retry is enabled (max_retries > 0)."""
        return self.max_retries > 0

    def __iter__(self) -> Generator[RetryAttemptContext, None, None]:
        """Yield retry contexts for each attempt (1-indexed)."""
        for attempt in range(1, self.max_attempts + 1):
            self._current_attempt = attempt
            yield RetryAttemptContext(self, attempt)

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
        sleep_seconds = self._calculate_wait_time(exception)

        prefix = f"{self.logger_prefix} | " if self.logger_prefix else ""
        logger.warning(
            f"{prefix}Attempt {self._current_attempt}/{self.max_attempts} failed: {exception}"
        )
        logger.warning(
            f"{prefix}Retrying in {sleep_seconds:.1f}s..."
        )
        sleep_with_jitter(sleep_seconds)

    def _calculate_wait_time(self, exception: Exception) -> float:
        """
        Calculate wait time, respecting Retry-After header if present.

        For HTTP 429 responses with a valid Retry-After header, uses the
        maximum of the header value and the exponential backoff time.

        Handles both:
        - requests.HTTPError with 429 status (TokenBucket or no rate-limit scenarios)
        - ServerSideRateLimitError (Adaptive rate-limit scenario)

        Args:
            exception: The exception that occurred during the attempt.

        Returns:
            The wait time in seconds before the next retry attempt.
        """
        # Convert 1-indexed attempt to 0-indexed for exponential calculation
        # Attempt 1 → 2^0, Attempt 2 → 2^1, Attempt 3 → 2^2, etc.
        base_wait: float = self.initial_delay * (2 ** (self._current_attempt - 1))

        # Extract response from either HTTPError or ServerSideRateLimitError
        response: requests.Response | None = None

        if isinstance(exception, requests.HTTPError):
            # Direct HTTP 429 (TokenBucket or no rate-limit decorator)
            response = getattr(exception, "response", None)
        else:
            # Lazy import to avoid circular dependency
            from stkai._rate_limit import ServerSideRateLimitError

            if isinstance(exception, ServerSideRateLimitError):
                # Wrapped 429 from AdaptiveRateLimitedHttpClient
                response = exception.response

        # Check for Retry-After header on 429 responses
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


