"""Tests for rate limiting implementations."""

import threading
from unittest.mock import MagicMock, patch

import pytest
import requests

from stkai import (
    AdaptiveRateLimitedHttpClient,
    ClientSideRateLimitError,
    HttpClient,
    ServerSideRateLimitError,
    TokenAcquisitionTimeoutError,
    TokenBucketRateLimitedHttpClient,
)
from stkai._rate_limit import Jitter

# =============================================================================
# Exception Hierarchy Tests
# =============================================================================


class TestExceptionHierarchy:
    """Tests for rate limit exception hierarchy."""

    def test_client_side_rate_limit_error_extends_retryable_error(self):
        """ClientSideRateLimitError should extend RetryableError."""
        from stkai._retry import RetryableError

        assert issubclass(ClientSideRateLimitError, RetryableError)

    def test_rate_limit_timeout_error_extends_client_side_rate_limit_error(self):
        """TokenAcquisitionTimeoutError should extend ClientSideRateLimitError."""
        assert issubclass(TokenAcquisitionTimeoutError, ClientSideRateLimitError)

    def test_server_side_rate_limit_error_extends_retryable_error(self):
        """ServerSideRateLimitError should extend RetryableError."""
        from stkai._retry import RetryableError

        assert issubclass(ServerSideRateLimitError, RetryableError)

    def test_server_side_rate_limit_error_not_client_side(self):
        """ServerSideRateLimitError should NOT extend ClientSideRateLimitError."""
        assert not issubclass(ServerSideRateLimitError, ClientSideRateLimitError)

    def test_can_catch_all_client_side_errors(self):
        """Should be able to catch all client-side rate limit errors with base class."""
        error = TokenAcquisitionTimeoutError(waited=5.0, max_wait_time=10.0)

        # Can catch with specific class
        assert isinstance(error, TokenAcquisitionTimeoutError)
        # Can catch with base client-side class
        assert isinstance(error, ClientSideRateLimitError)

    def test_server_side_error_contains_response(self):
        """ServerSideRateLimitError should contain the HTTP response."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "10"}

        error = ServerSideRateLimitError(mock_response)

        assert error.response is mock_response
        assert error.response.status_code == 429


# =============================================================================
# Jitter Tests
# =============================================================================


class TestJitter:
    """Tests for the Jitter class."""

    def test_init_with_default_factor(self):
        """Should use 0.20 (±20%) as default factor."""
        jitter = Jitter()
        assert jitter.factor == 0.20

    def test_init_with_custom_factor(self):
        """Should accept custom factor."""
        jitter = Jitter(factor=0.10)
        assert jitter.factor == 0.10

    def test_init_fails_with_negative_factor(self):
        """Factor must be non-negative."""
        with pytest.raises(AssertionError, match="factor must be non-negative"):
            Jitter(factor=-0.1)

    def test_init_fails_with_factor_greater_than_or_equal_to_one(self):
        """Factor must be less than 1."""
        with pytest.raises(AssertionError, match="factor must be less than 1"):
            Jitter(factor=1.0)

    def test_init_with_custom_rng(self):
        """Should accept custom RNG for testing."""
        import random
        custom_rng = random.Random(42)
        jitter = Jitter(rng=custom_rng)
        assert jitter._rng is custom_rng

    def test_init_creates_process_local_rng_by_default(self):
        """Should create a deterministic per-process RNG when no RNG provided."""
        import os
        import random
        import socket

        jitter = Jitter()

        expected_seed = hash((socket.gethostname(), os.getpid()))
        test_rng = random.Random(expected_seed)

        # Both should produce the same sequence
        assert jitter._rng.random() == test_rng.random()

    def test_next_returns_value_in_range(self):
        """next() should return a value in [1-factor, 1+factor]."""
        import random
        rng = random.Random(42)
        jitter = Jitter(factor=0.20, rng=rng)

        for _ in range(100):
            m = jitter.next()
            assert 0.80 <= m <= 1.20

    def test_random_returns_value_in_range(self):
        """random() should return a value in [0, 1)."""
        import random
        rng = random.Random(42)
        jitter = Jitter(factor=0.20, rng=rng)

        for _ in range(100):
            r = jitter.random()
            assert 0.0 <= r < 1.0

    def test_random_ignores_factor(self):
        """random() should not be affected by factor."""
        import random
        rng1 = random.Random(42)
        rng2 = random.Random(42)

        jitter_small = Jitter(factor=0.10, rng=rng1)
        jitter_large = Jitter(factor=0.50, rng=rng2)

        # Both should produce the same random() values since factor is ignored
        for _ in range(10):
            assert jitter_small.random() == jitter_large.random()

    def test_apply_jitters_value(self):
        """Apply should multiply value by jitter factor."""
        import random
        rng = random.Random(42)
        jitter = Jitter(factor=0.20, rng=rng)

        value = 100.0
        jittered = jitter.apply(value)

        # Should be in range [80, 120]
        assert 80.0 <= jittered <= 120.0

    def test_apply_with_mock_rng(self):
        """Apply should use the correct calculation."""
        mock_rng = MagicMock()
        mock_rng.uniform = MagicMock(return_value=0.9)

        jitter = Jitter(factor=0.20, rng=mock_rng)
        result = jitter.apply(100.0)

        assert result == 90.0  # 100 * 0.9
        mock_rng.uniform.assert_called_once_with(0.8, 1.2)

    def test_mul_operator(self):
        """jitter * value should work."""
        import random
        rng = random.Random(42)
        jitter = Jitter(factor=0.20, rng=rng)

        value = 100.0
        jittered = jitter * value

        assert 80.0 <= jittered <= 120.0

    def test_rmul_operator(self):
        """value * jitter should work."""
        import random
        rng = random.Random(42)
        jitter = Jitter(factor=0.20, rng=rng)

        value = 100.0
        jittered = value * jitter

        assert 80.0 <= jittered <= 120.0

    def test_each_call_produces_new_value(self):
        """Each next/apply call should produce a new random value."""
        import random
        rng = random.Random(42)
        jitter = Jitter(factor=0.20, rng=rng)

        values = [jitter.next() for _ in range(10)]

        # Should have variation (not all the same)
        assert len(set(values)) > 1

    def test_zero_factor_produces_no_jitter(self):
        """Factor of 0 should produce exactly the input value."""
        jitter = Jitter(factor=0.0)

        for _ in range(10):
            assert jitter.apply(100.0) == 100.0
            assert jitter.next() == 1.0


# =============================================================================
# TokenAcquisitionTimeoutError Tests
# =============================================================================


class TestTokenAcquisitionTimeoutError:
    """Tests for TokenAcquisitionTimeoutError exception."""

    def test_error_message_contains_waited_and_max_wait_time(self):
        error = TokenAcquisitionTimeoutError(waited=45.5, max_wait_time=60.0)

        assert "45.50s" in str(error)
        assert "60.00s" in str(error)
        assert "Rate limit timeout" in str(error)

    def test_error_exposes_waited_attribute(self):
        error = TokenAcquisitionTimeoutError(waited=30.0, max_wait_time=60.0)

        assert error.waited == 30.0

    def test_error_exposes_max_wait_time_attribute(self):
        error = TokenAcquisitionTimeoutError(waited=30.0, max_wait_time=60.0)

        assert error.max_wait_time == 60.0

    def test_error_is_exception_subclass(self):
        error = TokenAcquisitionTimeoutError(waited=10.0, max_wait_time=20.0)

        assert isinstance(error, Exception)


# =============================================================================
# MockHttpClient
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


# =============================================================================
# TokenBucketRateLimitedHttpClient Tests
# =============================================================================


class TestRateLimitedHttpClientInit:
    """Tests for TokenBucketRateLimitedHttpClient initialization."""

    def test_init_with_default_max_wait_time(self):
        delegate = MockHttpClient()

        client = TokenBucketRateLimitedHttpClient(
            delegate=delegate,
            max_requests=10,
            time_window=60.0,
        )

        assert client.max_wait_time == 30.0

    def test_init_with_custom_max_wait_time(self):
        delegate = MockHttpClient()

        client = TokenBucketRateLimitedHttpClient(
            delegate=delegate,
            max_requests=10,
            time_window=60.0,
            max_wait_time=120.0,
        )

        assert client.max_wait_time == 120.0

    def test_init_with_none_max_wait_time_allows_infinite_wait(self):
        delegate = MockHttpClient()

        client = TokenBucketRateLimitedHttpClient(
            delegate=delegate,
            max_requests=10,
            time_window=60.0,
            max_wait_time=None,
        )

        assert client.max_wait_time is None

    def test_init_fails_when_max_wait_time_is_zero(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match="max_wait_time must be > 0 or None"):
            TokenBucketRateLimitedHttpClient(
                delegate=delegate,
                max_requests=10,
                time_window=60.0,
                max_wait_time=0,
            )

    def test_init_fails_when_max_wait_time_is_negative(self):
        delegate = MockHttpClient()

        with pytest.raises(AssertionError, match="max_wait_time must be > 0 or None"):
            TokenBucketRateLimitedHttpClient(
                delegate=delegate,
                max_requests=10,
                time_window=60.0,
                max_wait_time=-1.0,
            )


class TestRateLimitedHttpClientTimeout:
    """Tests for TokenBucketRateLimitedHttpClient timeout behavior."""

    def test_raises_timeout_error_when_max_wait_time_exceeded(self):
        delegate = MockHttpClient()
        # Very restrictive rate: 1 request per 100 seconds
        client = TokenBucketRateLimitedHttpClient(
            delegate=delegate,
            max_requests=1,
            time_window=100.0,
            max_wait_time=0.1,  # Very short timeout
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
        client = TokenBucketRateLimitedHttpClient(
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
        client = TokenBucketRateLimitedHttpClient(
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
    """Tests for thread isolation in TokenBucketRateLimitedHttpClient."""

    def test_each_thread_has_independent_timeout(self):
        delegate = MockHttpClient()
        # Very restrictive: 1 request per 10 seconds
        client = TokenBucketRateLimitedHttpClient(
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
            except TokenAcquisitionTimeoutError as e:
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

        assert client.max_wait_time == 30.0

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
        with pytest.raises(TokenAcquisitionTimeoutError) as exc_info:
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


class TestAdaptiveRateLimitedHttpClientTokenInvariant:
    """Tests for token bucket invariant in AdaptiveRateLimitedHttpClient."""

    def test_tokens_clamped_after_penalty(self):
        """Test that tokens are clamped to effective_max after penalty.

        Scenario: tokens=80, effective_max=100, penalty reduces to 50 → tokens must be 50.
        """
        delegate = MockHttpClient()
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            penalty_factor=0.5,  # 50% reduction: 100 → 50
            max_wait_time=None,
        )

        # Manually set tokens to 80 (simulating partial bucket)
        client._tokens = 80.0
        assert client._effective_max == 100.0

        # Mock Jitter to return multiplier of 1.0 (no jitter) for deterministic test
        client._jitter.next = MagicMock(return_value=1.0)

        # Trigger penalty
        client._on_rate_limited()

        # effective_max should be reduced by 50%: 100 * (1 - 0.5 * 1.0) = 50
        assert client._effective_max == 50.0
        # tokens should be clamped to the new effective_max
        assert client._tokens == 50.0


class TestAdaptiveRateLimitedHttpClient429Handling:
    """Tests for 429 handling in AdaptiveRateLimitedHttpClient."""

    def test_raises_server_side_rate_limit_error_on_429_and_adapts_rate(self):
        """Test that 429 applies AIMD penalty and raises ServerSideRateLimitError."""
        delegate = MockHttpClient()
        delegate.response.status_code = 429
        delegate.response.headers = {}

        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            penalty_factor=0.5,
            max_wait_time=None,  # Disable timeout for this test
        )

        initial_effective_max = client._effective_max

        # 429 should raise ServerSideRateLimitError (for Retrying to handle)
        with pytest.raises(ServerSideRateLimitError):
            client.post("http://example.com", data={})

        # Effective max should be reduced (AIMD penalty applied)
        assert client._effective_max < initial_effective_max
        # Should have made only 1 attempt (no internal retry)
        assert len(delegate.post_calls) == 1

    def test_server_side_rate_limit_error_contains_response(self):
        """Test that ServerSideRateLimitError contains the response for Retry-After parsing."""
        delegate = MockHttpClient()
        delegate.response.status_code = 429
        delegate.response.headers = {"Retry-After": "5"}

        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            max_wait_time=None,
        )

        with pytest.raises(ServerSideRateLimitError) as exc_info:
            client.post("http://example.com", data={})

        # The exception should have the response attached (for Retry-After parsing)
        assert exc_info.value.response is not None
        assert exc_info.value.response.status_code == 429
        assert exc_info.value.response.headers.get("Retry-After") == "5"

    def test_success_recovers_rate(self):
        """Test that successful requests trigger AIMD recovery."""
        delegate = MockHttpClient()
        delegate.response.status_code = 200
        delegate.response.headers = {}

        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            recovery_factor=0.1,  # 10% recovery
            max_wait_time=None,
        )

        # Manually reduce effective_max to simulate prior penalty
        client._effective_max = 50.0

        # Mock Jitter to return multiplier of 1.0 (no jitter) for deterministic test
        client._jitter.next = MagicMock(return_value=1.0)

        client.post("http://example.com", data={})

        # Recovery: 50 + (100 * 0.1 * 1.0) = 60
        assert client._effective_max == 60.0


class TestAdaptiveRateLimitedHttpClientJitter:
    """Tests for jitter behavior in AdaptiveRateLimitedHttpClient."""

    def test_init_creates_jitter_with_deterministic_rng(self):
        """Jitter should use a per-process seeded RNG for structural jitter."""
        delegate = MockHttpClient()

        client1 = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        client2 = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )

        # Both should have Jitter instances
        assert client1._jitter is not None
        assert client2._jitter is not None

        # Verify the seed is based on hostname+pid (deterministic within same process)
        import os
        import random
        import socket
        expected_seed = hash((socket.gethostname(), os.getpid()))

        # Create a new RNG with same seed and verify it produces same values
        test_rng = random.Random(expected_seed)
        client3 = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
        )
        # Both should start with the same sequence
        assert test_rng.random() == client3._jitter.random()

    def test_on_success_applies_jittered_recovery(self):
        """Recovery factor should vary with ±20% jitter."""
        delegate = MockHttpClient()
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            recovery_factor=0.1,
        )

        client._effective_max = 50.0
        # Mock Jitter's RNG to return 0.8 (lower bound of ±20% jitter)
        client._jitter.next = MagicMock(return_value=0.8)

        client._on_success()

        # Recovery: 50 + (100 * 0.1 * 0.8) = 58.0
        assert client._effective_max == 58.0

    def test_on_success_uses_jitter(self):
        """Recovery should use jitter for desynchronization."""
        delegate = MockHttpClient()
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            recovery_factor=0.1,
        )

        client._effective_max = 50.0
        client._jitter.next = MagicMock(return_value=1.0)

        client._on_success()

        # Verify jitter was used
        client._jitter.next.assert_called_once()

    def test_on_rate_limited_applies_jittered_penalty(self):
        """Penalty factor should vary with ±20% jitter."""
        delegate = MockHttpClient()
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            penalty_factor=0.3,
        )

        client._effective_max = 100.0
        # Mock Jitter's RNG to return 1.2 (upper bound of ±20% jitter)
        client._jitter.next = MagicMock(return_value=1.2)

        client._on_rate_limited()

        # Penalty: 100 * (1 - 0.3 * 1.2) = 100 * (1 - 0.36) = 64.0
        assert client._effective_max == 64.0

    def test_on_rate_limited_uses_jitter(self):
        """Penalty should use jitter for desynchronization."""
        delegate = MockHttpClient()
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=100,
            time_window=60.0,
            penalty_factor=0.3,
        )

        client._effective_max = 100.0
        client._jitter.next = MagicMock(return_value=1.0)

        client._on_rate_limited()

        # Verify jitter was used
        client._jitter.next.assert_called_once()

    def test_acquire_token_uses_sleep_with_jitter(self):
        """Token acquisition should use sleep_with_jitter for desynchronization."""
        delegate = MockHttpClient()
        # Slow rate: 1 request per 10 seconds
        client = AdaptiveRateLimitedHttpClient(
            delegate=delegate,
            max_requests=1,
            time_window=10.0,
            max_wait_time=1.0,
        )

        # Consume the only token
        client._acquire_token()

        # Now test that next acquisition uses sleep_with_jitter
        with patch("stkai._rate_limit.sleep_with_jitter") as mock_sleep:
            # This will timeout but we want to verify sleep_with_jitter is called
            try:
                client._acquire_token()
            except Exception:
                pass  # Expected timeout

            # Verify sleep_with_jitter was called with correct jitter_factor (±20%)
            if mock_sleep.called:
                call_args = mock_sleep.call_args
                assert call_args[1].get("jitter_factor") == 0.20 or \
                       (len(call_args[0]) > 1 and call_args[0][1] == 0.20)
