"""
HTTP client implementations for Remote Quick Command.

This module contains concrete implementations of RqcHttpClient
for making authorized HTTP requests to the StackSpot AI API.

The default implementation (StkCLIRqcHttpClient) uses the StackSpot CLI
for authentication, which requires the CLI to be installed and configured.

Available implementations:
    - StkCLIRqcHttpClient: Uses StackSpot CLI for authentication.
    - RateLimitedHttpClient: Wrapper that adds rate limiting to any client.
"""

import random
import threading
import time
from typing import Any, override

import requests

from stkai.rqc._remote_quick_command import RqcHttpClient


class StkCLIRqcHttpClient(RqcHttpClient):
    """
    HTTP client implementation using StackSpot CLI for authorization.

    This client delegates authentication to the StackSpot CLI (oscli),
    which must be installed and logged in for this client to work.

    The CLI handles token management, refresh, and injection of
    authorization headers into HTTP requests.

    Note:
        Requires the `oscli` package to be installed and configured.
        Install via: pip install oscli
        Login via: stk login

    See Also:
        RqcHttpClient: Abstract base class defining the interface.
    """

    @override
    def get_with_authorization(self, execution_id: str, timeout: int = 30) -> requests.Response:
        """
        Retrieves the execution status from the StackSpot AI API.

        Args:
            execution_id: The execution ID to query.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response containing execution status and result.

        Raises:
            AssertionError: If execution_id is empty or timeout is invalid.
            requests.RequestException: If the HTTP request fails.
        """
        assert execution_id, "Execution ID can not be empty."
        assert timeout is not None, "Timeout can not be None."
        assert timeout > 0, "Timeout must be greater than 0."

        from oscli import __codebuddy_base_url__
        from oscli.core.http import get_with_authorization

        codebuddy_base_url = __codebuddy_base_url__
        nocache_param = random.randint(0, 1000000)
        url = f"{codebuddy_base_url}/v1/quick-commands/callback/{execution_id}?nocache={nocache_param}"
        headers = {
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }

        response: requests.Response = get_with_authorization(url=url, timeout=timeout, headers=headers)
        return response

    @override
    def post_with_authorization(self, slug_name: str, data: dict[str, Any] | None = None, timeout: int = 20) -> requests.Response:
        """
        Creates a new Quick Command execution on the StackSpot AI API.

        Args:
            slug_name: The Quick Command slug name to execute.
            data: The request payload containing input data.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response containing the execution ID.

        Raises:
            AssertionError: If slug_name is empty or timeout is invalid.
            requests.RequestException: If the HTTP request fails.
        """
        assert slug_name, "RQC slug-name can not be empty."
        assert timeout is not None, "Timeout can not be None."
        assert timeout > 0, "Timeout must be greater than 0."

        from oscli import __codebuddy_base_url__
        from oscli.core.http import post_with_authorization

        codebuddy_base_url = __codebuddy_base_url__
        url = f"{codebuddy_base_url}/v1/quick-commands/create-execution/{slug_name}"

        response: requests.Response = post_with_authorization(url=url, body=data, timeout=timeout)
        return response


class RateLimitedHttpClient(RqcHttpClient):
    """
    HTTP client wrapper that applies rate limiting to requests.

    Uses the Token Bucket algorithm to limit the rate of requests.
    Only POST requests (create-execution) are rate-limited; GET requests
    (polling) pass through without limiting.

    This wrapper is thread-safe and can be used with execute_many().

    Example:
        >>> # Limit to 10 requests per minute
        >>> client = RateLimitedHttpClient(
        ...     delegate=StkCLIRqcHttpClient(),
        ...     max_requests=10,
        ...     time_window=60.0,
        ... )
        >>> rqc = RemoteQuickCommand(slug_name="my-rqc", http_client=client)

    Args:
        delegate: The underlying HTTP client to delegate requests to.
        max_requests: Maximum number of requests allowed in the time window.
        time_window: Time window in seconds for the rate limit.
    """

    def __init__(
        self,
        delegate: RqcHttpClient,
        max_requests: int,
        time_window: float,
    ):
        """
        Initialize the rate-limited HTTP client.

        Args:
            delegate: The underlying HTTP client to delegate requests to.
            max_requests: Maximum number of requests allowed in the time window.
            time_window: Time window in seconds for the rate limit.

        Raises:
            AssertionError: If any parameter is invalid.
        """
        assert delegate, "Delegate HTTP client is required."
        assert max_requests is not None, "max_requests can not be None."
        assert max_requests > 0, "max_requests must be greater than 0."
        assert time_window is not None, "time_window can not be None."
        assert time_window > 0, "time_window must be greater than 0."

        self.delegate = delegate
        self.max_requests = max_requests
        self.time_window = time_window

        # Token bucket state
        self._tokens = float(max_requests)
        self._last_refill = time.time()
        self._lock = threading.Lock()

    def _acquire_token(self) -> None:
        """
        Acquires a token, blocking if necessary until one is available.

        Uses Token Bucket algorithm:
        - Refills tokens based on elapsed time
        - Waits if no tokens are available
        """
        while True:
            with self._lock:
                now = time.time()
                # Refill tokens based on elapsed time
                elapsed = now - self._last_refill
                refill_rate = self.max_requests / self.time_window
                self._tokens = min(
                    float(self.max_requests),
                    self._tokens + elapsed * refill_rate
                )
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                # Calculate wait time for next token
                wait_time = (1.0 - self._tokens) / refill_rate

            # Sleep outside the lock to allow other threads to proceed
            time.sleep(wait_time)

    @override
    def get_with_authorization(self, execution_id: str, timeout: int = 30) -> requests.Response:
        """
        Delegates to underlying client without rate limiting.

        GET requests (polling) are not rate-limited as they typically
        don't count against API rate limits.

        Args:
            execution_id: The execution ID to query.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response from the StackSpot AI API.
        """
        return self.delegate.get_with_authorization(execution_id, timeout)

    @override
    def post_with_authorization(
        self, slug_name: str, data: dict[str, Any] | None = None, timeout: int = 20
    ) -> requests.Response:
        """
        Acquires a rate limit token, then delegates to underlying client.

        This method blocks until a token is available if the rate limit
        has been reached.

        Args:
            slug_name: The Quick Command slug name to execute.
            data: The request payload to send.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response from the StackSpot AI API.
        """
        self._acquire_token()
        return self.delegate.post_with_authorization(slug_name, data, timeout)
