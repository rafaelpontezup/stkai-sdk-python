"""Tests for global configuration module."""

import os
import unittest
from dataclasses import asdict
from unittest.mock import patch

from stkai._config import (
    STKAI,
    AgentConfig,
    AuthConfig,
    ConfigEntry,
    ConfigValidationError,
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
        self.assertEqual(STKAI.config.rqc.retry_max_retries, 3)
        self.assertEqual(STKAI.config.rqc.retry_initial_delay, 0.5)
        self.assertEqual(STKAI.config.rqc.poll_interval, 10.0)
        self.assertEqual(STKAI.config.rqc.poll_max_duration, 600.0)
        self.assertEqual(STKAI.config.rqc.poll_overload_timeout, 60.0)
        self.assertEqual(STKAI.config.rqc.max_workers, 8)
        self.assertEqual(STKAI.config.rqc.base_url, "https://genai-code-buddy-api.stackspot.com")

    def test_agent_defaults(self):
        """Should return sensible defaults for Agent config."""
        self.assertEqual(STKAI.config.agent.base_url, "https://genai-inference-app.stackspot.com")
        self.assertEqual(STKAI.config.agent.request_timeout, 60)

    def test_auth_defaults(self):
        """Should return None for auth credentials when not userd."""
        self.assertIsNone(STKAI.config.auth.client_id)
        self.assertIsNone(STKAI.config.auth.client_secret)

    def test_has_credentials_false_by_default(self):
        """Should return False when no credentials userd."""
        self.assertFalse(STKAI.config.auth.has_credentials())


class TestSTKAIConfigure(unittest.TestCase):
    """Tests for STKAI.configure() method."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    def test_user_rqc_values(self):
        """Should override RQC defaults with STKAI.configure()."""
        STKAI.configure(rqc={"request_timeout": 60, "retry_max_retries": 10})
        self.assertEqual(STKAI.config.rqc.request_timeout, 60)
        self.assertEqual(STKAI.config.rqc.retry_max_retries, 10)
        # Other values should remain default
        self.assertEqual(STKAI.config.rqc.poll_interval, 10.0)

    def test_user_agent_values(self):
        """Should override Agent defaults with STKAI.configure()."""
        STKAI.configure(agent={"request_timeout": 120})
        self.assertEqual(STKAI.config.agent.request_timeout, 120)
        # Base URL should remain default
        self.assertEqual(STKAI.config.agent.base_url, "https://genai-inference-app.stackspot.com")

    def test_user_auth_values(self):
        """Should set auth credentials via STKAI.configure()."""
        STKAI.configure(auth={"client_id": "my-id", "client_secret": "my-secret"})
        self.assertEqual(STKAI.config.auth.client_id, "my-id")
        self.assertEqual(STKAI.config.auth.client_secret, "my-secret")
        self.assertTrue(STKAI.config.auth.has_credentials())

    def test_user_partial_auth(self):
        """Should handle partial auth credentials."""
        STKAI.configure(auth={"client_id": "my-id"})
        self.assertFalse(STKAI.config.auth.has_credentials())  # Need both

    def test_user_returns_instance(self):
        """Should return the userd STKAIConfig instance."""
        result = STKAI.configure(rqc={"request_timeout": 60})
        self.assertIsInstance(result, STKAIConfig)
        self.assertEqual(result.rqc.request_timeout, 60)
        # STKAI.config should return same values
        self.assertEqual(STKAI.config.rqc.request_timeout, 60)

    def test_user_isolation_between_rqc_and_agent(self):
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

    @patch.dict(os.environ, {"STKAI_RQC_RETRY_MAX_RETRIES": "7"})
    def test_rqc_env_var_int_conversion(self):
        """Should convert env var string to int."""
        STKAI.reset()
        self.assertEqual(STKAI.config.rqc.retry_max_retries, 7)

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
    def test_user_overrides_env_vars(self):
        """user() values should take precedence over env vars."""
        STKAI.configure(rqc={"request_timeout": 90}, allow_env_override=True)
        self.assertEqual(STKAI.config.rqc.request_timeout, 90)  # user wins

    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "45", "STKAI_RQC_RETRY_MAX_RETRIES": "7"})
    def test_env_vars_used_as_fallback(self):
        """Env vars should be used for fields NOT provided in user()."""
        STKAI.configure(rqc={"request_timeout": 90}, allow_env_override=True)
        self.assertEqual(STKAI.config.rqc.request_timeout, 90)  # user wins
        self.assertEqual(STKAI.config.rqc.retry_max_retries, 7)  # env var fallback

    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "45"})
    def test_user_without_env_override(self):
        """STKAI.configure() values should win when allow_env_override=False."""
        STKAI.configure(rqc={"request_timeout": 90}, allow_env_override=False)
        self.assertEqual(STKAI.config.rqc.request_timeout, 90)  # user wins


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
            "STKAI_RQC_RETRY_MAX_RETRIES": "5",
            "STKAI_RQC_RETRY_INITIAL_DELAY": "1.0",
            "STKAI_RQC_POLL_INTERVAL": "20.0",
            "STKAI_RQC_POLL_MAX_DURATION": "900.0",
            "STKAI_RQC_POLL_OVERLOAD_TIMEOUT": "120.0",
            "STKAI_RQC_MAX_WORKERS": "16",
        },
    )
    def test_all_rqc_env_vars(self):
        """All RQC env vars should be read correctly."""
        STKAI.reset()
        self.assertEqual(STKAI.config.rqc.base_url, "https://rqc.custom")
        self.assertEqual(STKAI.config.rqc.request_timeout, 100)
        self.assertEqual(STKAI.config.rqc.retry_max_retries, 5)
        self.assertEqual(STKAI.config.rqc.retry_initial_delay, 1.0)
        self.assertEqual(STKAI.config.rqc.poll_interval, 20.0)
        self.assertEqual(STKAI.config.rqc.poll_max_duration, 900.0)
        self.assertEqual(STKAI.config.rqc.poll_overload_timeout, 120.0)
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
        self.assertEqual(config.retry_max_retries, 3)  # unchanged

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
        self.assertEqual(rl.max_wait_time, 30.0)
        self.assertEqual(rl.min_rate_floor, 0.1)
        self.assertEqual(rl.penalty_factor, 0.3)
        self.assertEqual(rl.recovery_factor, 0.05)


class TestRateLimitConfigPresets(unittest.TestCase):
    """Tests for RateLimitConfig preset methods."""

    def test_conservative_preset_default_values(self):
        """Conservative preset should have stability-focused defaults."""
        config = RateLimitConfig.conservative_preset()

        self.assertTrue(config.enabled)
        self.assertEqual(config.strategy, "adaptive")
        self.assertEqual(config.max_requests, 20)
        self.assertEqual(config.time_window, 60.0)
        self.assertEqual(config.max_wait_time, 120.0)
        self.assertEqual(config.min_rate_floor, 0.05)
        self.assertEqual(config.penalty_factor, 0.5)
        self.assertEqual(config.recovery_factor, 0.02)

    def test_conservative_preset_custom_values(self):
        """Conservative preset should accept custom max_requests and time_window."""
        config = RateLimitConfig.conservative_preset(max_requests=50, time_window=30.0)

        self.assertEqual(config.max_requests, 50)
        self.assertEqual(config.time_window, 30.0)
        # Other values should remain preset defaults
        self.assertEqual(config.max_wait_time, 120.0)
        self.assertEqual(config.penalty_factor, 0.5)

    def test_balanced_preset_default_values(self):
        """Balanced preset should have sensible middle-ground defaults."""
        config = RateLimitConfig.balanced_preset()

        self.assertTrue(config.enabled)
        self.assertEqual(config.strategy, "adaptive")
        self.assertEqual(config.max_requests, 40)
        self.assertEqual(config.time_window, 60.0)
        self.assertEqual(config.max_wait_time, 30.0)
        self.assertEqual(config.min_rate_floor, 0.1)
        self.assertEqual(config.penalty_factor, 0.3)
        self.assertEqual(config.recovery_factor, 0.05)

    def test_balanced_preset_custom_values(self):
        """Balanced preset should accept custom max_requests and time_window."""
        config = RateLimitConfig.balanced_preset(max_requests=100, time_window=120.0)

        self.assertEqual(config.max_requests, 100)
        self.assertEqual(config.time_window, 120.0)
        # Other values should remain preset defaults
        self.assertEqual(config.max_wait_time, 30.0)
        self.assertEqual(config.penalty_factor, 0.3)

    def test_optimistic_preset_default_values(self):
        """Optimistic preset should have throughput-focused defaults."""
        config = RateLimitConfig.optimistic_preset()

        self.assertTrue(config.enabled)
        self.assertEqual(config.strategy, "adaptive")
        self.assertEqual(config.max_requests, 80)
        self.assertEqual(config.time_window, 60.0)
        self.assertEqual(config.max_wait_time, 5.0)
        self.assertEqual(config.min_rate_floor, 0.3)
        self.assertEqual(config.penalty_factor, 0.15)
        self.assertEqual(config.recovery_factor, 0.1)

    def test_optimistic_preset_custom_values(self):
        """Optimistic preset should accept custom max_requests and time_window."""
        config = RateLimitConfig.optimistic_preset(max_requests=150, time_window=60.0)

        self.assertEqual(config.max_requests, 150)
        self.assertEqual(config.time_window, 60.0)
        # Other values should remain preset defaults
        self.assertEqual(config.max_wait_time, 5.0)
        self.assertEqual(config.penalty_factor, 0.15)

    def test_presets_can_be_used_with_configure(self):
        """Presets should work seamlessly with STKAI.configure() via asdict()."""
        STKAI.reset()

        # Configure using a preset (convert to dict with asdict)
        preset = RateLimitConfig.balanced_preset(max_requests=50)
        STKAI.configure(rate_limit=asdict(preset))

        rl = STKAI.config.rate_limit
        self.assertTrue(rl.enabled)
        self.assertEqual(rl.strategy, "adaptive")
        self.assertEqual(rl.max_requests, 50)
        self.assertEqual(rl.max_wait_time, 30.0)

        STKAI.reset()

    def test_presets_are_valid_configs(self):
        """All presets should pass validation."""
        # Should not raise
        RateLimitConfig.conservative_preset().validate()
        RateLimitConfig.balanced_preset().validate()
        RateLimitConfig.optimistic_preset().validate()


class TestRateLimitConfigure(unittest.TestCase):
    """Tests for configuring rate limiting via STKAI.configure()."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    def test_user_rate_limit_enabled(self):
        """Should enable rate limiting via user()."""
        STKAI.configure(rate_limit={"enabled": True})
        self.assertTrue(STKAI.config.rate_limit.enabled)

    def test_user_rate_limit_strategy(self):
        """Should set strategy via user()."""
        STKAI.configure(rate_limit={"strategy": "adaptive"})
        self.assertEqual(STKAI.config.rate_limit.strategy, "adaptive")

    def test_user_rate_limit_token_bucket(self):
        """Should user token_bucket strategy."""
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

    def test_user_rate_limit_adaptive(self):
        """Should user adaptive strategy with all parameters."""
        STKAI.configure(
            rate_limit={
                "enabled": True,
                "strategy": "adaptive",
                "max_requests": 50,
                "time_window": 120.0,
                "max_wait_time": 30.0,
                "min_rate_floor": 0.2,
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
        self.assertEqual(rl.penalty_factor, 0.3)
        self.assertEqual(rl.recovery_factor, 0.02)

    def test_user_rate_limit_max_wait_time_none(self):
        """Should allow None for max_wait_time (unlimited wait)."""
        STKAI.configure(rate_limit={"max_wait_time": None})
        self.assertIsNone(STKAI.config.rate_limit.max_wait_time)

    def test_user_rate_limit_invalid_field_raises_error(self):
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
        self.assertEqual(rl.penalty_factor, 0.25)
        self.assertEqual(rl.recovery_factor, 0.05)

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_ENABLED": "true"})
    def test_user_overrides_env_vars(self):
        """user() values should take precedence over env vars."""
        STKAI.configure(rate_limit={"enabled": False}, allow_env_override=True)
        self.assertFalse(STKAI.config.rate_limit.enabled)  # user wins

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_ENABLED": "true", "STKAI_RATE_LIMIT_MAX_REQUESTS": "50"})
    def test_env_vars_used_as_fallback(self):
        """Env vars should be used for fields NOT provided in user()."""
        STKAI.configure(rate_limit={"enabled": False}, allow_env_override=True)
        self.assertFalse(STKAI.config.rate_limit.enabled)  # user wins
        self.assertEqual(STKAI.config.rate_limit.max_requests, 50)  # env var fallback

    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_ENABLED": "true"})
    def test_user_without_env_override(self):
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


class TestCLIPrecedence(unittest.TestCase):
    """Tests for CLI value precedence in configuration."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    def test_cli_base_url_overrides_hardcoded_default(self, mock_codebuddy, mock_inference):
        """CLI base_url should override hardcoded default."""
        STKAI.reset()
        self.assertEqual(STKAI.config.rqc.base_url, "https://cli.example.com")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    @patch.dict(os.environ, {"STKAI_RQC_BASE_URL": "https://env.example.com"})
    def test_cli_base_url_overrides_env_var(self, mock_codebuddy, mock_inference):
        """CLI base_url should override env var."""
        STKAI.reset()
        self.assertEqual(STKAI.config.rqc.base_url, "https://cli.example.com")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    @patch.dict(os.environ, {"STKAI_RQC_BASE_URL": "https://env.example.com"})
    def test_user_overrides_cli_base_url(self, mock_codebuddy, mock_inference):
        """STKAI.configure() should override CLI base_url."""
        STKAI.configure(rqc={"base_url": "https://user.example.com"})
        self.assertEqual(STKAI.config.rqc.base_url, "https://user.example.com")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_hardcoded_default_used_when_no_cli(self, mock_codebuddy, mock_inference):
        """Should use hardcoded default when CLI is not available."""
        STKAI.reset()
        self.assertEqual(STKAI.config.rqc.base_url, "https://genai-code-buddy-api.stackspot.com")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    @patch.dict(os.environ, {"STKAI_RQC_BASE_URL": "https://env.example.com"})
    def test_env_var_used_when_no_cli(self, mock_codebuddy, mock_inference):
        """Should use env var when CLI is not available."""
        STKAI.reset()
        self.assertEqual(STKAI.config.rqc.base_url, "https://env.example.com")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    def test_cli_preserves_other_rqc_defaults(self, mock_codebuddy, mock_inference):
        """CLI should only override base_url, not other RQC defaults."""
        STKAI.reset()
        self.assertEqual(STKAI.config.rqc.base_url, "https://cli.example.com")
        self.assertEqual(STKAI.config.rqc.request_timeout, 30)  # Default preserved
        self.assertEqual(STKAI.config.rqc.retry_max_retries, 3)  # Default preserved

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    def test_allow_cli_override_false_ignores_cli(self, mock_codebuddy, mock_inference):
        """allow_cli_override=False should ignore CLI values."""
        STKAI.configure(allow_cli_override=False)
        self.assertEqual(STKAI.config.rqc.base_url, "https://genai-code-buddy-api.stackspot.com")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    @patch.dict(os.environ, {"STKAI_RQC_BASE_URL": "https://env.example.com"})
    def test_allow_cli_override_false_uses_env_var(self, mock_codebuddy, mock_inference):
        """allow_cli_override=False should use env var instead of CLI."""
        STKAI.configure(allow_cli_override=False)
        self.assertEqual(STKAI.config.rqc.base_url, "https://env.example.com")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    @patch.dict(os.environ, {"STKAI_RQC_BASE_URL": "https://env.example.com"})
    def test_both_overrides_false_uses_defaults(self, mock_codebuddy, mock_inference):
        """Both overrides False should use only defaults."""
        STKAI.configure(allow_env_override=False, allow_cli_override=False)
        self.assertEqual(STKAI.config.rqc.base_url, "https://genai-code-buddy-api.stackspot.com")


class TestWithCliDefaults(unittest.TestCase):
    """Tests for STKAIConfig.with_cli_defaults() method."""

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    def test_applies_cli_base_url_to_rqc(self, mock_codebuddy, mock_inference):
        """Should apply CLI base_url to RQC config."""
        config = STKAIConfig().with_cli_defaults()
        self.assertEqual(config.rqc.base_url, "https://cli.example.com")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value="https://genai-inference-app.stackspot.com")
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_applies_cli_base_url_to_agent(self, mock_codebuddy, mock_inference):
        """Should apply CLI base_url to Agent config."""
        config = STKAIConfig().with_cli_defaults()
        self.assertEqual(config.agent.base_url, "https://genai-inference-app.stackspot.com")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value="https://genai-inference-app.stackspot.com")
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://genai-code-buddy-api.stackspot.com")
    def test_applies_cli_base_url_to_both_rqc_and_agent(self, mock_codebuddy, mock_inference):
        """Should apply CLI base_url to both RQC and Agent configs."""
        config = STKAIConfig().with_cli_defaults()
        self.assertEqual(config.rqc.base_url, "https://genai-code-buddy-api.stackspot.com")
        self.assertEqual(config.agent.base_url, "https://genai-inference-app.stackspot.com")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    def test_preserves_other_rqc_defaults(self, mock_codebuddy, mock_inference):
        """Should preserve other RQC default values."""
        config = STKAIConfig().with_cli_defaults()
        self.assertEqual(config.rqc.request_timeout, 30)
        self.assertEqual(config.rqc.retry_max_retries, 3)

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value="https://genai-inference-app.stackspot.com")
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_preserves_other_agent_defaults(self, mock_codebuddy, mock_inference):
        """Should preserve other Agent default values."""
        config = STKAIConfig().with_cli_defaults()
        self.assertEqual(config.agent.request_timeout, 60)

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_no_op_when_cli_not_available(self, mock_codebuddy, mock_inference):
        """Should be a no-op when CLI is not available."""
        original = STKAIConfig()
        result = original.with_cli_defaults()
        self.assertEqual(result.rqc.base_url, original.rqc.base_url)
        self.assertEqual(result.agent.base_url, original.agent.base_url)

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value="https://genai-inference-app.stackspot.com")
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    def test_returns_new_instance(self, mock_codebuddy, mock_inference):
        """Should return a new instance, not modify original."""
        original = STKAIConfig()
        result = original.with_cli_defaults()
        self.assertIsNot(original, result)
        self.assertEqual(original.rqc.base_url, "https://genai-code-buddy-api.stackspot.com")
        self.assertEqual(result.rqc.base_url, "https://cli.example.com")
        self.assertEqual(original.agent.base_url, "https://genai-inference-app.stackspot.com")
        self.assertEqual(result.agent.base_url, "https://genai-inference-app.stackspot.com")


class TestSourceTracking(unittest.TestCase):
    """Tests for _tracker.sources tracking in STKAIConfig."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    def test_defaults_have_emptysources(self):
        """Default config should have empty _tracker.sources."""
        config = STKAIConfig()
        self.assertEqual(config._tracker.sources, {})

    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "99"})
    def test_env_vars_tracked_insources(self):
        """Env vars should be tracked in _tracker.sources."""
        config = STKAIConfig().with_env_vars()
        self.assertIn("rqc", config._tracker.sources)
        self.assertEqual(config._tracker.sources["rqc"]["request_timeout"], "env:STKAI_RQC_REQUEST_TIMEOUT")

    @patch.dict(os.environ, {"STKAI_AUTH_CLIENT_SECRET": "secret123"})
    def test_auth_env_vars_tracked_insources(self):
        """Auth env vars should be tracked in _tracker.sources."""
        config = STKAIConfig().with_env_vars()
        self.assertIn("auth", config._tracker.sources)
        self.assertEqual(config._tracker.sources["auth"]["client_secret"], "env:STKAI_AUTH_CLIENT_SECRET")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value="https://genai-inference-app.example.com")
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    def test_cli_values_tracked_insources(self, mock_codebuddy, mock_inference):
        """CLI values should be tracked in _tracker.sources."""
        config = STKAIConfig().with_cli_defaults()
        self.assertIn("rqc", config._tracker.sources)
        self.assertEqual(config._tracker.sources["rqc"]["base_url"], "CLI")
        self.assertIn("agent", config._tracker.sources)
        self.assertEqual(config._tracker.sources["agent"]["base_url"], "CLI")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_user_values_tracked_insources(self, mock_codebuddy, mock_inference):
        """Configure values should be tracked in _tracker.sources."""
        STKAI.configure(rqc={"request_timeout": 120}, allow_env_override=False)
        # Access via internal _config._tracker
        self.assertIn("rqc", STKAI.config._tracker.sources)
        self.assertEqual(STKAI.config._tracker.sources["rqc"]["request_timeout"], "user")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value="https://genai-inference-app.example.com")
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "99"})
    def test_user_overrides_cli_and_env_insources(self, mock_codebuddy, mock_inference):
        """Configure values should override CLI and env in _tracker.sources."""
        STKAI.configure(rqc={"request_timeout": 120, "base_url": "https://custom.com"})
        sources = STKAI.config._tracker.sources
        # Configure should win for all fields it sets
        self.assertEqual(sources["rqc"]["request_timeout"], "user")
        self.assertEqual(sources["rqc"]["base_url"], "user")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value="https://genai-inference-app.example.com")
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    @patch.dict(os.environ, {"STKAI_RQC_RETRY_MAX_RETRIES": "10"})
    def testsources_from_multiple_origins(self, mock_codebuddy, mock_inference):
        """Sources should track multiple origins correctly."""
        STKAI.configure(rqc={"request_timeout": 120})
        sources = STKAI.config._tracker.sources
        # CLI provides base_url for rqc and agent
        self.assertEqual(sources["rqc"]["base_url"], "CLI")
        self.assertEqual(sources["agent"]["base_url"], "CLI")
        # Env var provides retry_max_retries
        self.assertEqual(sources["rqc"]["retry_max_retries"], "env:STKAI_RQC_RETRY_MAX_RETRIES")
        # Configure provides request_timeout
        self.assertEqual(sources["rqc"]["request_timeout"], "user")


class TestExplain(unittest.TestCase):
    """Tests for STKAI.explain() method."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    def _capture_explain(self) -> str:
        """Capture explain() output and print it to console for debugging."""
        import io
        import sys

        captured = io.StringIO()
        sys.stdout = captured
        try:
            STKAI.explain()
        finally:
            sys.stdout = sys.__stdout__

        output = captured.getvalue()
        print(output)  # Print to console for visibility
        return output

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_explain_prints_output(self, mock_codebuddy, mock_inference):
        """explain() should print configuration output."""
        STKAI.configure(allow_env_override=False, allow_cli_override=False)
        output = self._capture_explain()
        self.assertIn("STKAI Configuration:", output)
        self.assertIn("[auth]", output)
        self.assertIn("[rqc]", output)
        self.assertIn("[agent]", output)
        self.assertIn("[rate_limit]", output)

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_explain_shows_default_source(self, mock_codebuddy, mock_inference):
        """explain() should show 'default' for default values (without marker)."""
        STKAI.configure(allow_env_override=False, allow_cli_override=False)
        output = self._capture_explain()
        self.assertIn("  default", output)  # space before default (no ✎ marker)

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_explain_shows_user_source(self, mock_codebuddy, mock_inference):
        """explain() should show '✎ user' for userd values."""
        STKAI.configure(
            rqc={"request_timeout": 99},
            allow_env_override=False,
            allow_cli_override=False,
        )
        output = self._capture_explain()
        self.assertIn("99", output)
        self.assertIn("✎ user", output)

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    def test_explain_shows_cli_source(self, mock_codebuddy, mock_inference):
        """explain() should show '✎ CLI' for CLI values."""
        STKAI.reset()
        output = self._capture_explain()
        self.assertIn("https://cli.example.com", output)
        self.assertIn("✎ CLI", output)

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    @patch.dict(os.environ, {"STKAI_RQC_RETRY_MAX_RETRIES": "15"})
    def test_explain_shows_env_source(self, mock_codebuddy, mock_inference):
        """explain() should show '✎ env:VAR_NAME' for env values."""
        STKAI.reset()
        output = self._capture_explain()
        self.assertIn("15", output)
        self.assertIn("✎ env:STKAI_RQC_RETRY_MAX_RETRIES", output)

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_explain_masks_client_secret(self, mock_codebuddy, mock_inference):
        """explain() should mask client_secret value."""
        STKAI.configure(
            auth={"client_secret": "super-secret-value"},
            allow_env_override=False,
            allow_cli_override=False,
        )
        output = self._capture_explain()
        self.assertNotIn("super-secret-value", output)
        self.assertIn("********", output)

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_explain_shows_none_values(self, mock_codebuddy, mock_inference):
        """explain() should show 'None' for None values."""
        STKAI.configure(allow_env_override=False, allow_cli_override=False)
        output = self._capture_explain()
        # client_id should be None by default
        self.assertIn("client_id", output)
        self.assertIn("None", output)

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_explain_with_custom_output_handler(self, mock_codebuddy, mock_inference):
        """explain() should accept custom output handler."""
        STKAI.configure(allow_env_override=False, allow_cli_override=False)

        # Capture output using a custom handler
        lines: list[str] = []
        STKAI.explain(output=lines.append)

        # Print for visibility
        for line in lines:
            print(line)

        # Verify output was captured
        self.assertTrue(any("STKAI Configuration:" in line for line in lines))
        self.assertTrue(any("[rqc]" in line for line in lines))

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://cli.example.com")
    @patch.dict(os.environ, {"STKAI_RQC_RETRY_MAX_RETRIES": "10", "STKAI_AGENT_REQUEST_TIMEOUT": "90"})
    def test_explain_shows_mixed_sources(self, mock_codebuddy, mock_inference):
        """explain() should show mix of default, env, CLI, and user sources."""
        STKAI.configure(
            rqc={"request_timeout": 99},  # user overrides default
            # retry_max_retries comes from env (10)
            # base_url comes from CLI (https://cli.example.com)
            # poll_interval stays default
        )
        output = self._capture_explain()

        # Verify all source types are present (✎ marker for non-default)
        self.assertIn("  default", output)  # no marker for default
        self.assertIn("✎ env:STKAI_RQC_RETRY_MAX_RETRIES", output)
        self.assertIn("✎ env:STKAI_AGENT_REQUEST_TIMEOUT", output)
        self.assertIn("✎ CLI", output)
        self.assertIn("✎ user", output)

        # Verify specific values
        self.assertIn("99", output)  # request_timeout from user
        self.assertIn("10", output)  # retry_max_retries from env
        self.assertIn("https://cli.example.com", output)  # base_url from CLI
        self.assertIn("10.0", output)  # poll_interval from default

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_explain_with_logger(self, mock_codebuddy, mock_inference):
        """explain() should work with logging."""
        import logging

        STKAI.configure(allow_env_override=False, allow_cli_override=False)

        # Capture log output
        log_messages: list[str] = []
        handler = logging.Handler()
        handler.emit = lambda record: log_messages.append(record.getMessage())  # type: ignore

        logger = logging.getLogger("test_explain")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        STKAI.explain(output=logger.info)

        # Print for visibility
        for msg in log_messages:
            print(msg)

        # Verify log messages were captured
        self.assertTrue(any("STKAI Configuration:" in msg for msg in log_messages))


class TestConfigEntryFormattedValue(unittest.TestCase):
    """Tests for ConfigEntry.formatted_value property."""

    # -------------------------------------------------------------------------
    # Secret masking: long secrets (>=12 chars) - show first 4 and last 4
    # -------------------------------------------------------------------------

    def test_long_secret_shows_first_and_last_four_chars(self):
        """Long secrets (>=12 chars) should show first 4 and last 4 chars."""
        entry = ConfigEntry("client_secret", "super-secret-value", "user")
        self.assertEqual(entry.formatted_value, "supe********alue")

    def test_secret_exactly_12_chars_shows_first_and_last_four(self):
        """Secret with exactly 12 chars should show first 4 and last 4."""
        entry = ConfigEntry("client_secret", "123456789012", "user")
        self.assertEqual(entry.formatted_value, "1234********9012")

    def test_long_secret_with_special_chars(self):
        """Long secrets with special characters should be masked correctly."""
        entry = ConfigEntry("client_secret", "abc!@#$%^&*()xyz", "user")
        self.assertEqual(entry.formatted_value, "abc!********)xyz")

    # -------------------------------------------------------------------------
    # Secret masking: short secrets (3-11 chars) - show last 1/3
    # -------------------------------------------------------------------------

    def test_short_secret_11_chars_shows_last_third(self):
        """11-char secret should show last 3 chars (11//3=3)."""
        entry = ConfigEntry("client_secret", "12345678901", "user")
        self.assertEqual(entry.formatted_value, "********901")

    def test_short_secret_9_chars_shows_last_third(self):
        """9-char secret should show last 3 chars (9//3=3)."""
        entry = ConfigEntry("client_secret", "123456789", "user")
        self.assertEqual(entry.formatted_value, "********789")

    def test_short_secret_6_chars_shows_last_third(self):
        """6-char secret should show last 2 chars (6//3=2)."""
        entry = ConfigEntry("client_secret", "123456", "user")
        self.assertEqual(entry.formatted_value, "********56")

    def test_short_secret_5_chars_shows_last_one(self):
        """5-char secret should show last 1 char (5//3=1)."""
        entry = ConfigEntry("client_secret", "12345", "user")
        self.assertEqual(entry.formatted_value, "********5")

    def test_short_secret_3_chars_shows_last_one(self):
        """3-char secret should show last 1 char (3//3=1)."""
        entry = ConfigEntry("client_secret", "abc", "user")
        self.assertEqual(entry.formatted_value, "********c")

    # -------------------------------------------------------------------------
    # Secret masking: very short secrets (<3 chars) - fully masked
    # -------------------------------------------------------------------------

    def test_very_short_secret_2_chars_fully_masked(self):
        """2-char secret should be fully masked."""
        entry = ConfigEntry("client_secret", "ab", "user")
        self.assertEqual(entry.formatted_value, "********")

    def test_very_short_secret_1_char_fully_masked(self):
        """1-char secret should be fully masked."""
        entry = ConfigEntry("client_secret", "a", "user")
        self.assertEqual(entry.formatted_value, "********")

    def test_empty_secret_fully_masked(self):
        """Empty secret should be fully masked."""
        entry = ConfigEntry("client_secret", "", "user")
        self.assertEqual(entry.formatted_value, "********")

    # -------------------------------------------------------------------------
    # Secret masking: None value
    # -------------------------------------------------------------------------

    def test_secret_none_value_shows_none(self):
        """None secret should show 'None', not masked."""
        entry = ConfigEntry("client_secret", None, "user")
        self.assertEqual(entry.formatted_value, "None")

    # -------------------------------------------------------------------------
    # None handling for non-secret fields
    # -------------------------------------------------------------------------

    def test_none_value_returns_none_string(self):
        """None values should return 'None' string."""
        entry = ConfigEntry("client_id", None, "default")
        self.assertEqual(entry.formatted_value, "None")

    def test_none_value_for_any_field(self):
        """None should return 'None' for any field."""
        entry = ConfigEntry("base_url", None, "default")
        self.assertEqual(entry.formatted_value, "None")

    # -------------------------------------------------------------------------
    # String truncation (>50 chars)
    # -------------------------------------------------------------------------

    def test_long_string_truncated_with_ellipsis(self):
        """Strings longer than 50 chars should be truncated with '...'."""
        long_url = "https://example.com/very/long/path/that/exceeds/fifty/characters/limit"
        entry = ConfigEntry("base_url", long_url, "default")
        self.assertEqual(len(entry.formatted_value), 50)
        self.assertTrue(entry.formatted_value.endswith("..."))
        self.assertEqual(entry.formatted_value, long_url[:47] + "...")

    def test_string_exactly_50_chars_not_truncated(self):
        """Strings with exactly 50 chars should not be truncated."""
        exact_50 = "a" * 50
        entry = ConfigEntry("base_url", exact_50, "default")
        self.assertEqual(entry.formatted_value, exact_50)
        self.assertFalse(entry.formatted_value.endswith("..."))

    def test_string_51_chars_truncated(self):
        """Strings with 51 chars should be truncated."""
        string_51 = "a" * 51
        entry = ConfigEntry("base_url", string_51, "default")
        self.assertEqual(entry.formatted_value, "a" * 47 + "...")

    def test_short_string_not_truncated(self):
        """Short strings should not be truncated."""
        entry = ConfigEntry("base_url", "https://example.com", "default")
        self.assertEqual(entry.formatted_value, "https://example.com")

    # -------------------------------------------------------------------------
    # Normal values (no masking, no truncation)
    # -------------------------------------------------------------------------

    def test_integer_value(self):
        """Integer values should be converted to string."""
        entry = ConfigEntry("request_timeout", 30, "default")
        self.assertEqual(entry.formatted_value, "30")

    def test_float_value(self):
        """Float values should be converted to string."""
        entry = ConfigEntry("poll_interval", 10.5, "default")
        self.assertEqual(entry.formatted_value, "10.5")

    def test_boolean_true_value(self):
        """Boolean True should be converted to string."""
        entry = ConfigEntry("enabled", True, "user")
        self.assertEqual(entry.formatted_value, "True")

    def test_boolean_false_value(self):
        """Boolean False should be converted to string."""
        entry = ConfigEntry("enabled", False, "default")
        self.assertEqual(entry.formatted_value, "False")

    def test_regular_string_value(self):
        """Regular string values should be returned as-is."""
        entry = ConfigEntry("strategy", "token_bucket", "default")
        self.assertEqual(entry.formatted_value, "token_bucket")

    # -------------------------------------------------------------------------
    # Edge cases
    # -------------------------------------------------------------------------

    def test_non_secret_field_not_masked(self):
        """Non-secret fields should not be masked even if they look like secrets."""
        entry = ConfigEntry("client_id", "super-secret-looking-value", "user")
        self.assertEqual(entry.formatted_value, "super-secret-looking-value")

    def test_secret_with_numeric_value(self):
        """Secret with numeric value should be masked."""
        entry = ConfigEntry("client_secret", 123456789012, "user")
        self.assertEqual(entry.formatted_value, "1234********9012")


class TestConfigValidation(unittest.TestCase):
    """Tests for config field validation."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    # -------------------------------------------------------------------------
    # AuthConfig validation
    # -------------------------------------------------------------------------

    def test_auth_client_id_cannot_be_empty_string(self):
        """client_id cannot be empty string."""
        with self.assertRaises(ConfigValidationError) as ctx:
            AuthConfig(client_id="").validate()
        self.assertIn("client_id", str(ctx.exception))
        self.assertIn("empty string", str(ctx.exception))

    def test_auth_client_secret_cannot_be_empty_string(self):
        """client_secret cannot be empty string."""
        with self.assertRaises(ConfigValidationError) as ctx:
            AuthConfig(client_secret="").validate()
        self.assertIn("client_secret", str(ctx.exception))
        self.assertIn("empty string", str(ctx.exception))

    def test_auth_token_url_must_be_http(self):
        """token_url must start with http:// or https://."""
        with self.assertRaises(ConfigValidationError) as ctx:
            AuthConfig(token_url="ftp://invalid.url").validate()
        self.assertIn("token_url", str(ctx.exception))
        self.assertIn("http", str(ctx.exception))

    def test_auth_valid_config_passes(self):
        """Valid auth config should pass validation."""
        config = AuthConfig(
            client_id="my-id",
            client_secret="my-secret",
            token_url="https://auth.example.com/token"
        ).validate()
        self.assertEqual(config.client_id, "my-id")

    def test_auth_none_values_are_valid(self):
        """None values for client_id/secret are valid."""
        config = AuthConfig(client_id=None, client_secret=None).validate()
        self.assertIsNone(config.client_id)

    # -------------------------------------------------------------------------
    # RqcConfig validation
    # -------------------------------------------------------------------------

    def test_rqc_request_timeout_must_be_positive(self):
        """request_timeout must be > 0."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RqcConfig(request_timeout=0).validate()
        self.assertIn("request_timeout", str(ctx.exception))
        self.assertIn("greater than 0", str(ctx.exception))

    def test_rqc_request_timeout_negative(self):
        """request_timeout cannot be negative."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RqcConfig(request_timeout=-10).validate()
        self.assertIn("request_timeout", str(ctx.exception))

    def test_rqc_retry_max_retries_cannot_be_negative(self):
        """retry_max_retries must be >= 0."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RqcConfig(retry_max_retries=-1).validate()
        self.assertIn("retry_max_retries", str(ctx.exception))
        self.assertIn(">= 0", str(ctx.exception))

    def test_rqc_retry_max_retries_zero_is_valid(self):
        """retry_max_retries=0 is valid (no retries)."""
        config = RqcConfig(retry_max_retries=0).validate()
        self.assertEqual(config.retry_max_retries, 0)

    def test_rqc_retry_initial_delay_must_be_positive(self):
        """retry_initial_delay must be > 0."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RqcConfig(retry_initial_delay=0).validate()
        self.assertIn("retry_initial_delay", str(ctx.exception))

    def test_rqc_poll_interval_must_be_positive(self):
        """poll_interval must be > 0."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RqcConfig(poll_interval=-5.0).validate()
        self.assertIn("poll_interval", str(ctx.exception))

    def test_rqc_poll_max_duration_must_be_positive(self):
        """poll_max_duration must be > 0."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RqcConfig(poll_max_duration=0).validate()
        self.assertIn("poll_max_duration", str(ctx.exception))

    def test_rqc_poll_overload_timeout_must_be_positive(self):
        """poll_overload_timeout must be > 0."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RqcConfig(poll_overload_timeout=-1).validate()
        self.assertIn("poll_overload_timeout", str(ctx.exception))

    def test_rqc_max_workers_must_be_positive(self):
        """max_workers must be > 0."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RqcConfig(max_workers=0).validate()
        self.assertIn("max_workers", str(ctx.exception))

    def test_rqc_base_url_must_be_http(self):
        """base_url must start with http:// or https://."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RqcConfig(base_url="invalid-url").validate()
        self.assertIn("base_url", str(ctx.exception))
        self.assertIn("http", str(ctx.exception))

    def test_rqc_valid_config_passes(self):
        """Valid RQC config should pass validation."""
        config = RqcConfig().validate()
        self.assertEqual(config.request_timeout, 30)

    # -------------------------------------------------------------------------
    # AgentConfig validation
    # -------------------------------------------------------------------------

    def test_agent_request_timeout_must_be_positive(self):
        """request_timeout must be > 0."""
        with self.assertRaises(ConfigValidationError) as ctx:
            AgentConfig(request_timeout=0).validate()
        self.assertIn("request_timeout", str(ctx.exception))
        self.assertIn("greater than 0", str(ctx.exception))

    def test_agent_base_url_must_be_http(self):
        """base_url must start with http:// or https://."""
        with self.assertRaises(ConfigValidationError) as ctx:
            AgentConfig(base_url="ws://invalid").validate()
        self.assertIn("base_url", str(ctx.exception))
        self.assertIn("http", str(ctx.exception))

    def test_agent_valid_config_passes(self):
        """Valid Agent config should pass validation."""
        config = AgentConfig().validate()
        self.assertEqual(config.request_timeout, 60)

    # -------------------------------------------------------------------------
    # RateLimitConfig validation
    # -------------------------------------------------------------------------

    def test_rate_limit_strategy_must_be_valid(self):
        """strategy must be 'token_bucket' or 'adaptive'."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RateLimitConfig(strategy="invalid").validate()  # type: ignore
        self.assertIn("strategy", str(ctx.exception))
        self.assertIn("token_bucket", str(ctx.exception))
        self.assertIn("adaptive", str(ctx.exception))

    def test_rate_limit_max_requests_must_be_positive(self):
        """max_requests must be > 0."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RateLimitConfig(max_requests=0).validate()
        self.assertIn("max_requests", str(ctx.exception))

    def test_rate_limit_time_window_must_be_positive(self):
        """time_window must be > 0."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RateLimitConfig(time_window=-1.0).validate()
        self.assertIn("time_window", str(ctx.exception))

    def test_rate_limit_max_wait_time_must_be_positive_or_none(self):
        """max_wait_time must be > 0 or None."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RateLimitConfig(max_wait_time=0).validate()
        self.assertIn("max_wait_time", str(ctx.exception))

    def test_rate_limit_max_wait_time_none_is_valid(self):
        """max_wait_time=None is valid (unlimited)."""
        config = RateLimitConfig(max_wait_time=None).validate()
        self.assertIsNone(config.max_wait_time)

    def test_rate_limit_min_rate_floor_must_be_in_range(self):
        """min_rate_floor must be > 0 and <= 1."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RateLimitConfig(min_rate_floor=0).validate()
        self.assertIn("min_rate_floor", str(ctx.exception))

        with self.assertRaises(ConfigValidationError) as ctx:
            RateLimitConfig(min_rate_floor=1.5).validate()
        self.assertIn("min_rate_floor", str(ctx.exception))

    def test_rate_limit_min_rate_floor_one_is_valid(self):
        """min_rate_floor=1 is valid (edge case)."""
        config = RateLimitConfig(min_rate_floor=1.0).validate()
        self.assertEqual(config.min_rate_floor, 1.0)

    def test_rate_limit_penalty_factor_must_be_in_range(self):
        """penalty_factor must be > 0 and < 1."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RateLimitConfig(penalty_factor=0).validate()
        self.assertIn("penalty_factor", str(ctx.exception))

        with self.assertRaises(ConfigValidationError) as ctx:
            RateLimitConfig(penalty_factor=1.0).validate()
        self.assertIn("penalty_factor", str(ctx.exception))

    def test_rate_limit_recovery_factor_must_be_in_range(self):
        """recovery_factor must be > 0 and < 1."""
        with self.assertRaises(ConfigValidationError) as ctx:
            RateLimitConfig(recovery_factor=0).validate()
        self.assertIn("recovery_factor", str(ctx.exception))

        with self.assertRaises(ConfigValidationError) as ctx:
            RateLimitConfig(recovery_factor=1.0).validate()
        self.assertIn("recovery_factor", str(ctx.exception))

    def test_rate_limit_valid_config_passes(self):
        """Valid rate limit config should pass validation."""
        config = RateLimitConfig().validate()
        self.assertEqual(config.strategy, "token_bucket")

    # -------------------------------------------------------------------------
    # STKAI.configure() validation
    # -------------------------------------------------------------------------

    def test_configure_validates_rqc_values(self):
        """STKAI.configure() should validate RQC values."""
        with self.assertRaises(ConfigValidationError) as ctx:
            STKAI.configure(rqc={"request_timeout": -10})
        self.assertIn("request_timeout", str(ctx.exception))
        self.assertIn("[rqc]", str(ctx.exception))

    def test_configure_validates_agent_values(self):
        """STKAI.configure() should validate Agent values."""
        with self.assertRaises(ConfigValidationError) as ctx:
            STKAI.configure(agent={"request_timeout": 0})
        self.assertIn("request_timeout", str(ctx.exception))
        self.assertIn("[agent]", str(ctx.exception))

    def test_configure_validates_rate_limit_values(self):
        """STKAI.configure() should validate rate limit values."""
        with self.assertRaises(ConfigValidationError) as ctx:
            STKAI.configure(rate_limit={"strategy": "invalid"})
        self.assertIn("strategy", str(ctx.exception))
        self.assertIn("[rate_limit]", str(ctx.exception))

    def test_configure_validates_auth_values(self):
        """STKAI.configure() should validate auth values."""
        with self.assertRaises(ConfigValidationError) as ctx:
            STKAI.configure(auth={"token_url": "not-a-valid-url"})
        self.assertIn("token_url", str(ctx.exception))
        self.assertIn("[auth]", str(ctx.exception))

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_configure_valid_values_pass(self, mock_codebuddy, mock_inference):
        """STKAI.configure() with valid values should succeed."""
        result = STKAI.configure(
            rqc={"request_timeout": 60, "retry_max_retries": 5},
            agent={"request_timeout": 120},
            rate_limit={"enabled": True, "strategy": "adaptive", "max_requests": 50},
            allow_env_override=False,
            allow_cli_override=False,
        )
        self.assertEqual(result.rqc.request_timeout, 60)
        self.assertEqual(result.agent.request_timeout, 120)
        self.assertTrue(result.rate_limit.enabled)

    # -------------------------------------------------------------------------
    # ConfigValidationError attributes
    # -------------------------------------------------------------------------

    def test_config_validation_error_has_field_attribute(self):
        """ConfigValidationError should have field attribute."""
        try:
            RqcConfig(request_timeout=-1).validate()
        except ConfigValidationError as e:
            self.assertEqual(e.field, "request_timeout")
            self.assertEqual(e.value, -1)
            self.assertEqual(e.section, "rqc")

    def test_config_validation_error_message_format(self):
        """ConfigValidationError message should include section prefix."""
        try:
            RateLimitConfig(strategy="invalid").validate()  # type: ignore
        except ConfigValidationError as e:
            self.assertIn("[rate_limit]", str(e))
            self.assertIn("strategy", str(e))
            self.assertIn("'invalid'", str(e))


class TestSourceTrackingWithSameValue(unittest.TestCase):
    """Test source tracking when value is same across sources."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "30"})
    def test_env_var_same_as_default_shows_env_source(self, mock_codebuddy, mock_inference):
        """ENV var with same value as default should show env: source."""
        STKAI.reset()
        data = STKAI.config.explain_data()
        entry = next(e for e in data["rqc"] if e.name == "request_timeout")
        self.assertEqual(entry.source, "env:STKAI_RQC_REQUEST_TIMEOUT")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://genai-code-buddy-api.stackspot.com")
    def test_cli_same_as_default_shows_cli_source(self, mock_codebuddy, mock_inference):
        """CLI with same value as default should show CLI source."""
        STKAI.reset()
        data = STKAI.config.explain_data()
        entry = next(e for e in data["rqc"] if e.name == "base_url")
        self.assertEqual(entry.source, "CLI")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    @patch.dict(os.environ, {"STKAI_RQC_BASE_URL": "https://example.com"})
    def test_cli_same_as_env_shows_cli_source(self, mock_codebuddy, mock_inference):
        """CLI with same value as ENV var should show CLI source."""
        # Set CLI to return the same value as env
        mock_codebuddy.return_value = "https://example.com"
        STKAI.reset()
        data = STKAI.config.explain_data()
        entry = next(e for e in data["rqc"] if e.name == "base_url")
        self.assertEqual(entry.source, "CLI")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_configure_same_as_default_shows_user_source(self, mock_codebuddy, mock_inference):
        """configure() with same value as default should show user source."""
        STKAI.configure(
            rqc={"request_timeout": 30},  # 30 is the default
            allow_env_override=False,
            allow_cli_override=False,
        )
        data = STKAI.config.explain_data()
        entry = next(e for e in data["rqc"] if e.name == "request_timeout")
        self.assertEqual(entry.source, "user")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "60"})
    def test_configure_same_as_env_shows_user_source(self, mock_codebuddy, mock_inference):
        """configure() with same value as ENV var should show user source."""
        STKAI.configure(rqc={"request_timeout": 60})  # same as env
        data = STKAI.config.explain_data()
        entry = next(e for e in data["rqc"] if e.name == "request_timeout")
        self.assertEqual(entry.source, "user")  # user wins

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value="https://example.com")
    @patch.dict(os.environ, {"STKAI_RQC_BASE_URL": "https://example.com"})
    def test_configure_same_as_env_and_cli_shows_user_source(self, mock_codebuddy, mock_inference):
        """configure() with same value as ENV+CLI should show user source."""
        STKAI.configure(rqc={"base_url": "https://example.com"})  # same as env and CLI
        data = STKAI.config.explain_data()
        entry = next(e for e in data["rqc"] if e.name == "base_url")
        self.assertEqual(entry.source, "user")  # user wins

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    def test_configure_none_value_with_allow_none_shows_user_source(self, mock_codebuddy, mock_inference):
        """None value with allow_none_fields should show user source."""
        STKAI.configure(
            rate_limit={"max_wait_time": None},
            allow_env_override=False,
            allow_cli_override=False,
        )
        data = STKAI.config.explain_data()
        entry = next(e for e in data["rate_limit"] if e.name == "max_wait_time")
        self.assertEqual(entry.source, "user")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    @patch.dict(os.environ, {"STKAI_AUTH_TOKEN_URL": "https://idm.stackspot.com/stackspot-dev/oidc/oauth/token"})
    def test_auth_env_var_same_as_default_shows_env_source(self, mock_codebuddy, mock_inference):
        """Auth ENV var with same value as default should show env: source."""
        STKAI.reset()
        data = STKAI.config.explain_data()
        entry = next(e for e in data["auth"] if e.name == "token_url")
        self.assertEqual(entry.source, "env:STKAI_AUTH_TOKEN_URL")

    @patch("stkai._cli.StkCLI.get_inference_app_base_url", return_value=None)
    @patch("stkai._cli.StkCLI.get_codebuddy_base_url", return_value=None)
    @patch.dict(os.environ, {"STKAI_RATE_LIMIT_ENABLED": "false"})
    def test_rate_limit_env_var_same_as_default_shows_env_source(self, mock_codebuddy, mock_inference):
        """Rate limit ENV var with same value as default should show env: source."""
        STKAI.reset()
        data = STKAI.config.explain_data()
        entry = next(e for e in data["rate_limit"] if e.name == "enabled")
        self.assertEqual(entry.source, "env:STKAI_RATE_LIMIT_ENABLED")


if __name__ == "__main__":
    unittest.main()
