"""Tests for global configuration module."""

import os
import unittest
from unittest.mock import patch

from stkai._config import (
    STKAI_CONFIG,
    AgentConfig,
    AuthConfig,
    RqcConfig,
    StkAiConfig,
    configure_stkai,
    reset_stkai_config,
)


class TestDefaults(unittest.TestCase):
    """Tests for default configuration values."""

    def setUp(self):
        reset_stkai_config()

    def tearDown(self):
        reset_stkai_config()

    def test_rqc_defaults(self):
        """Should return sensible defaults for RQC config."""
        self.assertEqual(STKAI_CONFIG.rqc.request_timeout, 30)
        self.assertEqual(STKAI_CONFIG.rqc.max_retries, 3)
        self.assertEqual(STKAI_CONFIG.rqc.backoff_factor, 0.5)
        self.assertEqual(STKAI_CONFIG.rqc.poll_interval, 10.0)
        self.assertEqual(STKAI_CONFIG.rqc.poll_max_duration, 600.0)
        self.assertEqual(STKAI_CONFIG.rqc.overload_timeout, 60.0)
        self.assertEqual(STKAI_CONFIG.rqc.max_workers, 8)
        self.assertIsNone(STKAI_CONFIG.rqc.base_url)

    def test_agent_defaults(self):
        """Should return sensible defaults for Agent config."""
        self.assertEqual(STKAI_CONFIG.agent.base_url, "https://genai-inference-app.stackspot.com")
        self.assertEqual(STKAI_CONFIG.agent.request_timeout, 60)

    def test_auth_defaults(self):
        """Should return None for auth credentials when not configured."""
        self.assertIsNone(STKAI_CONFIG.auth.client_id)
        self.assertIsNone(STKAI_CONFIG.auth.client_secret)

    def test_has_credentials_false_by_default(self):
        """Should return False when no credentials configured."""
        self.assertFalse(STKAI_CONFIG.auth.has_credentials())


class TestConfigureStkai(unittest.TestCase):
    """Tests for configure_stkai() function."""

    def setUp(self):
        reset_stkai_config()

    def tearDown(self):
        reset_stkai_config()

    def test_configure_rqc_values(self):
        """Should override RQC defaults with configure_stkai()."""
        configure_stkai(rqc={"request_timeout": 60, "max_retries": 10})
        self.assertEqual(STKAI_CONFIG.rqc.request_timeout, 60)
        self.assertEqual(STKAI_CONFIG.rqc.max_retries, 10)
        # Other values should remain default
        self.assertEqual(STKAI_CONFIG.rqc.poll_interval, 10.0)

    def test_configure_agent_values(self):
        """Should override Agent defaults with configure_stkai()."""
        configure_stkai(agent={"request_timeout": 120})
        self.assertEqual(STKAI_CONFIG.agent.request_timeout, 120)
        # Base URL should remain default
        self.assertEqual(STKAI_CONFIG.agent.base_url, "https://genai-inference-app.stackspot.com")

    def test_configure_auth_values(self):
        """Should set auth credentials via configure_stkai()."""
        configure_stkai(auth={"client_id": "my-id", "client_secret": "my-secret"})
        self.assertEqual(STKAI_CONFIG.auth.client_id, "my-id")
        self.assertEqual(STKAI_CONFIG.auth.client_secret, "my-secret")
        self.assertTrue(STKAI_CONFIG.auth.has_credentials())

    def test_configure_partial_auth(self):
        """Should handle partial auth credentials."""
        configure_stkai(auth={"client_id": "my-id"})
        self.assertFalse(STKAI_CONFIG.auth.has_credentials())  # Need both

    def test_configure_returns_instance(self):
        """Should return the configured StkAiConfig instance."""
        result = configure_stkai(rqc={"request_timeout": 60})
        self.assertIsInstance(result, StkAiConfig)
        self.assertEqual(result.rqc.request_timeout, 60)
        # STKAI_CONFIG is a proxy, so check values match
        self.assertEqual(STKAI_CONFIG.rqc.request_timeout, 60)

    def test_configure_isolation_between_rqc_and_agent(self):
        """RQC config should not affect Agent config and vice versa."""
        configure_stkai(rqc={"request_timeout": 30}, agent={"request_timeout": 120})
        self.assertEqual(STKAI_CONFIG.rqc.request_timeout, 30)
        self.assertEqual(STKAI_CONFIG.agent.request_timeout, 120)


class TestEnvVars(unittest.TestCase):
    """Tests for environment variable override."""

    def setUp(self):
        reset_stkai_config()

    def tearDown(self):
        reset_stkai_config()

    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "45"})
    def test_rqc_env_var_override(self):
        """Should use env var value over defaults."""
        reset_stkai_config()  # Re-read env vars
        self.assertEqual(STKAI_CONFIG.rqc.request_timeout, 45)

    @patch.dict(os.environ, {"STKAI_RQC_MAX_RETRIES": "7"})
    def test_rqc_env_var_int_conversion(self):
        """Should convert env var string to int."""
        reset_stkai_config()
        self.assertEqual(STKAI_CONFIG.rqc.max_retries, 7)

    @patch.dict(os.environ, {"STKAI_RQC_POLL_INTERVAL": "15.5"})
    def test_rqc_env_var_float_conversion(self):
        """Should convert env var string to float."""
        reset_stkai_config()
        self.assertEqual(STKAI_CONFIG.rqc.poll_interval, 15.5)

    @patch.dict(os.environ, {"STKAI_AGENT_REQUEST_TIMEOUT": "180"})
    def test_agent_env_var_override(self):
        """Should use env var value for Agent config."""
        reset_stkai_config()
        self.assertEqual(STKAI_CONFIG.agent.request_timeout, 180)

    @patch.dict(os.environ, {"STKAI_AGENT_BASE_URL": "https://custom.url"})
    def test_agent_base_url_env_var(self):
        """Should use env var for Agent base_url."""
        reset_stkai_config()
        self.assertEqual(STKAI_CONFIG.agent.base_url, "https://custom.url")

    @patch.dict(os.environ, {"STKAI_AUTH_CLIENT_ID": "env-id", "STKAI_AUTH_CLIENT_SECRET": "env-secret"})
    def test_auth_from_env_vars(self):
        """Should read auth credentials from env vars."""
        reset_stkai_config()
        self.assertEqual(STKAI_CONFIG.auth.client_id, "env-id")
        self.assertEqual(STKAI_CONFIG.auth.client_secret, "env-secret")
        self.assertTrue(STKAI_CONFIG.auth.has_credentials())

    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "45"})
    def test_env_vars_override_configure_stkai(self):
        """env vars should take precedence over configure_stkai() when allow_env_override=True."""
        configure_stkai(rqc={"request_timeout": 90}, allow_env_override=True)
        self.assertEqual(STKAI_CONFIG.rqc.request_timeout, 45)  # env var wins

    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "45"})
    def test_configure_without_env_override(self):
        """configure_stkai() values should win when allow_env_override=False."""
        configure_stkai(rqc={"request_timeout": 90}, allow_env_override=False)
        self.assertEqual(STKAI_CONFIG.rqc.request_timeout, 90)  # configure wins


class TestResetStkaiConfig(unittest.TestCase):
    """Tests for reset_stkai_config() function."""

    def setUp(self):
        reset_stkai_config()

    def tearDown(self):
        reset_stkai_config()

    def test_reset_clears_config(self):
        """reset_stkai_config() should restore defaults."""
        configure_stkai(
            auth={"client_id": "my-id", "client_secret": "my-secret"},
            rqc={"request_timeout": 999},
            agent={"request_timeout": 888},
        )
        reset_stkai_config()
        self.assertEqual(STKAI_CONFIG.rqc.request_timeout, 30)
        self.assertEqual(STKAI_CONFIG.agent.request_timeout, 60)
        self.assertFalse(STKAI_CONFIG.auth.has_credentials())

    def test_reset_returns_instance(self):
        """reset_stkai_config() should return the reset instance."""
        result = reset_stkai_config()
        self.assertIsInstance(result, StkAiConfig)
        # STKAI_CONFIG is a proxy, so check values match
        self.assertEqual(result.rqc.request_timeout, STKAI_CONFIG.rqc.request_timeout)


class TestAllEnvVars(unittest.TestCase):
    """Tests to ensure all env vars work correctly."""

    def setUp(self):
        reset_stkai_config()

    def tearDown(self):
        reset_stkai_config()

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
        reset_stkai_config()
        self.assertEqual(STKAI_CONFIG.rqc.base_url, "https://rqc.custom")
        self.assertEqual(STKAI_CONFIG.rqc.request_timeout, 100)
        self.assertEqual(STKAI_CONFIG.rqc.max_retries, 5)
        self.assertEqual(STKAI_CONFIG.rqc.backoff_factor, 1.0)
        self.assertEqual(STKAI_CONFIG.rqc.poll_interval, 20.0)
        self.assertEqual(STKAI_CONFIG.rqc.poll_max_duration, 900.0)
        self.assertEqual(STKAI_CONFIG.rqc.overload_timeout, 120.0)
        self.assertEqual(STKAI_CONFIG.rqc.max_workers, 16)

    @patch.dict(
        os.environ,
        {
            "STKAI_AGENT_BASE_URL": "https://agent.custom",
            "STKAI_AGENT_REQUEST_TIMEOUT": "200",
        },
    )
    def test_all_agent_env_vars(self):
        """All Agent env vars should be read correctly."""
        reset_stkai_config()
        self.assertEqual(STKAI_CONFIG.agent.base_url, "https://agent.custom")
        self.assertEqual(STKAI_CONFIG.agent.request_timeout, 200)


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
        reset_stkai_config()

    def tearDown(self):
        reset_stkai_config()

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


if __name__ == "__main__":
    unittest.main()
