"""Tests for HTTP client implementations."""

import threading
import time
import unittest
from unittest.mock import MagicMock

import requests

from stkai.rqc import AdaptiveRateLimitedHttpClient, RateLimitedHttpClient, RqcHttpClient


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


class MockHttpClientWith429(RqcHttpClient):
    """Mock HTTP client that returns 429 responses."""

    def __init__(self, fail_count: int = 1, retry_after: str | None = None):
        self.fail_count = fail_count
        self.retry_after = retry_after
        self.call_count = 0
        self.post_calls: list[tuple[str, dict | None, int]] = []

    def get_with_authorization(self, execution_id: str, timeout: int = 30) -> requests.Response:
        response = MagicMock(spec=requests.Response)
        response.status_code = 200
        return response

    def post_with_authorization(
        self, slug_name: str, data: dict | None = None, timeout: int = 20
    ) -> requests.Response:
        self.post_calls.append((slug_name, data, timeout))
        self.call_count += 1
        response = MagicMock(spec=requests.Response)

        if self.call_count <= self.fail_count:
            response.status_code = 429
            response.headers = {"Retry-After": self.retry_after} if self.retry_after else {}
        else:
            response.status_code = 200
            response.headers = {}

        return response


class TestAdaptiveRateLimitedHttpClientInit(unittest.TestCase):
    """Tests for AdaptiveRateLimitedHttpClient initialization."""

    def test_init_with_valid_params(self):
        """Should initialize correctly with valid parameters."""
        delegate = MockHttpClient()
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        self.assertEqual(client.delegate, delegate)
        self.assertEqual(client.max_requests, 100)
        self.assertEqual(client.time_window, 60.0)
        self.assertEqual(client.min_rate_floor, 0.1)
        self.assertEqual(client.max_retries_on_429, 3)
        self.assertEqual(client.penalty_factor, 0.2)
        self.assertEqual(client.recovery_factor, 0.01)

    def test_init_with_custom_params(self):
        """Should initialize correctly with custom parameters."""
        delegate = MockHttpClient()
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=50,
            time_window=30.0,
            min_rate_floor=0.2,
            max_retries_on_429=5,
            penalty_factor=0.3,
            recovery_factor=0.05,
        )

        self.assertEqual(client.min_rate_floor, 0.2)
        self.assertEqual(client.max_retries_on_429, 5)
        self.assertEqual(client.penalty_factor, 0.3)
        self.assertEqual(client.recovery_factor, 0.05)

    def test_init_fails_when_delegate_is_none(self):
        """Should fail when delegate is None."""
        with self.assertRaises(AssertionError) as ctx:
            AdaptiveRateLimitedHttpClient(
                delegate=None,  # type: ignore
                max_requests=10,
                time_window=60.0,
            )
        self.assertIn("Delegate", str(ctx.exception))

    def test_init_fails_when_min_rate_floor_is_zero(self):
        """Should fail when min_rate_floor is zero."""
        with self.assertRaises(AssertionError) as ctx:
            AdaptiveRateLimitedHttpClient(
                delegate=MockHttpClient(),
                max_requests=10,
                time_window=60.0,
                min_rate_floor=0,
            )
        self.assertIn("min_rate_floor", str(ctx.exception))

    def test_init_fails_when_min_rate_floor_greater_than_one(self):
        """Should fail when min_rate_floor is greater than 1."""
        with self.assertRaises(AssertionError) as ctx:
            AdaptiveRateLimitedHttpClient(
                delegate=MockHttpClient(),
                max_requests=10,
                time_window=60.0,
                min_rate_floor=1.5,
            )
        self.assertIn("min_rate_floor", str(ctx.exception))

    def test_init_fails_when_penalty_factor_is_zero(self):
        """Should fail when penalty_factor is zero."""
        with self.assertRaises(AssertionError) as ctx:
            AdaptiveRateLimitedHttpClient(
                delegate=MockHttpClient(),
                max_requests=10,
                time_window=60.0,
                penalty_factor=0,
            )
        self.assertIn("penalty_factor", str(ctx.exception))

    def test_init_fails_when_penalty_factor_is_one(self):
        """Should fail when penalty_factor is 1."""
        with self.assertRaises(AssertionError) as ctx:
            AdaptiveRateLimitedHttpClient(
                delegate=MockHttpClient(),
                max_requests=10,
                time_window=60.0,
                penalty_factor=1,
            )
        self.assertIn("penalty_factor", str(ctx.exception))


class TestAdaptiveRateLimitedHttpClientDelegation(unittest.TestCase):
    """Tests for AdaptiveRateLimitedHttpClient delegation behavior."""

    def setUp(self):
        self.delegate = MockHttpClient()
        self.client = AdaptiveRateLimitedHttpClient(
            delegate=self.delegate,
            max_requests=100,
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


class TestAdaptiveRateLimitedHttpClientAdaptation(unittest.TestCase):
    """Tests for AdaptiveRateLimitedHttpClient adaptive rate behavior."""

    def test_effective_max_decreases_after_429(self):
        """Should decrease effective_max after receiving 429."""
        delegate = MockHttpClientWith429(fail_count=1)
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            penalty_factor=0.2,
            max_retries_on_429=0,  # No retries to isolate the penalty effect
        )

        initial_max = client.effective_max
        client.post_with_authorization("slug")

        # After 429 (no retry), effective_max should be reduced by penalty_factor (20%)
        expected_max = initial_max * (1 - 0.2)
        self.assertAlmostEqual(client.effective_max, expected_max, places=1)

    def test_effective_max_increases_after_success(self):
        """Should increase effective_max after successful request."""
        delegate = MockHttpClient()
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            recovery_factor=0.01,
        )

        # Manually reduce effective_max to test recovery
        with client._lock:
            client._effective_max = 50.0

        client.post_with_authorization("slug")

        # After success, effective_max should increase by recovery_factor * max_requests
        expected_max = 50.0 + (100 * 0.01)
        self.assertAlmostEqual(client.effective_max, expected_max, places=1)

    def test_effective_max_never_exceeds_original(self):
        """Should never increase effective_max beyond original max_requests."""
        delegate = MockHttpClient()
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            recovery_factor=0.5,  # Large recovery factor
        )

        # Make several successful requests
        for _ in range(10):
            client.post_with_authorization("slug")

        # Should never exceed original max
        self.assertLessEqual(client.effective_max, 100.0)

    def test_effective_max_respects_floor(self):
        """Should never decrease effective_max below floor."""
        delegate = MockHttpClientWith429(fail_count=100)  # Always return 429
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            min_rate_floor=0.1,
            penalty_factor=0.5,  # Large penalty
            max_retries_on_429=0,  # No retries, just adapt
        )

        min_floor = 100 * 0.1  # 10

        # Make many requests that all get 429
        for _ in range(20):
            client.post_with_authorization("slug")

        # Should never go below floor
        self.assertGreaterEqual(client.effective_max, min_floor)


class TestAdaptiveRateLimitedHttpClient429Handling(unittest.TestCase):
    """Tests for AdaptiveRateLimitedHttpClient 429 retry behavior."""

    def test_retries_on_429_and_succeeds(self):
        """Should retry on 429 and eventually succeed."""
        delegate = MockHttpClientWith429(fail_count=2)
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            max_retries_on_429=3,
        )

        response = client.post_with_authorization("slug")

        # Should have made 3 calls: 2 failures + 1 success
        self.assertEqual(delegate.call_count, 3)
        self.assertEqual(response.status_code, 200)

    def test_returns_429_when_max_retries_exceeded(self):
        """Should return 429 response when max retries exceeded."""
        delegate = MockHttpClientWith429(fail_count=10)  # More failures than retries
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            max_retries_on_429=2,
        )

        response = client.post_with_authorization("slug")

        # Should have made 3 calls (initial + 2 retries)
        self.assertEqual(delegate.call_count, 3)
        self.assertEqual(response.status_code, 429)

    def test_respects_retry_after_header(self):
        """Should use Retry-After header for wait time."""
        delegate = MockHttpClientWith429(fail_count=1, retry_after="0.1")
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            max_retries_on_429=1,
        )

        start = time.time()
        client.post_with_authorization("slug")
        elapsed = time.time() - start

        # Should have waited at least 0.1 seconds (from Retry-After)
        self.assertGreaterEqual(elapsed, 0.1)

    def test_no_retries_when_max_retries_is_zero(self):
        """Should not retry when max_retries_on_429 is 0."""
        delegate = MockHttpClientWith429(fail_count=1)
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            max_retries_on_429=0,
        )

        response = client.post_with_authorization("slug")

        # Should have made only 1 call
        self.assertEqual(delegate.call_count, 1)
        self.assertEqual(response.status_code, 429)


class TestAdaptiveRateLimitedHttpClientThreadSafety(unittest.TestCase):
    """Tests for AdaptiveRateLimitedHttpClient thread safety."""

    def test_thread_safe_concurrent_requests(self):
        """Should handle concurrent requests safely."""
        delegate = MockHttpClient()
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
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

        threads = [threading.Thread(target=make_request, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 10)
        self.assertEqual(len(delegate.post_calls), 10)

    def test_thread_safe_adaptation(self):
        """Should adapt effective_max safely across threads."""
        # Create a client that will receive some 429s
        call_count = 0
        lock = threading.Lock()

        class ThreadSafeMock429(RqcHttpClient):
            def get_with_authorization(self, execution_id: str, timeout: int = 30) -> requests.Response:
                response = MagicMock(spec=requests.Response)
                response.status_code = 200
                return response

            def post_with_authorization(
                self, slug_name: str, data: dict | None = None, timeout: int = 20
            ) -> requests.Response:
                nonlocal call_count
                with lock:
                    call_count += 1
                    current_count = call_count

                response = MagicMock(spec=requests.Response)
                # First 5 calls return 429, rest return 200
                if current_count <= 5:
                    response.status_code = 429
                    response.headers = {"Retry-After": "0.01"}
                else:
                    response.status_code = 200
                    response.headers = {}
                return response

        delegate = ThreadSafeMock429()
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=1.0,
            max_retries_on_429=0,  # No retries, just track adaptation
        )

        initial_max = client.effective_max
        errors = []

        def make_request():
            try:
                client.post_with_authorization("slug")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=make_request) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(len(errors), 0)
        # effective_max should have been reduced (due to 429s) but not below floor
        self.assertLess(client.effective_max, initial_max)
        self.assertGreaterEqual(client.effective_max, 100 * 0.1)


if __name__ == "__main__":
    unittest.main()
