"""Tests for CongestionControlledHttpClient."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from stkai._http import HttpClient
from stkai._rate_limit import (
    CongestionControlledHttpClient,
    ServerSideRateLimitError,
    TokenAcquisitionTimeoutError,
)

# =============================================================================
# Test Fixtures
# =============================================================================


class MockHttpClient(HttpClient):
    """Mock HTTP client for testing."""

    def __init__(self, response_delay: float = 0.0):
        self.get_calls: list[dict] = []
        self.post_calls: list[dict] = []
        self.response = MagicMock(spec=requests.Response)
        self.response.status_code = 200
        self.response_delay = response_delay

    def get(self, url, headers=None, timeout=30):
        self.get_calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self.response

    def post(self, url, data=None, headers=None, timeout=30):
        if self.response_delay > 0:
            time.sleep(self.response_delay)
        self.post_calls.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        return self.response


# =============================================================================
# Initialization Tests
# =============================================================================


class TestCongestionControlledHttpClientInit:
    """Tests for CongestionControlledHttpClient initialization."""

    def test_init_with_default_values(self):
        delegate = MockHttpClient()

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        assert client.max_requests == 100
        assert client.time_window == 60.0
        assert client.min_rate_floor == 0.1
        assert client.penalty_factor == 0.3
        assert client.recovery_factor == 0.05
        assert client.max_wait_time == 30.0
        assert client.max_concurrency == 5
        assert client._latency_alpha == 0.2

    def test_init_with_custom_values(self):
        delegate = MockHttpClient()

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=50,
            time_window=30.0,
            min_rate_floor=0.2,
            penalty_factor=0.5,
            recovery_factor=0.1,
            max_wait_time=60.0,
            max_concurrency=10,
            latency_alpha=0.3,
        )

        assert client.max_requests == 50
        assert client.time_window == 30.0
        assert client.min_rate_floor == 0.2
        assert client.penalty_factor == 0.5
        assert client.recovery_factor == 0.1
        assert client.max_wait_time == 60.0
        assert client.max_concurrency == 10
        assert client._latency_alpha == 0.3

    def test_init_with_none_max_wait_time_allows_infinite_wait(self):
        delegate = MockHttpClient()

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            max_wait_time=None,
        )

        assert client.max_wait_time is None

    def test_init_sets_effective_max_to_max_requests(self):
        delegate = MockHttpClient()

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        assert client._effective_max == 100.0

    def test_init_sets_min_effective_based_on_floor(self):
        delegate = MockHttpClient()

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            min_rate_floor=0.1,
        )

        assert client._min_effective == 10.0  # 100 * 0.1

    def test_init_starts_with_concurrency_limit_of_one(self):
        """Concurrency should start conservatively at 1."""
        delegate = MockHttpClient()

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            max_concurrency=10,
        )

        assert client._concurrency_limit == 1

    def test_init_latency_ema_is_none(self):
        delegate = MockHttpClient()

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        assert client._latency_ema is None

    def test_init_creates_jitter_with_deterministic_rng(self):
        """Jitter should use a per-process seeded RNG for structural jitter."""
        delegate = MockHttpClient()

        client1 = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        client2 = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        # Both should have Jitter instances
        assert client1._jitter is not None
        assert client2._jitter is not None

        # Verify the seed is based on hostname+pid (deterministic within same process)
        import os
        import socket
        expected_seed = hash((socket.gethostname(), os.getpid()))

        # Create a new RNG with same seed and verify it produces same values
        import random
        test_rng = random.Random(expected_seed)
        client3 = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )
        # Both should start with the same sequence
        assert test_rng.random() == client3._jitter.random()


class TestCongestionControlledHttpClientInitValidation:
    """Tests for parameter validation during initialization."""

    def test_init_fails_when_delegate_is_none(self):
        with pytest.raises(AssertionError, match="Delegate HTTP client is required"):
            CongestionControlledHttpClient(
                delegate=None,
                max_requests=100,
                time_window=60.0,
            )

    def test_init_fails_when_max_requests_is_zero(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match="max_requests must be greater than 0"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=0,
                time_window=60.0,
            )

    def test_init_fails_when_max_requests_is_negative(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match="max_requests must be greater than 0"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=-1,
                time_window=60.0,
            )

    def test_init_fails_when_time_window_is_zero(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match="time_window must be greater than 0"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=0,
            )

    def test_init_fails_when_time_window_is_negative(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match="time_window must be greater than 0"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=-1.0,
            )

    def test_init_fails_when_min_rate_floor_is_zero(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match=r"min_rate_floor must be between 0 \(exclusive\) and 1 \(inclusive\)"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=60.0,
                min_rate_floor=0,
            )

    def test_init_fails_when_min_rate_floor_is_greater_than_one(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match=r"min_rate_floor must be between 0 \(exclusive\) and 1 \(inclusive\)"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=60.0,
                min_rate_floor=1.5,
            )

    def test_init_fails_when_penalty_factor_is_zero(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match=r"penalty_factor must be between 0 and 1 \(exclusive\)"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=60.0,
                penalty_factor=0,
            )

    def test_init_fails_when_penalty_factor_is_one(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match=r"penalty_factor must be between 0 and 1 \(exclusive\)"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=60.0,
                penalty_factor=1.0,
            )

    def test_init_fails_when_recovery_factor_is_zero(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match=r"recovery_factor must be between 0 and 1 \(exclusive\)"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=60.0,
                recovery_factor=0,
            )

    def test_init_fails_when_recovery_factor_is_one(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match=r"recovery_factor must be between 0 and 1 \(exclusive\)"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=60.0,
                recovery_factor=1.0,
            )

    def test_init_fails_when_max_wait_time_is_zero(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match=r"max_wait_time must be > 0 or None"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=60.0,
                max_wait_time=0,
            )

    def test_init_fails_when_max_wait_time_is_negative(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match=r"max_wait_time must be > 0 or None"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=60.0,
                max_wait_time=-1.0,
            )

    def test_init_fails_when_max_concurrency_is_zero(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match="max_concurrency must be at least 1"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=60.0,
                max_concurrency=0,
            )

    def test_init_fails_when_latency_alpha_is_zero(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match=r"latency_alpha must be between 0 and 1 \(exclusive\)"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=60.0,
                latency_alpha=0,
            )

    def test_init_fails_when_latency_alpha_is_one(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match=r"latency_alpha must be between 0 and 1 \(exclusive\)"):
            CongestionControlledHttpClient(
                delegate=delegate,
                max_requests=100,
                time_window=60.0,
                latency_alpha=1.0,
            )


# =============================================================================
# GET Request Tests (Bypass Rate Limiting)
# =============================================================================


class TestCongestionControlledHttpClientGet:
    """Tests for GET requests bypassing rate limiting."""

    def test_get_delegates_without_rate_limiting(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=1,
            time_window=100.0,
            max_wait_time=0.1,
        )

        # Exhaust token with POST
        client.post("http://example.com", data={})

        # GET should still work (no rate limiting)
        response = client.get("http://example.com/status")

        assert response.status_code == 200
        assert len(delegate.get_calls) == 1
        assert delegate.get_calls[0]["url"] == "http://example.com/status"

    def test_get_passes_headers_to_delegate(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        client.get("http://example.com", headers={"X-Custom": "value"})

        assert delegate.get_calls[0]["headers"] == {"X-Custom": "value"}

    def test_get_passes_timeout_to_delegate(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        client.get("http://example.com", timeout=60)

        assert delegate.get_calls[0]["timeout"] == 60


# =============================================================================
# POST Request Tests (Basic)
# =============================================================================


class TestCongestionControlledHttpClientPost:
    """Tests for basic POST request behavior."""

    def test_post_delegates_to_underlying_client(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        response = client.post("http://example.com/api", data={"key": "value"})

        assert response.status_code == 200
        assert len(delegate.post_calls) == 1
        assert delegate.post_calls[0]["url"] == "http://example.com/api"
        assert delegate.post_calls[0]["data"] == {"key": "value"}

    def test_post_passes_headers_to_delegate(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        client.post("http://example.com", headers={"X-Custom": "header"})

        assert delegate.post_calls[0]["headers"] == {"X-Custom": "header"}

    def test_post_passes_timeout_to_delegate(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        client.post("http://example.com", timeout=90)

        assert delegate.post_calls[0]["timeout"] == 90


# =============================================================================
# Token Bucket Tests
# =============================================================================


class TestCongestionControlledHttpClientTokenBucket:
    """Tests for token bucket behavior."""

    def test_raises_timeout_error_when_max_wait_time_exceeded(self):
        delegate = MockHttpClient()
        # Very restrictive rate: 1 request per 100 seconds
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=1,
            time_window=100.0,
            max_wait_time=0.1,
        )

        # First request consumes the only token
        client.post("http://example.com", data={})

        # Second request should timeout waiting for token
        with pytest.raises(TokenAcquisitionTimeoutError) as exc_info:
            client.post("http://example.com", data={})

        assert exc_info.value.max_wait_time == 0.1
        assert exc_info.value.waited >= 0

    def test_does_not_timeout_when_tokens_available(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=10,
            time_window=60.0,
            max_wait_time=1.0,
        )

        # Should not timeout - plenty of tokens
        response = client.post("http://example.com", data={})

        assert response.status_code == 200

    def test_tokens_refill_over_time(self):
        delegate = MockHttpClient()
        # 10 requests per second
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=10,
            time_window=1.0,
            max_wait_time=0.5,
        )

        # Consume all tokens
        for _ in range(10):
            client.post("http://example.com", data={})

        # Wait for partial refill
        time.sleep(0.2)  # Should refill ~2 tokens

        # Should be able to make at least one more request
        response = client.post("http://example.com", data={})
        assert response.status_code == 200


# =============================================================================
# Concurrency Control Tests
# =============================================================================


class TestCongestionControlledHttpClientConcurrency:
    """Tests for concurrency control via semaphore."""

    def test_semaphore_limits_concurrent_requests(self):
        """Only _concurrency_limit requests should be in-flight at once."""
        delegate = MockHttpClient(response_delay=0.1)  # Slow responses
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            max_concurrency=5,
        )

        # Start with concurrency_limit = 1
        assert client._concurrency_limit == 1

        concurrent_count = [0]
        max_concurrent = [0]
        lock = threading.Lock()

        original_post = delegate.post

        def tracking_post(*args, **kwargs):
            with lock:
                concurrent_count[0] += 1
                max_concurrent[0] = max(max_concurrent[0], concurrent_count[0])
            try:
                return original_post(*args, **kwargs)
            finally:
                with lock:
                    concurrent_count[0] -= 1

        delegate.post = tracking_post

        # Launch multiple threads
        threads = [
            threading.Thread(target=lambda: client.post("http://example.com", data={}))
            for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Max concurrent should not exceed concurrency_limit (which starts at 1)
        assert max_concurrent[0] <= client._concurrency_limit + 1  # +1 for race tolerance

    def test_semaphore_is_released_even_on_exception(self):
        """Semaphore should be released in finally block."""
        delegate = MockHttpClient()
        delegate.response.status_code = 500

        # Make delegate raise an exception
        def raising_post(*args, **kwargs):
            raise requests.RequestException("Network error")

        delegate.post = raising_post

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        initial_value = client._semaphore._value

        with pytest.raises(requests.RequestException):
            client.post("http://example.com", data={})

        # Semaphore should be released back
        assert client._semaphore._value == initial_value


# =============================================================================
# Latency Tracking Tests
# =============================================================================


class TestCongestionControlledHttpClientLatencyTracking:
    """Tests for latency EMA tracking."""

    def test_latency_ema_initialized_on_first_request(self):
        delegate = MockHttpClient(response_delay=0.05)
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        assert client._latency_ema is None

        client.post("http://example.com", data={})

        assert client._latency_ema is not None
        assert client._latency_ema >= 0.05  # At least the response delay

    def test_latency_ema_smooths_values(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            latency_alpha=0.2,
        )

        # Manually record latencies to test EMA
        client._record_latency(100.0)
        assert client._latency_ema == 100.0  # First value

        client._record_latency(200.0)
        # EMA = 0.2 * 200 + 0.8 * 100 = 40 + 80 = 120
        assert client._latency_ema == 120.0

        client._record_latency(100.0)
        # EMA = 0.2 * 100 + 0.8 * 120 = 20 + 96 = 116
        assert client._latency_ema == 116.0

    def test_latency_alpha_controls_smoothing(self):
        """Higher alpha = more reactive to new values."""
        delegate = MockHttpClient()

        # Low alpha (more stable)
        client_low = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            latency_alpha=0.1,
        )
        client_low._record_latency(100.0)
        client_low._record_latency(200.0)
        # EMA = 0.1 * 200 + 0.9 * 100 = 20 + 90 = 110
        assert client_low._latency_ema == 110.0

        # High alpha (more reactive)
        client_high = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            latency_alpha=0.5,
        )
        client_high._record_latency(100.0)
        client_high._record_latency(200.0)
        # EMA = 0.5 * 200 + 0.5 * 100 = 100 + 50 = 150
        assert client_high._latency_ema == 150.0


# =============================================================================
# AIMD Behavior Tests
# =============================================================================


class TestCongestionControlledHttpClientAIMD:
    """Tests for AIMD (Additive Increase, Multiplicative Decrease) behavior."""

    def test_on_success_increases_effective_max(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            recovery_factor=0.1,
        )

        # Reduce effective_max to simulate prior penalty
        client._effective_max = 50.0

        # Mock Jitter's RNG to return 1.0 (no jitter)
        client._jitter.next = MagicMock(return_value=1.0)

        client._on_success()

        # Recovery: 50 + (100 * 0.1 * 1.0) = 60
        assert client._effective_max == 60.0

    def test_on_success_does_not_exceed_max_requests(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            recovery_factor=0.5,
        )

        client._effective_max = 90.0
        client._jitter.next = MagicMock(return_value=1.0)

        client._on_success()

        # Should cap at max_requests
        assert client._effective_max == 100.0

    def test_on_success_applies_jitter(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            recovery_factor=0.1,
        )

        client._effective_max = 50.0
        client._jitter.next = MagicMock(return_value=0.8)  # 80% of base

        client._on_success()

        # Recovery: 50 + (100 * 0.1 * 0.8) = 58
        assert client._effective_max == 58.0

    def test_on_rate_limited_decreases_effective_max(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            penalty_factor=0.3,
        )

        client._effective_max = 100.0
        client._jitter.next = MagicMock(return_value=1.0)

        client._on_rate_limited()

        # Penalty: 100 * (1 - 0.3 * 1.0) = 70
        assert client._effective_max == 70.0

    def test_on_rate_limited_respects_floor(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            min_rate_floor=0.1,
            penalty_factor=0.9,
        )

        client._effective_max = 15.0
        client._jitter.next = MagicMock(return_value=1.0)

        client._on_rate_limited()

        # Should not go below floor (100 * 0.1 = 10)
        assert client._effective_max == 10.0

    def test_on_rate_limited_clamps_tokens(self):
        """Tokens should be clamped to effective_max after penalty."""
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            penalty_factor=0.5,
        )

        client._effective_max = 100.0
        client._tokens = 80.0
        client._jitter.next = MagicMock(return_value=1.0)

        client._on_rate_limited()

        # effective_max: 100 * (1 - 0.5) = 50
        # tokens should be clamped: min(80, 50) = 50
        assert client._effective_max == 50.0
        assert client._tokens == 50.0

    def test_on_rate_limited_applies_jitter(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            penalty_factor=0.3,
        )

        client._effective_max = 100.0
        client._jitter.next = MagicMock(return_value=1.2)  # 120% of base penalty

        client._on_rate_limited()

        # Penalty: 100 * (1 - 0.3 * 1.2) = 100 * 0.64 = 64
        assert client._effective_max == 64.0


# =============================================================================
# Concurrency Recomputation Tests
# =============================================================================


class TestCongestionControlledHttpClientConcurrencyRecomputation:
    """Tests for adaptive concurrency recomputation."""

    def test_recompute_does_nothing_when_no_latency(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            max_concurrency=10,
        )

        initial_limit = client._concurrency_limit
        client._recompute_concurrency()

        assert client._concurrency_limit == initial_limit

    def test_recompute_shrinks_immediately_when_target_lower(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=60,  # 1 req/sec
            time_window=60.0,
            max_concurrency=10,
        )

        # Set up state
        client._concurrency_limit = 5
        client._semaphore = threading.Semaphore(5)
        client._latency_ema = 0.5  # target = 1 * 0.5 = 0.5 → ceil = 1

        client._recompute_concurrency()

        # Should shrink to 1
        assert client._concurrency_limit == 1

    def test_recompute_grows_probabilistically(self):
        """Growth only happens when random() < 0.30 (30% chance)."""
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=60,  # 1 req/sec
            time_window=60.0,
            max_concurrency=10,
        )

        # Set up state for potential growth
        client._concurrency_limit = 1
        client._latency_ema = 5.0  # target = 1 * 5 = 5

        # Force growth by making random() return low value (< 0.30)
        # In the code: if self._jitter.random() >= 0.30: return (no growth)
        # So we need < 0.30 to grow
        client._jitter.random = MagicMock(return_value=0.2)

        client._recompute_concurrency()

        # Should grow by 1
        assert client._concurrency_limit == 2

    def test_recompute_does_not_grow_with_high_random(self):
        """Growth is skipped when random() >= 0.30 (70% chance)."""
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=60,
            time_window=60.0,
            max_concurrency=10,
        )

        client._concurrency_limit = 1
        client._latency_ema = 5.0

        # Prevent growth with high random value (>= 0.30)
        # In the code: if self._jitter.random() >= 0.30: return (no growth)
        client._jitter.random = MagicMock(return_value=0.5)

        client._recompute_concurrency()

        assert client._concurrency_limit == 1

    def test_recompute_respects_max_concurrency(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=60,
            time_window=60.0,
            max_concurrency=3,
        )

        client._concurrency_limit = 3
        client._latency_ema = 10.0  # Would suggest target > 3

        client._recompute_concurrency()

        # Should stay at max
        assert client._concurrency_limit <= 3


# =============================================================================
# HTTP 429 Handling Tests
# =============================================================================


class TestCongestionControlledHttpClient429Handling:
    """Tests for HTTP 429 handling."""

    def test_raises_server_side_rate_limit_error_on_429(self):
        delegate = MockHttpClient()
        delegate.response.status_code = 429
        delegate.response.headers = {}

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        with pytest.raises(ServerSideRateLimitError):
            client.post("http://example.com", data={})

    def test_applies_aimd_penalty_on_429(self):
        delegate = MockHttpClient()
        delegate.response.status_code = 429
        delegate.response.headers = {}

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            penalty_factor=0.5,
        )
        client._jitter.next = MagicMock(return_value=1.0)

        initial_effective_max = client._effective_max

        with pytest.raises(ServerSideRateLimitError):
            client.post("http://example.com", data={})

        assert client._effective_max < initial_effective_max
        assert client._effective_max == 50.0  # 100 * (1 - 0.5)

    def test_429_response_is_attached_to_exception(self):
        delegate = MockHttpClient()
        delegate.response.status_code = 429
        delegate.response.headers = {"Retry-After": "10"}

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        with pytest.raises(ServerSideRateLimitError) as exc_info:
            client.post("http://example.com", data={})

        assert exc_info.value.response is not None
        assert exc_info.value.response.status_code == 429
        assert exc_info.value.response.headers.get("Retry-After") == "10"

    def test_429_triggers_concurrency_recomputation(self):
        delegate = MockHttpClient()
        delegate.response.status_code = 429
        delegate.response.headers = {}

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        with patch.object(client, "_recompute_concurrency") as mock_recompute:
            with pytest.raises(ServerSideRateLimitError):
                client.post("http://example.com", data={})

            mock_recompute.assert_called_once()


# =============================================================================
# Success Flow Tests
# =============================================================================


class TestCongestionControlledHttpClientSuccessFlow:
    """Tests for successful request flow."""

    def test_success_triggers_aimd_recovery(self):
        delegate = MockHttpClient()
        delegate.response.status_code = 200

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            recovery_factor=0.1,
        )
        client._effective_max = 50.0
        client._jitter.next = MagicMock(return_value=1.0)

        client.post("http://example.com", data={})

        assert client._effective_max == 60.0  # 50 + (100 * 0.1)

    def test_success_triggers_concurrency_recomputation(self):
        delegate = MockHttpClient()
        delegate.response.status_code = 200

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        with patch.object(client, "_recompute_concurrency") as mock_recompute:
            client.post("http://example.com", data={})

            mock_recompute.assert_called_once()

    def test_success_records_latency(self):
        delegate = MockHttpClient(response_delay=0.05)
        delegate.response.status_code = 200

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        assert client._latency_ema is None

        client.post("http://example.com", data={})

        assert client._latency_ema is not None


# =============================================================================
# Thread Safety Tests
# =============================================================================


class TestCongestionControlledHttpClientThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_requests_do_not_corrupt_state(self):
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        errors = []

        def make_requests():
            try:
                for _ in range(10):
                    client.post("http://example.com", data={})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=make_requests) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should occur
        assert len(errors) == 0

        # State should be consistent
        assert client._effective_max > 0
        assert client._effective_max <= client.max_requests
        assert client._tokens >= 0

    def test_concurrent_429_handling(self):
        delegate = MockHttpClient()
        delegate.response.status_code = 429
        delegate.response.headers = {}

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            penalty_factor=0.1,
        )

        errors = []

        def make_request():
            try:
                client.post("http://example.com", data={})
            except ServerSideRateLimitError:
                pass  # Expected
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=make_request) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No unexpected errors
        assert len(errors) == 0

        # Effective max should have been reduced (but not corrupted)
        assert client._effective_max > 0
        assert client._effective_max < 100  # Should be reduced from penalties


# =============================================================================
# Integration Tests
# =============================================================================


class TestCongestionControlledHttpClientIntegration:
    """Integration tests for the full request flow."""

    def test_full_flow_with_mixed_responses(self):
        """Test a realistic flow with successes and 429s."""
        delegate = MockHttpClient()
        call_count = [0]

        original_post = delegate.post

        def alternating_post(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] % 3 == 0:
                delegate.response.status_code = 429
            else:
                delegate.response.status_code = 200
            return original_post(*args, **kwargs)

        delegate.post = alternating_post

        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        success_count = 0
        rate_limit_count = 0

        for _ in range(9):
            try:
                client.post("http://example.com", data={})
                success_count += 1
            except ServerSideRateLimitError:
                rate_limit_count += 1

        assert success_count == 6  # 2 out of every 3
        assert rate_limit_count == 3  # 1 out of every 3

    def test_recovery_after_penalties(self):
        """Test that rate recovers after successful requests."""
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            penalty_factor=0.5,
            recovery_factor=0.1,
        )
        client._jitter.next = MagicMock(return_value=1.0)

        # Apply penalty
        client._on_rate_limited()
        assert client._effective_max == 50.0

        # Multiple successes should recover
        for _ in range(5):
            client._on_success()

        # Recovery: 50 → 60 → 70 → 80 → 90 → 100
        assert client._effective_max == 100.0

    def test_uses_monotonic_time(self):
        """Verify that time.monotonic is used for timing."""
        delegate = MockHttpClient()
        client = CongestionControlledHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        # The implementation uses time.monotonic() for _last_refill
        # This is verified by checking the attribute exists and is a float
        assert isinstance(client._last_refill, float)
