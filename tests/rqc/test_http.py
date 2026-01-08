"""Tests for HTTP client implementations."""

import threading
import time
import unittest
from unittest.mock import MagicMock

import requests

from stkai.rqc import RateLimitedHttpClient, RqcHttpClient


class MockHttpClient(RqcHttpClient):
    """Mock HTTP client for testing."""

    def __init__(self):
        self.get_calls: list[tuple[str, int]] = []
        self.post_calls: list[tuple[str, dict | None, int]] = []

    def get_with_authorization(self, execution_id: str, timeout: int = 30) -> requests.Response:
        self.get_calls.append((execution_id, timeout))
        response = MagicMock(spec=requests.Response)
        response.status_code = 200
        return response

    def post_with_authorization(
        self, slug_name: str, data: dict | None = None, timeout: int = 20
    ) -> requests.Response:
        self.post_calls.append((slug_name, data, timeout))
        response = MagicMock(spec=requests.Response)
        response.status_code = 200
        return response


class TestRateLimitedHttpClientInit(unittest.TestCase):
    """Tests for RateLimitedHttpClient initialization."""

    def test_init_with_valid_params(self):
        """Should initialize correctly with valid parameters."""
        delegate = MockHttpClient()
        client = RateLimitedHttpClient(
            delegate=delegate,
            max_requests=10,
            time_window=60.0,
        )

        self.assertEqual(client.delegate, delegate)
        self.assertEqual(client.max_requests, 10)
        self.assertEqual(client.time_window, 60.0)

    def test_init_fails_when_delegate_is_none(self):
        """Should fail when delegate is None."""
        with self.assertRaises(AssertionError) as ctx:
            RateLimitedHttpClient(
                delegate=None,  # type: ignore
                max_requests=10,
                time_window=60.0,
            )
        self.assertIn("Delegate", str(ctx.exception))

    def test_init_fails_when_max_requests_is_zero(self):
        """Should fail when max_requests is zero."""
        with self.assertRaises(AssertionError) as ctx:
            RateLimitedHttpClient(
                delegate=MockHttpClient(),
                max_requests=0,
                time_window=60.0,
            )
        self.assertIn("max_requests", str(ctx.exception))

    def test_init_fails_when_max_requests_is_negative(self):
        """Should fail when max_requests is negative."""
        with self.assertRaises(AssertionError) as ctx:
            RateLimitedHttpClient(
                delegate=MockHttpClient(),
                max_requests=-1,
                time_window=60.0,
            )
        self.assertIn("max_requests", str(ctx.exception))

    def test_init_fails_when_time_window_is_zero(self):
        """Should fail when time_window is zero."""
        with self.assertRaises(AssertionError) as ctx:
            RateLimitedHttpClient(
                delegate=MockHttpClient(),
                max_requests=10,
                time_window=0.0,
            )
        self.assertIn("time_window", str(ctx.exception))

    def test_init_fails_when_time_window_is_negative(self):
        """Should fail when time_window is negative."""
        with self.assertRaises(AssertionError) as ctx:
            RateLimitedHttpClient(
                delegate=MockHttpClient(),
                max_requests=10,
                time_window=-1.0,
            )
        self.assertIn("time_window", str(ctx.exception))


class TestRateLimitedHttpClientDelegation(unittest.TestCase):
    """Tests for RateLimitedHttpClient delegation behavior."""

    def setUp(self):
        self.delegate = MockHttpClient()
        self.client = RateLimitedHttpClient(
            delegate=self.delegate,
            max_requests=100,  # High limit to avoid rate limiting in these tests
            time_window=1.0,
        )

    def test_get_with_authorization_delegates_to_underlying_client(self):
        """GET requests should be delegated without rate limiting."""
        self.client.get_with_authorization("exec-123", timeout=15)

        self.assertEqual(len(self.delegate.get_calls), 1)
        self.assertEqual(self.delegate.get_calls[0], ("exec-123", 15))

    def test_post_with_authorization_delegates_to_underlying_client(self):
        """POST requests should be delegated after acquiring token."""
        data = {"input_data": {"prompt": "test"}}
        self.client.post_with_authorization("my-slug", data=data, timeout=25)

        self.assertEqual(len(self.delegate.post_calls), 1)
        self.assertEqual(self.delegate.post_calls[0], ("my-slug", data, 25))

    def test_multiple_get_requests_not_rate_limited(self):
        """Multiple GET requests should pass through without rate limiting."""
        for i in range(10):
            self.client.get_with_authorization(f"exec-{i}")

        self.assertEqual(len(self.delegate.get_calls), 10)


class TestRateLimitedHttpClientRateLimiting(unittest.TestCase):
    """Tests for RateLimitedHttpClient rate limiting behavior."""

    def test_allows_requests_up_to_max_requests(self):
        """Should allow max_requests without blocking."""
        delegate = MockHttpClient()
        client = RateLimitedHttpClient(
            delegate=delegate,
            max_requests=5,
            time_window=10.0,
        )

        start = time.time()
        for _ in range(5):
            client.post_with_authorization("slug")
        elapsed = time.time() - start

        self.assertEqual(len(delegate.post_calls), 5)
        # Should complete almost instantly (< 0.1s)
        self.assertLess(elapsed, 0.1)

    def test_blocks_when_rate_limit_exceeded(self):
        """Should block when rate limit is exceeded."""
        delegate = MockHttpClient()
        client = RateLimitedHttpClient(
            delegate=delegate,
            max_requests=2,
            time_window=1.0,  # 2 requests per second
        )

        start = time.time()
        # First 2 requests should be immediate
        client.post_with_authorization("slug")
        client.post_with_authorization("slug")
        # Third request should block for ~0.5 seconds (time for 1 token to refill)
        client.post_with_authorization("slug")
        elapsed = time.time() - start

        self.assertEqual(len(delegate.post_calls), 3)
        # Should have waited for at least 0.4s (allowing some tolerance)
        self.assertGreaterEqual(elapsed, 0.4)

    def test_tokens_refill_over_time(self):
        """Should refill tokens over time."""
        delegate = MockHttpClient()
        client = RateLimitedHttpClient(
            delegate=delegate,
            max_requests=2,
            time_window=0.5,  # 2 requests per 0.5 seconds = 4 per second
        )

        # Use all tokens
        client.post_with_authorization("slug")
        client.post_with_authorization("slug")

        # Wait for tokens to refill
        time.sleep(0.6)

        # Should be able to make 2 more requests immediately
        start = time.time()
        client.post_with_authorization("slug")
        client.post_with_authorization("slug")
        elapsed = time.time() - start

        self.assertEqual(len(delegate.post_calls), 4)
        self.assertLess(elapsed, 0.1)


class TestRateLimitedHttpClientThreadSafety(unittest.TestCase):
    """Tests for RateLimitedHttpClient thread safety."""

    def test_thread_safe_concurrent_requests(self):
        """Should handle concurrent requests safely."""
        delegate = MockHttpClient()
        client = RateLimitedHttpClient(
            delegate=delegate,
            max_requests=5,
            time_window=1.0,
        )

        results = []
        errors = []

        def make_request(idx: int):
            try:
                client.post_with_authorization(f"slug-{idx}")
                results.append(idx)
            except Exception as e:
                errors.append(e)

        # Launch 10 threads, each making 1 request
        threads = [threading.Thread(target=make_request, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # All requests should complete without errors
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 10)
        self.assertEqual(len(delegate.post_calls), 10)

    def test_rate_limiting_works_across_threads(self):
        """Rate limiting should work correctly across multiple threads."""
        delegate = MockHttpClient()
        client = RateLimitedHttpClient(
            delegate=delegate,
            max_requests=3,
            time_window=1.0,  # 3 requests per second
        )

        timestamps: list[float] = []
        lock = threading.Lock()

        def make_request():
            client.post_with_authorization("slug")
            with lock:
                timestamps.append(time.time())

        # Launch 6 threads simultaneously
        start = time.time()
        threads = [threading.Thread(target=make_request) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
        total_time = time.time() - start

        self.assertEqual(len(timestamps), 6)
        # First 3 should be immediate, next 3 should wait
        # Total time should be at least 0.9 seconds (3 tokens need to refill)
        self.assertGreaterEqual(total_time, 0.9)


if __name__ == "__main__":
    unittest.main()
