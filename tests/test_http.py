"""Tests for HTTP client implementations, focusing on rate limiting."""

import threading
import time
from unittest.mock import MagicMock

import pytest
import requests

from stkai import (
    AdaptiveRateLimitedHttpClient,
    HttpClient,
    RateLimitedHttpClient,
    RateLimitTimeoutError,
)


# =============================================================================
# RateLimitTimeoutError Tests
# =============================================================================


class TestRateLimitTimeoutError:
    """Tests for RateLimitTimeoutError exception."""

    def test_error_message_contains_waited_and_max_wait_time(self):
        error = RateLimitTimeoutError(waited=45.5, max_wait_time=60.0)

        assert "45.50s" in str(error)
        assert "60.00s" in str(error)
        assert "Rate limit timeout" in str(error)

    def test_error_exposes_waited_attribute(self):
        error = RateLimitTimeoutError(waited=30.0, max_wait_time=60.0)

        assert error.waited == 30.0

    def test_error_exposes_max_wait_time_attribute(self):
        error = RateLimitTimeoutError(waited=30.0, max_wait_time=60.0)

        assert error.max_wait_time == 60.0

    def test_error_is_exception_subclass(self):
        error = RateLimitTimeoutError(waited=10.0, max_wait_time=20.0)

        assert isinstance(error, Exception)


# =============================================================================
# RateLimitedHttpClient Tests
# =============================================================================


class MockHttpClient(HttpClient):
    """Mock HTTP client for testing."""

    def __init__(self):
        self.get_calls = []
        self.post_calls = []
        self.response = MagicMock(spec=requests.Response)
        self.response.status_code = 200

    def get(self, url, headers=None, timeout=30):
        self.get_calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self.response

    def post(self, url, data=None, headers=None, timeout=30):
        self.post_calls.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        return self.response


class TestRateLimitedHttpClientInit:
    """Tests for RateLimitedHttpClient initialization."""

    def test_init_with_default_max_wait_time(self):
        delegate = MockHttpClient()

        client = RateLimitedHttpClient(
            delegate=delegate,
            max_requests=10,
            time_window=60.0,
        )

        assert client.max_wait_time == 60.0

    def test_init_with_custom_max_wait_time(self):
        delegate = MockHttpClient()

        client = RateLimitedHttpClient(
            delegate=delegate,
            max_requests=10,
            time_window=60.0,
            max_wait_time=120.0,
        )

        assert client.max_wait_time == 120.0

    def test_init_with_none_max_wait_time_allows_infinite_wait(self):
        delegate = MockHttpClient()

        client = RateLimitedHttpClient(
            delegate=delegate,
            max_requests=10,
            time_window=60.0,
            max_wait_time=None,
        )

        assert client.max_wait_time is None

    def test_init_fails_when_max_wait_time_is_zero(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match="max_wait_time must be > 0 or None"):
            RateLimitedHttpClient(
                delegate=delegate,
                max_requests=10,
                time_window=60.0,
                max_wait_time=0,
            )

    def test_init_fails_when_max_wait_time_is_negative(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match="max_wait_time must be > 0 or None"):
            RateLimitedHttpClient(
                delegate=delegate,
                max_requests=10,
                time_window=60.0,
                max_wait_time=-1.0,
            )


class TestRateLimitedHttpClientTimeout:
    """Tests for RateLimitedHttpClient timeout behavior."""

    def test_raises_timeout_error_when_max_wait_time_exceeded(self):
        delegate = MockHttpClient()
        # Very restrictive rate: 1 request per 100 seconds
        client = RateLimitedHttpClient(
            delegate=delegate,
            max_requests=1,
            time_window=100.0,
            max_wait_time=0.1,  # Very short timeout
        )

        # First request consumes the only token
        client.post("http://example.com", data={})

        # Second request should timeout waiting for token
        with pytest.raises(RateLimitTimeoutError) as exc_info:
            client.post("http://example.com", data={})

        assert exc_info.value.max_wait_time == 0.1
        assert exc_info.value.waited >= 0

    def test_does_not_timeout_when_tokens_available(self):
        delegate = MockHttpClient()
        client = RateLimitedHttpClient(
            delegate=delegate,
            max_requests=10,
            time_window=60.0,
            max_wait_time=1.0,
        )

        # Should not timeout - plenty of tokens
        response = client.post("http://example.com", data={})

        assert response.status_code == 200

    def test_get_requests_bypass_rate_limiting(self):
        delegate = MockHttpClient()
        client = RateLimitedHttpClient(
            delegate=delegate,
            max_requests=1,
            time_window=100.0,
            max_wait_time=0.1,
        )

        # Exhaust the single token
        client.post("http://example.com", data={})

        # GET should still work (no rate limiting for GET)
        response = client.get("http://example.com")

        assert response.status_code == 200


class TestRateLimitedHttpClientThreadIsolation:
    """Tests for thread isolation in RateLimitedHttpClient."""

    def test_each_thread_has_independent_timeout(self):
        delegate = MockHttpClient()
        # Very restrictive: 1 request per 10 seconds
        client = RateLimitedHttpClient(
            delegate=delegate,
            max_requests=1,
            time_window=10.0,
            max_wait_time=0.2,
        )

        errors = []
        success_count = [0]
        lock = threading.Lock()

        def make_request():
            try:
                client.post("http://example.com", data={})
                with lock:
                    success_count[0] += 1
            except RateLimitTimeoutError as e:
                with lock:
                    errors.append(e)

        # Launch 3 threads simultaneously
        threads = [threading.Thread(target=make_request) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # One should succeed (got the token), others should timeout
        assert success_count[0] == 1
        assert len(errors) == 2

        # Each error should have its own waited time
        for error in errors:
            assert error.max_wait_time == 0.2


# =============================================================================
# AdaptiveRateLimitedHttpClient Tests
# =============================================================================


class TestAdaptiveRateLimitedHttpClientInit:
    """Tests for AdaptiveRateLimitedHttpClient initialization."""

    def test_init_with_default_max_wait_time(self):
        delegate = MockHttpClient()

        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        assert client.max_wait_time == 60.0

    def test_init_with_custom_max_wait_time(self):
        delegate = MockHttpClient()

        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            max_wait_time=120.0,
        )

        assert client.max_wait_time == 120.0

    def test_init_with_none_max_wait_time_allows_infinite_wait(self):
        delegate = MockHttpClient()

        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            max_wait_time=None,
        )

        assert client.max_wait_time is None

    def test_init_fails_when_max_wait_time_is_zero(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match="max_wait_time must be > 0 or None"):
            AdaptiveRateLimitedHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=60.0,
                max_wait_time=0,
            )

    def test_init_fails_when_max_wait_time_is_negative(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match="max_wait_time must be > 0 or None"):
            AdaptiveRateLimitedHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=60.0,
                max_wait_time=-1.0,
            )


class TestAdaptiveRateLimitedHttpClientTimeout:
    """Tests for AdaptiveRateLimitedHttpClient timeout behavior."""

    def test_raises_timeout_error_when_max_wait_time_exceeded(self):
        delegate = MockHttpClient()
        # Very restrictive rate: 1 request per 100 seconds
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=1,
            time_window=100.0,
            max_wait_time=0.1,
        )

        # First request consumes the only token
        client.post("http://example.com", data={})

        # Second request should timeout
        with pytest.raises(RateLimitTimeoutError) as exc_info:
            client.post("http://example.com", data={})

        assert exc_info.value.max_wait_time == 0.1

    def test_does_not_timeout_when_tokens_available(self):
        delegate = MockHttpClient()
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            max_wait_time=1.0,
        )

        response = client.post("http://example.com", data={})

        assert response.status_code == 200

    def test_get_requests_bypass_rate_limiting(self):
        delegate = MockHttpClient()
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=1,
            time_window=100.0,
            max_wait_time=0.1,
        )

        # Exhaust the single token
        client.post("http://example.com", data={})

        # GET should still work
        response = client.get("http://example.com")

        assert response.status_code == 200


class TestAdaptiveRateLimitedHttpClient429Handling:
    """Tests for 429 handling in AdaptiveRateLimitedHttpClient."""

    def test_retries_on_429_and_adapts_rate(self):
        delegate = MockHttpClient()
        delegate.response.status_code = 429
        delegate.response.headers = {}

        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            max_retries_on_429=2,
            penalty_factor=0.5,
            max_wait_time=None,  # Disable timeout for this test
        )

        initial_effective_max = client.effective_max

        # This will retry and reduce effective_max
        client.post("http://example.com", data={})

        # Effective max should be reduced after 429s
        assert client.effective_max < initial_effective_max

    def test_returns_429_after_max_retries_exhausted(self):
        delegate = MockHttpClient()
        delegate.response.status_code = 429
        delegate.response.headers = {}

        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            max_retries_on_429=1,
            max_wait_time=None,
        )

        response = client.post("http://example.com", data={})

        assert response.status_code == 429
        # Should have made 2 attempts (initial + 1 retry)
        assert len(delegate.post_calls) == 2
