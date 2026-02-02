"""
Retry logic - high fidelity port from stkai._retry.

Implements exponential backoff with jitter and Retry-After support.
"""

from dataclasses import dataclass

from simulations.src.config import RetryConfig
from simulations.src.jitter import sleep_with_jitter


@dataclass
class RetryDecision:
    """Result of a retry decision."""

    should_retry: bool
    wait_time: float = 0.0
    attempt_number: int = 0


class RetryHandler:
    """
    Retry handler for simulation.

    High-fidelity port of stkai._retry.Retrying logic.

    Key behaviors:
    - Exponential backoff: delay = initial * 2^(attempt-1)
    - Jitter: ±10% on delays
    - Retry-After: respected (max 60s)
    - Max retries: 3 (4 total attempts)
    """

    def __init__(self, config: RetryConfig):
        """
        Initialize retry handler.

        Args:
            config: Retry configuration.
        """
        self.max_retries = config.max_retries
        self.initial_delay = config.initial_delay
        self.jitter_factor = config.jitter_factor
        self.max_retry_after = config.max_retry_after

        self._current_attempt = 0

    def start_request(self) -> int:
        """Start a new request, resetting attempt counter. Returns attempt number."""
        self._current_attempt = 1
        return self._current_attempt

    def should_retry(
        self,
        status_code: int,
        retry_after: float | None = None,
    ) -> RetryDecision:
        """
        Determine if request should be retried.

        Args:
            status_code: HTTP response status code.
            retry_after: Optional Retry-After header value.

        Returns:
            RetryDecision indicating whether to retry and wait time.
        """
        # Check if status is retryable
        retryable_codes = {408, 429, 500, 502, 503, 504}
        if status_code not in retryable_codes:
            return RetryDecision(should_retry=False, attempt_number=self._current_attempt)

        # Check if we've exceeded max retries
        if self._current_attempt > self.max_retries:
            return RetryDecision(should_retry=False, attempt_number=self._current_attempt)

        # Calculate wait time
        wait_time = self._calculate_wait_time(retry_after)

        # Increment attempt for next call
        self._current_attempt += 1

        return RetryDecision(
            should_retry=True,
            wait_time=wait_time,
            attempt_number=self._current_attempt - 1,
        )

    def _calculate_wait_time(self, retry_after: float | None) -> float:
        """
        Calculate wait time with exponential backoff.

        Mirrors Retrying._calculate_wait_time().

        Args:
            retry_after: Optional Retry-After header value.

        Returns:
            Wait time in seconds.
        """
        # Exponential backoff: delay = initial * 2^(attempt-1)
        # Attempt 1 → 2^0, Attempt 2 → 2^1, etc.
        base_wait = self.initial_delay * (2 ** (self._current_attempt - 1))

        # Apply jitter
        base_wait = sleep_with_jitter(base_wait, jitter_factor=self.jitter_factor)

        # Respect Retry-After header if present (max 60s)
        if retry_after is not None and retry_after <= self.max_retry_after:
            return max(retry_after, base_wait)

        return base_wait

    @property
    def max_attempts(self) -> int:
        """Total attempts (1 original + max_retries)."""
        return self.max_retries + 1

    @property
    def enabled(self) -> bool:
        """Whether retry is enabled (max_retries > 0)."""
        return self.max_retries > 0
