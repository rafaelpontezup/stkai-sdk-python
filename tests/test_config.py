"""Tests for global configuration module."""

import os
import unittest
from unittest.mock import patch

from stkai._config import (
    config,
    configure,
    reset,
)


class TestDefaults(unittest.TestCase):
    """Tests for default configuration values."""

    def setUp(self):
        reset()

    def tearDown(self):
        reset()

    def test_rqc_defaults(self):
        """Should return sensible defaults for RQC config."""
        self.assertEqual(config.rqc.request_timeout, 30)
        self.assertEqual(config.rqc.max_retries, 3)
        self.assertEqual(config.rqc.backoff_factor, 0.5)
        self.assertEqual(config.rqc.poll_interval, 10.0)
        self.assertEqual(config.rqc.poll_max_duration, 600.0)
        self.assertEqual(config.rqc.overload_timeout, 60.0)
        self.assertEqual(config.rqc.max_workers, 8)
        self.assertIsNone(config.rqc.base_url)

    def test_agent_defaults(self):
        """Should return sensible defaults for Agent config."""
        self.assertEqual(config.agent.base_url, "https://genai-inference-app.stackspot.com")
        self.assertEqual(config.agent.request_timeout, 60)

    def test_credentials_default_to_none(self):
        """Should return None for credentials when not configured."""
        self.assertIsNone(config.client_id)
        self.assertIsNone(config.client_secret)

    def test_has_credentials_false_by_default(self):
        """Should return False when no credentials configured."""
        self.assertFalse(config.has_credentials())


class TestConfigure(unittest.TestCase):
    """Tests for configure() function."""

    def setUp(self):
        reset()

    def tearDown(self):
        reset()

    def test_configure_rqc_values(self):
        """Should override RQC defaults with configure()."""
        configure(rqc={"request_timeout": 60, "max_retries": 10})
        self.assertEqual(config.rqc.request_timeout, 60)
        self.assertEqual(config.rqc.max_retries, 10)
        # Other values should remain default
        self.assertEqual(config.rqc.poll_interval, 10.0)

    def test_configure_agent_values(self):
        """Should override Agent defaults with configure()."""
        configure(agent={"request_timeout": 120})
        self.assertEqual(config.agent.request_timeout, 120)
        # Base URL should remain default
        self.assertEqual(config.agent.base_url, "https://genai-inference-app.stackspot.com")

    def test_configure_credentials(self):
        """Should set credentials via configure()."""
        configure(client_id="my-id", client_secret="my-secret")
        self.assertEqual(config.client_id, "my-id")
        self.assertEqual(config.client_secret, "my-secret")
        self.assertTrue(config.has_credentials())

    def test_configure_partial_credentials(self):
        """Should handle partial credentials."""
        configure(client_id="my-id")
        self.assertFalse(config.has_credentials())  # Need both

    def test_configure_merges_values(self):
        """Should merge multiple configure() calls."""
        configure(rqc={"request_timeout": 60})
        configure(rqc={"max_retries": 10})
        self.assertEqual(config.rqc.request_timeout, 60)
        self.assertEqual(config.rqc.max_retries, 10)

    def test_configure_isolation_between_rqc_and_agent(self):
        """RQC config should not affect Agent config and vice versa."""
        configure(rqc={"request_timeout": 30}, agent={"request_timeout": 120})
        self.assertEqual(config.rqc.request_timeout, 30)
        self.assertEqual(config.agent.request_timeout, 120)


class TestEnvVars(unittest.TestCase):
    """Tests for environment variable fallback."""

    def setUp(self):
        reset()

    def tearDown(self):
        reset()

    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "45"})
    def test_rqc_env_var_override(self):
        """Should use env var value over defaults."""
        self.assertEqual(config.rqc.request_timeout, 45)

    @patch.dict(os.environ, {"STKAI_RQC_MAX_RETRIES": "7"})
    def test_rqc_env_var_int_conversion(self):
        """Should convert env var string to int."""
        self.assertEqual(config.rqc.max_retries, 7)

    @patch.dict(os.environ, {"STKAI_RQC_POLL_INTERVAL": "15.5"})
    def test_rqc_env_var_float_conversion(self):
        """Should convert env var string to float."""
        self.assertEqual(config.rqc.poll_interval, 15.5)

    @patch.dict(os.environ, {"STKAI_AGENT_REQUEST_TIMEOUT": "180"})
    def test_agent_env_var_override(self):
        """Should use env var value for Agent config."""
        self.assertEqual(config.agent.request_timeout, 180)

    @patch.dict(os.environ, {"STKAI_AGENT_BASE_URL": "https://custom.url"})
    def test_agent_base_url_env_var(self):
        """Should use env var for Agent base_url."""
        self.assertEqual(config.agent.base_url, "https://custom.url")

    @patch.dict(os.environ, {"STKAI_CLIENT_ID": "env-id", "STKAI_CLIENT_SECRET": "env-secret"})
    def test_credentials_from_env_vars(self):
        """Should read credentials from env vars."""
        self.assertEqual(config.client_id, "env-id")
        self.assertEqual(config.client_secret, "env-secret")
        self.assertTrue(config.has_credentials())

    @patch.dict(os.environ, {"STKAI_RQC_REQUEST_TIMEOUT": "45"})
    def test_configure_overrides_env_vars(self):
        """configure() should take precedence over env vars."""
        configure(rqc={"request_timeout": 90})
        self.assertEqual(config.rqc.request_timeout, 90)

    @patch.dict(os.environ, {"STKAI_CLIENT_ID": "env-id"})
    def test_configure_credentials_override_env_vars(self):
        """configure() credentials should take precedence over env vars."""
        configure(client_id="configured-id")
        self.assertEqual(config.client_id, "configured-id")


class TestReset(unittest.TestCase):
    """Tests for reset() function."""

    def setUp(self):
        reset()

    def tearDown(self):
        reset()

    def test_reset_clears_config(self):
        """reset() should restore defaults."""
        configure(
            client_id="my-id",
            client_secret="my-secret",
            rqc={"request_timeout": 999},
            agent={"request_timeout": 888},
        )
        reset()
        self.assertEqual(config.rqc.request_timeout, 30)
        self.assertEqual(config.agent.request_timeout, 60)
        self.assertFalse(config.has_credentials())


class TestAllEnvVars(unittest.TestCase):
    """Tests to ensure all env vars work correctly."""

    def setUp(self):
        reset()

    def tearDown(self):
        reset()

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
        self.assertEqual(config.rqc.base_url, "https://rqc.custom")
        self.assertEqual(config.rqc.request_timeout, 100)
        self.assertEqual(config.rqc.max_retries, 5)
        self.assertEqual(config.rqc.backoff_factor, 1.0)
        self.assertEqual(config.rqc.poll_interval, 20.0)
        self.assertEqual(config.rqc.poll_max_duration, 900.0)
        self.assertEqual(config.rqc.overload_timeout, 120.0)
        self.assertEqual(config.rqc.max_workers, 16)

    @patch.dict(
        os.environ,
        {
            "STKAI_AGENT_BASE_URL": "https://agent.custom",
            "STKAI_AGENT_REQUEST_TIMEOUT": "200",
        },
    )
    def test_all_agent_env_vars(self):
        """All Agent env vars should be read correctly."""
        self.assertEqual(config.agent.base_url, "https://agent.custom")
        self.assertEqual(config.agent.request_timeout, 200)


class TestDataclassAccess(unittest.TestCase):
    """Tests for dataclass-style attribute access."""

    def setUp(self):
        reset()

    def tearDown(self):
        reset()

    def test_attribute_access(self):
        """Should access config via attributes."""
        self.assertEqual(config.rqc.request_timeout, 30)
        self.assertEqual(config.agent.base_url, "https://genai-inference-app.stackspot.com")

    def test_rqc_config_is_frozen(self):
        """RqcConfig should be immutable."""
        with self.assertRaises(AttributeError):
            config.rqc.request_timeout = 999  # type: ignore

    def test_agent_config_is_frozen(self):
        """AgentConfig should be immutable."""
        with self.assertRaises(AttributeError):
            config.agent.request_timeout = 999  # type: ignore


if __name__ == "__main__":
    unittest.main()
