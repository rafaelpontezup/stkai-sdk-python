"""Tests for global configuration module."""

import os
import unittest
from unittest.mock import patch

from stkai._config import (
    STKAI,
    AgentConfig,
    AuthConfig,
    RateLimitConfig,
    RqcConfig,
    STKAIConfig,
)


class TestDefaults(unittest.TestCase):
    """Tests for default configuration values."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    def test_rqc_defaults(self):
        """Should return sensible defaults for RQC config."""
        self.assertEqual(STKAI.config.rqc.request_timeout, 30)
        self.assertEqual(STKAI.config.rqc.max_retries, 3)
        self.assertEqual(STKAI.config.rqc.backoff_factor, 0.5)
        self.assertEqual(STKAI.config.rqc.poll_interval, 10.0)
        self.assertEqual(STKAI.config.rqc.poll_max_duration, 600.0)
        self.assertEqual(STKAI.config.rqc.overload_timeout, 60.0)
        self.assertEqual(STKAI.config.rqc.max_workers, 8)
        self.assertEqual(STKAI.config.rqc.base_url, "https://genai-code-buddy-api.stackspot.com")

    def test_agent_defaults(self):
        """Should return sensible defaults for Agent config."""
        self.assertEqual(STKAI.config.agent.base_url, "https://genai-inference-app.stackspot.com")
        self.assertEqual(STKAI.config.agent.request_timeout, 60)

    def test_auth_defaults(self):
        """Should return None for auth credentials when not configured."""
        self.assertIsNone(STKAI.config.auth.client_id)
        self.assertIsNone(STKAI.config.auth.client_secret)

    def test_has_credentials_false_by_default(self):
        """Should return False when no credentials configured."""
        self.assertFalse(STKAI.config.auth.has_credentials())


class TestSTKAIConfigure(unittest.TestCase):
    """Tests for STKAI.configure() method."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    def test_configure_rqc_values(self):
        """Should override RQC defaults with STKAI.configure()."""
        STKAI.configure(rqc={"request_timeout": 60, "max_retries": 10})
        self.assertEqual(STKAI.config.rqc.request_timeout, 60)
        self.assertEqual(STKAI.config.rqc.max_retries, 10)
        # Other values should remain default
        self.assertEqual(STKAI.config.rqc.poll_interval, 10.0)

    def test_configure_agent_values(self):
        """Should override Agent defaults with STKAI.configure()."""
        STKAI.configure(agent={"request_timeout": 120})
        self.assertEqual(STKAI.config.agent.request_timeout, 120)
        # Base URL should remain default
        self.assertEqual(STKAI.config.agent.base_url, "https://genai-inference-app.stackspot.com")

    def test_configure_auth_values(self):
        """Should set auth credentials via STKAI.configure()."""
        STKAI.configure(auth={"client_id": "my-id", "client_secret": "my-secret"})
        self.assertEqual(STKAI.config.auth.client_id, "my-id")
        self.assertEqual(STKAI.config.auth.client_secret, "my-secret")
        self.assertTrue(STKAI.config.auth.has_credentials())

    def test_configure_partial_auth(self):
        """Should handle partial auth credentials."""
        STKAI.configure(auth={"client_id": "my-id"})
        self.assertFalse(STKAI.config.auth.has_credentials())  # Need both

    def test_configure_returns_instance(self):
        """Should return the configured STKAIConfig instance."""
        result = STKAI.configure(rqc={"request_timeout": 60})
        self.assertIsInstance(result, STKAIConfig)
        self.assertEqual(result.rqc.request_timeout, 60)
        # STKAI.config should return same values
        self.assertEqual(STKAI.config.rqc.request_timeout, 60)

    def test_configure_isolation_between_rqc_and_agent(self):
        """RQC config should not affect Agent config and vice versa."""
        STKAI.configure(rqc={"request_timeout": 30}, agent={"request_timeout": 120})
        self.assertEqual(STKAI.config.rqc.request_timeout, 30)
        self.assertEqual(STKAI.config.agent.request_timeout, 120)


class TestEnvVars(unittest.TestCase):
    """Tests for environment variable override."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "45"})
    def test_rqc_env_var_override(self):
        """Should use env var value over defaults."""
        STKAI.reset()  # Re-read env vars
        self.assertEqual(STKAI.config.rqc.request_timeout, 45)

    @patch.dict(os.environ, {"STKAI_RQC_MAX_RETRIES": "7"})
    def test_rqc_env_var_int_conversion(self):
        """Should convert env var string to int."""
        STKAI.reset()
        self.assertEqual(STKAI.config.rqc.max_retries, 7)

    @patch.dict(os.environ, {"STKAI_RQC_POLL_INTERVAL": "15.5"})
    def test_rqc_env_var_float_conversion(self):
        """Should convert env var string to float."""
        STKAI.reset()
        self.assertEqual(STKAI.config.rqc.poll_interval, 15.5)

    @patch.dict(os.environ, {"STKAI_AGENT_REQUEST_TIMEOUT": "180"})
    def test_agent_env_var_override(self):
        """Should use env var value for Agent config."""
        STKAI.reset()
        self.assertEqual(STKAI.config.agent.request_timeout, 180)

    @patch.dict(os.environ, {"STKAI_AGENT_BASE_URL": "https://custom.url"})
    def test_agent_base_url_env_var(self):
        """Should use env var for Agent base_url."""
        STKAI.reset()
        self.assertEqual(STKAI.config.agent.base_url, "https://custom.url")

    @patch.dict(os.environ, {"STKAI_AUTH_CLIENT_ID": "env-id", "STKAI_AUTH_CLIENT_SECRET": "env-secret"})
    def test_auth_from_env_vars(self):
        """Should read auth credentials from env vars."""
        STKAI.reset()
        self.assertEqual(STKAI.config.auth.client_id, "env-id")
        self.assertEqual(STKAI.config.auth.client_secret, "env-secret")
        self.assertTrue(STKAI.config.auth.has_credentials())

    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "45"})
    def test_configure_overrides_env_vars(self):
        """configure() values should take precedence over env vars."""
        STKAI.configure(rqc={"request_timeout": 90}, allow_env_override=True)
        self.assertEqual(STKAI.config.rqc.request_timeout, 90)  # configure wins

    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "45", "STKAI_RQC_MAX_RETRIES": "7"})
    def test_env_vars_used_as_fallback(self):
        """Env vars should be used for fields NOT provided in configure()."""
        STKAI.configure(rqc={"request_timeout": 90}, allow_env_override=True)
        self.assertEqual(STKAI.config.rqc.request_timeout, 90)  # configure wins
        self.assertEqual(STKAI.config.rqc.max_retries, 7)  # env var fallback

    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "45"})
    def test_configure_without_env_override(self):
        """STKAI.configure() values should win when allow_env_override=False."""
        STKAI.configure(rqc={"request_timeout": 90}, allow_env_override=False)
        self.assertEqual(STKAI.config.rqc.request_timeout, 90)  # configure wins


class TestSTKAIReset(unittest.TestCase):
    """Tests for STKAI.reset() method."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    def test_reset_clears_config(self):
        """STKAI.reset() should restore defaults."""
        STKAI.configure(
            auth={"client_id": "my-id", "client_secret": "my-secret"},
            rqc={"request_timeout": 999},
            agent={"request_timeout": 888},
        )
        STKAI.reset()
        self.assertEqual(STKAI.config.rqc.request_timeout, 30)
        self.assertEqual(STKAI.config.agent.request_timeout, 60)
        self.assertFalse(STKAI.config.auth.has_credentials())

    def test_reset_returns_instance(self):
        """STKAI.reset() should return the reset instance."""
        result = STKAI.reset()
        self.assertIsInstance(result, STKAIConfig)
        # STKAI.config should return same values
        self.assertEqual(result.rqc.request_timeout, STKAI.config.rqc.request_timeout)


class TestAllEnvVars(unittest.TestCase):
    """Tests to ensure all env vars work correctly."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    @patch.dict(
        os.environ,
        {
            "STKAI_RQC_BASE_URL": "https://rqc.custom",
            "STKAI_RQC_REQUEST_TIMEOUT": "100",
            "STKAI_RQC_MAX_RETRIES": "5",
            "STKAI_RQC_BACKOFF_FACTOR": "1.0",
            "STKAI_RQC_POLL_INTERVAL": "20.0",
            "STKAI_RQC_POLL_MAX_DURATION": "900.0",
            "STKAI_RQC_OVERLOAD_TIMEOUT": "120.0",
            "STKAI_RQC_MAX_WORKERS": "16",
        },
    )
    def test_all_rqc_env_vars(self):
        """All RQC env vars should be read correctly."""
        STKAI.reset()
        self.assertEqual(STKAI.config.rqc.base_url, "https://rqc.custom")
        self.assertEqual(STKAI.config.rqc.request_timeout, 100)
        self.assertEqual(STKAI.config.rqc.max_retries, 5)
        self.assertEqual(STKAI.config.rqc.backoff_factor, 1.0)
        self.assertEqual(STKAI.config.rqc.poll_interval, 20.0)
        self.assertEqual(STKAI.config.rqc.poll_max_duration, 900.0)
        self.assertEqual(STKAI.config.rqc.overload_timeout, 120.0)
        self.assertEqual(STKAI.config.rqc.max_workers, 16)

    @patch.dict(
        os.environ,
        {
            "STKAI_AGENT_BASE_URL": "https://agent.custom",
            "STKAI_AGENT_REQUEST_TIMEOUT": "200",
        },
    )
    def test_all_agent_env_vars(self):
        """All Agent env vars should be read correctly."""
        STKAI.reset()
        self.assertEqual(STKAI.config.agent.base_url, "https://agent.custom")
        self.assertEqual(STKAI.config.agent.request_timeout, 200)


class TestWithOverrides(unittest.TestCase):
    """Tests for OverridableConfig.with_overrides() method."""

    def test_with_overrides_returns_new_instance(self):
        """with_overrides() should return a new instance."""
        original = RqcConfig()
        modified = original.with_overrides({"request_timeout": 60})
        self.assertIsNot(original, modified)
        self.assertEqual(original.request_timeout, 30)  # unchanged
        self.assertEqual(modified.request_timeout, 60)

    def test_with_overrides_partial_update(self):
        """with_overrides() should only update specified fields."""
        config = RqcConfig().with_overrides({"request_timeout": 60})
        self.assertEqual(config.request_timeout, 60)
        self.assertEqual(config.max_retries, 3)  # unchanged

    def test_with_overrides_empty_dict(self):
        """with_overrides() with empty dict should return same instance."""
        original = RqcConfig()
        result = original.with_overrides({})
        self.assertIs(original, result)

    def test_with_overrides_none_values_ignored(self):
        """with_overrides() should ignore None values."""
        original = RqcConfig()
        result = original.with_overrides({"request_timeout": None})
        self.assertIs(original, result)

    def test_with_overrides_invalid_field_raises_error(self):
        """with_overrides() should raise ValueError for unknown fields."""
        config = RqcConfig()
        with self.assertRaises(ValueError) as context:
            config.with_overrides({"invalid_field": 123})
        self.assertIn("invalid_field", str(context.exception))
        self.assertIn("Unknown config fields", str(context.exception))

    def test_with_overrides_typo_raises_error(self):
        """with_overrides() should catch typos in field names."""
        config = RqcConfig()
        with self.assertRaises(ValueError) as context:
            config.with_overrides({"request_timout": 60})  # typo
        self.assertIn("request_timout", str(context.exception))


class TestDataclassImmutability(unittest.TestCase):
    """Tests for dataclass immutability (frozen=True)."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    def test_rqc_config_is_frozen(self):
        """RqcConfig should be immutable."""
        config = RqcConfig()
        with self.assertRaises(AttributeError):
            config.request_timeout = 999  # type: ignore

    def test_agent_config_is_frozen(self):
        """AgentConfig should be immutable."""
        config = AgentConfig()
        with self.assertRaises(AttributeError):
            config.request_timeout = 999  # type: ignore

    def test_auth_config_is_frozen(self):
        """AuthConfig should be immutable."""
        config = AuthConfig()
        with self.assertRaises(AttributeError):
            config.client_id = "test"  # type: ignore


class TestAuthConfigHasCredentials(unittest.TestCase):
    """Tests for AuthConfig.has_credentials() method."""

    def test_has_credentials_both_set(self):
        """Should return True when both credentials are set."""
        config = AuthConfig(client_id="id", client_secret="secret")
        self.assertTrue(config.has_credentials())

    def test_has_credentials_only_client_id(self):
        """Should return False when only client_id is set."""
        config = AuthConfig(client_id="id")
        self.assertFalse(config.has_credentials())

    def test_has_credentials_only_client_secret(self):
        """Should return False when only client_secret is set."""
        config = AuthConfig(client_secret="secret")
        self.assertFalse(config.has_credentials())

    def test_has_credentials_none(self):
        """Should return False when no credentials are set."""
        config = AuthConfig()
        self.assertFalse(config.has_credentials())

    def test_has_credentials_empty_strings(self):
        """Should return False when credentials are empty strings."""
        config = AuthConfig(client_id="", client_secret="")
        self.assertFalse(config.has_credentials())


class TestSTKAIRepr(unittest.TestCase):
    """Tests for STKAI.__repr__() method."""

    def test_repr_includes_config(self):
        """STKAI repr should include config representation."""
        repr_str = repr(STKAI)
        self.assertIn("STKAI", repr_str)
        self.assertIn("config=", repr_str)


class TestRateLimitConfigDefaults(unittest.TestCase):
    """Tests for RateLimitConfig default values."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    def test_rate_limit_disabled_by_default(self):
        """Rate limiting should be disabled by default."""
        self.assertFalse(STKAI.config.rate_limit.enabled)

    def test_rate_limit_default_strategy(self):
        """Default strategy should be token_bucket."""
        self.assertEqual(STKAI.config.rate_limit.strategy, "token_bucket")

    def test_rate_limit_default_values(self):
        """Should have sensible defaults for rate limiting."""
        rl = STKAI.config.rate_limit
        self.assertEqual(rl.max_requests, 100)
        self.assertEqual(rl.time_window, 60.0)
        self.assertEqual(rl.max_wait_time, 60.0)
        self.assertEqual(rl.min_rate_floor, 0.1)
        self.assertEqual(rl.max_retries_on_429, 3)
        self.assertEqual(rl.penalty_factor, 0.2)
        self.assertEqual(rl.recovery_factor, 0.01)


class TestRateLimitConfigure(unittest.TestCase):
    """Tests for configuring rate limiting via STKAI.configure()."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    def test_configure_rate_limit_enabled(self):
        """Should enable rate limiting via configure()."""
        STKAI.configure(rate_limit={"enabled": True})
        self.assertTrue(STKAI.config.rate_limit.enabled)

    def test_configure_rate_limit_strategy(self):
        """Should set strategy via configure()."""
        STKAI.configure(rate_limit={"strategy": "adaptive"})
        self.assertEqual(STKAI.config.rate_limit.strategy, "adaptive")

    def test_configure_rate_limit_token_bucket(self):
        """Should configure token_bucket strategy."""
        STKAI.configure(
            rate_limit={
                "enabled": True,
                "strategy": "token_bucket",
                "max_requests": 10,
                "time_window": 30.0,
            }
        )
        rl = STKAI.config.rate_limit
        self.assertTrue(rl.enabled)
        self.assertEqual(rl.strategy, "token_bucket")
        self.assertEqual(rl.max_requests, 10)
        self.assertEqual(rl.time_window, 30.0)

    def test_configure_rate_limit_adaptive(self):
        """Should configure adaptive strategy with all parameters."""
        STKAI.configure(
            rate_limit={
                "enabled": True,
                "strategy": "adaptive",
                "max_requests": 50,
                "time_window": 120.0,
                "max_wait_time": 30.0,
                "min_rate_floor": 0.2,
                "max_retries_on_429": 5,
                "penalty_factor": 0.3,
                "recovery_factor": 0.02,
            }
        )
        rl = STKAI.config.rate_limit
        self.assertTrue(rl.enabled)
        self.assertEqual(rl.strategy, "adaptive")
        self.assertEqual(rl.max_requests, 50)
        self.assertEqual(rl.time_window, 120.0)
        self.assertEqual(rl.max_wait_time, 30.0)
        self.assertEqual(rl.min_rate_floor, 0.2)
        self.assertEqual(rl.max_retries_on_429, 5)
        self.assertEqual(rl.penalty_factor, 0.3)
        self.assertEqual(rl.recovery_factor, 0.02)

    def test_configure_rate_limit_max_wait_time_none(self):
        """Should allow None for max_wait_time (unlimited wait)."""
        STKAI.configure(rate_limit={"max_wait_time": None})
        self.assertIsNone(STKAI.config.rate_limit.max_wait_time)

    def test_configure_rate_limit_invalid_field_raises_error(self):
        """Should raise ValueError for unknown fields."""
        with self.assertRaises(ValueError) as context:
            STKAI.configure(rate_limit={"invalid_field": True})
        self.assertIn("invalid_field", str(context.exception))


class TestRateLimitEnvVars(unittest.TestCase):
    """Tests for rate limit environment variables."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_ENABLED": "true"})
    def test_enabled_env_var_true(self):
        """Should read enabled=true from env var."""
        STKAI.reset()
        self.assertTrue(STKAI.config.rate_limit.enabled)

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_ENABLED": "1"})
    def test_enabled_env_var_one(self):
        """Should read enabled=1 from env var."""
        STKAI.reset()
        self.assertTrue(STKAI.config.rate_limit.enabled)

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_ENABLED": "yes"})
    def test_enabled_env_var_yes(self):
        """Should read enabled=yes from env var."""
        STKAI.reset()
        self.assertTrue(STKAI.config.rate_limit.enabled)

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_ENABLED": "false"})
    def test_enabled_env_var_false(self):
        """Should read enabled=false from env var."""
        STKAI.reset()
        self.assertFalse(STKAI.config.rate_limit.enabled)

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_STRATEGY": "adaptive"})
    def test_strategy_env_var(self):
        """Should read strategy from env var."""
        STKAI.reset()
        self.assertEqual(STKAI.config.rate_limit.strategy, "adaptive")

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_MAX_REQUESTS": "50"})
    def test_max_requests_env_var(self):
        """Should read max_requests from env var."""
        STKAI.reset()
        self.assertEqual(STKAI.config.rate_limit.max_requests, 50)

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_TIME_WINDOW": "120.5"})
    def test_time_window_env_var(self):
        """Should read time_window from env var."""
        STKAI.reset()
        self.assertEqual(STKAI.config.rate_limit.time_window, 120.5)

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_MAX_WAIT_TIME": "30.0"})
    def test_max_wait_time_env_var(self):
        """Should read max_wait_time from env var."""
        STKAI.reset()
        self.assertEqual(STKAI.config.rate_limit.max_wait_time, 30.0)

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_MAX_WAIT_TIME": "none"})
    def test_max_wait_time_env_var_none(self):
        """Should read max_wait_time=None from env var."""
        STKAI.reset()
        self.assertIsNone(STKAI.config.rate_limit.max_wait_time)

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_MAX_WAIT_TIME": "unlimited"})
    def test_max_wait_time_env_var_unlimited(self):
        """Should read max_wait_time=unlimited as None from env var."""
        STKAI.reset()
        self.assertIsNone(STKAI.config.rate_limit.max_wait_time)

    @patch.dict(
        os.environ,
        {
            "STKAI_RATE_LIMIT_ENABLED": "true",
            "STKAI_RATE_LIMIT_STRATEGY": "adaptive",
            "STKAI_RATE_LIMIT_MAX_REQUESTS": "25",
            "STKAI_RATE_LIMIT_TIME_WINDOW": "30.0",
            "STKAI_RATE_LIMIT_MIN_RATE_FLOOR": "0.15",
            "STKAI_RATE_LIMIT_MAX_RETRIES_ON_429": "7",
            "STKAI_RATE_LIMIT_PENALTY_FACTOR": "0.25",
            "STKAI_RATE_LIMIT_RECOVERY_FACTOR": "0.05",
        },
    )
    def test_all_rate_limit_env_vars(self):
        """All rate limit env vars should be read correctly."""
        STKAI.reset()
        rl = STKAI.config.rate_limit
        self.assertTrue(rl.enabled)
        self.assertEqual(rl.strategy, "adaptive")
        self.assertEqual(rl.max_requests, 25)
        self.assertEqual(rl.time_window, 30.0)
        self.assertEqual(rl.min_rate_floor, 0.15)
        self.assertEqual(rl.max_retries_on_429, 7)
        self.assertEqual(rl.penalty_factor, 0.25)
        self.assertEqual(rl.recovery_factor, 0.05)

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_ENABLED": "true"})
    def test_configure_overrides_env_vars(self):
        """configure() values should take precedence over env vars."""
        STKAI.configure(rate_limit={"enabled": False}, allow_env_override=True)
        self.assertFalse(STKAI.config.rate_limit.enabled)  # configure wins

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_ENABLED": "true", "STKAI_RATE_LIMIT_MAX_REQUESTS": "50"})
    def test_env_vars_used_as_fallback(self):
        """Env vars should be used for fields NOT provided in configure()."""
        STKAI.configure(rate_limit={"enabled": False}, allow_env_override=True)
        self.assertFalse(STKAI.config.rate_limit.enabled)  # configure wins
        self.assertEqual(STKAI.config.rate_limit.max_requests, 50)  # env var fallback

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_ENABLED": "true"})
    def test_configure_without_env_override(self):
        """Configure values should win when allow_env_override=False."""
        STKAI.configure(rate_limit={"enabled": False}, allow_env_override=False)
        self.assertFalse(STKAI.config.rate_limit.enabled)


class TestRateLimitConfigImmutability(unittest.TestCase):
    """Tests for RateLimitConfig immutability (frozen=True)."""

    def test_rate_limit_config_is_frozen(self):
        """RateLimitConfig should be immutable."""
        config = RateLimitConfig()
        with self.assertRaises(AttributeError):
            config.enabled = True  # type: ignore

    def test_rate_limit_config_is_frozen_strategy(self):
        """RateLimitConfig.strategy should be immutable."""
        config = RateLimitConfig()
        with self.assertRaises(AttributeError):
            config.strategy = "adaptive"  # type: ignore


class TestRateLimitConfigReset(unittest.TestCase):
    """Tests for STKAI.reset() with rate limit config."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    def test_reset_clears_rate_limit_config(self):
        """STKAI.reset() should restore rate limit defaults."""
        STKAI.configure(
            rate_limit={
                "enabled": True,
                "strategy": "adaptive",
                "max_requests": 999,
            }
        )
        STKAI.reset()
        self.assertFalse(STKAI.config.rate_limit.enabled)
        self.assertEqual(STKAI.config.rate_limit.strategy, "token_bucket")
        self.assertEqual(STKAI.config.rate_limit.max_requests, 100)


if __name__ == "__main__":
    unittest.main()
