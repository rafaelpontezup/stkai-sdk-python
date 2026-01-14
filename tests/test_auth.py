"""Tests for authentication module."""

import threading
import time
import unittest
from unittest.mock import Mock, patch

import requests

from stkai._auth import (
    AuthenticationError,
    AuthProvider,
    ClientCredentialsAuthProvider,
    TokenInfo,
    create_standalone_auth,
)
from stkai._config import STKAI


class TestTokenInfo(unittest.TestCase):
    """Tests for TokenInfo dataclass."""

    def test_creation(self):
        """Should create TokenInfo with access_token and expires_at."""
        token = TokenInfo(access_token="test-token", expires_at=1234567890.0)
        self.assertEqual(token.access_token, "test-token")
        self.assertEqual(token.expires_at, 1234567890.0)


class TestAuthenticationError(unittest.TestCase):
    """Tests for AuthenticationError exception."""

    def test_creation_with_message_only(self):
        """Should create error with message only."""
        error = AuthenticationError("Test error")
        self.assertEqual(error.message, "Test error")
        self.assertIsNone(error.cause)
        self.assertEqual(str(error), "Test error")

    def test_creation_with_message_and_cause(self):
        """Should create error with message and cause."""
        cause = ValueError("Original error")
        error = AuthenticationError("Test error", cause=cause)
        self.assertEqual(error.message, "Test error")
        self.assertEqual(error.cause, cause)


class TestClientCredentialsAuthProviderInit(unittest.TestCase):
    """Tests for ClientCredentialsAuthProvider initialization."""

    def test_init_with_valid_credentials(self):
        """Should initialize with valid credentials."""
        auth = ClientCredentialsAuthProvider(
            client_id="test-id",
            client_secret="test-secret",
        )
        self.assertEqual(auth._client_id, "test-id")
        self.assertEqual(auth._client_secret, "test-secret")
        self.assertEqual(auth._token_url, ClientCredentialsAuthProvider.DEFAULT_TOKEN_URL)

    def test_init_with_custom_token_url(self):
        """Should accept custom token URL."""
        auth = ClientCredentialsAuthProvider(
            client_id="test-id",
            client_secret="test-secret",
            token_url="https://custom.url/token",
        )
        self.assertEqual(auth._token_url, "https://custom.url/token")

    def test_init_with_custom_refresh_margin(self):
        """Should accept custom refresh margin."""
        auth = ClientCredentialsAuthProvider(
            client_id="test-id",
            client_secret="test-secret",
            refresh_margin=120,
        )
        self.assertEqual(auth._refresh_margin, 120)

    def test_init_fails_with_empty_client_id(self):
        """Should raise AssertionError for empty client_id."""
        with self.assertRaises(AssertionError) as context:
            ClientCredentialsAuthProvider(
                client_id="",
                client_secret="test-secret",
            )
        self.assertIn("client_id", str(context.exception))

    def test_init_fails_with_none_client_id(self):
        """Should raise AssertionError for None client_id."""
        with self.assertRaises(AssertionError):
            ClientCredentialsAuthProvider(
                client_id=None,  # type: ignore
                client_secret="test-secret",
            )

    def test_init_fails_with_empty_client_secret(self):
        """Should raise AssertionError for empty client_secret."""
        with self.assertRaises(AssertionError) as context:
            ClientCredentialsAuthProvider(
                client_id="test-id",
                client_secret="",
            )
        self.assertIn("client_secret", str(context.exception))


class TestClientCredentialsAuthProviderGetToken(unittest.TestCase):
    """Tests for ClientCredentialsAuthProvider.get_access_token()."""

    def setUp(self):
        self.auth = ClientCredentialsAuthProvider(
            client_id="test-id",
            client_secret="test-secret",
        )

    @patch("stkai._auth.requests.post")
    def test_get_access_token_fetches_new_token(self, mock_post):
        """Should fetch new token on first call."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "new-token",
            "expires_in": 1199,
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        token = self.auth.get_access_token()

        self.assertEqual(token, "new-token")
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], ClientCredentialsAuthProvider.DEFAULT_TOKEN_URL)
        self.assertEqual(call_args[1]["data"]["grant_type"], "client_credentials")
        self.assertEqual(call_args[1]["data"]["client_id"], "test-id")
        self.assertEqual(call_args[1]["data"]["client_secret"], "test-secret")

    @patch("stkai._auth.requests.post")
    def test_get_access_token_returns_cached_token(self, mock_post):
        """Should return cached token if still valid."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "cached-token",
            "expires_in": 1199,
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # First call - fetches token
        token1 = self.auth.get_access_token()
        # Second call - should use cache
        token2 = self.auth.get_access_token()

        self.assertEqual(token1, "cached-token")
        self.assertEqual(token2, "cached-token")
        # Should only call API once
        self.assertEqual(mock_post.call_count, 1)

    @patch("stkai._auth.requests.post")
    @patch("stkai._auth.time.time")
    def test_get_access_token_refreshes_expired_token(self, mock_time, mock_post):
        """Should fetch new token when current one is expired."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "token",
            "expires_in": 100,  # Short TTL for testing
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # First call at time 0
        mock_time.return_value = 0.0
        self.auth.get_access_token()

        # Second call at time 50 (within refresh margin of 60s from expiry at 100)
        mock_time.return_value = 50.0
        self.auth.get_access_token()

        # Should have fetched token twice
        self.assertEqual(mock_post.call_count, 2)

    @patch("stkai._auth.requests.post")
    def test_get_access_token_raises_on_http_error(self, mock_post):
        """Should raise AuthenticationError on HTTP error."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)
        mock_post.return_value = mock_response

        with self.assertRaises(AuthenticationError) as context:
            self.auth.get_access_token()
        self.assertIn("Failed to obtain access token", context.exception.message)

    @patch("stkai._auth.requests.post")
    def test_get_access_token_raises_on_connection_error(self, mock_post):
        """Should raise AuthenticationError on connection error."""
        mock_post.side_effect = requests.ConnectionError("Connection refused")

        with self.assertRaises(AuthenticationError) as context:
            self.auth.get_access_token()
        self.assertIn("Failed to obtain access token", context.exception.message)

    @patch("stkai._auth.requests.post")
    def test_get_access_token_raises_on_missing_field(self, mock_post):
        """Should raise AuthenticationError if response missing access_token."""
        mock_response = Mock()
        mock_response.json.return_value = {"expires_in": 1199}  # Missing access_token
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        with self.assertRaises(AuthenticationError) as context:
            self.auth.get_access_token()
        self.assertIn("missing", context.exception.message.lower())


class TestClientCredentialsAuthProviderGetAuthHeaders(unittest.TestCase):
    """Tests for ClientCredentialsAuthProvider.get_auth_headers()."""

    @patch("stkai._auth.requests.post")
    def test_get_auth_headers_returns_bearer_token(self, mock_post):
        """Should return Authorization header with Bearer token."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "test-token",
            "expires_in": 1199,
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        auth = ClientCredentialsAuthProvider(
            client_id="test-id",
            client_secret="test-secret",
        )
        headers = auth.get_auth_headers()

        self.assertEqual(headers, {"Authorization": "Bearer test-token"})


class TestClientCredentialsAuthProviderThreadSafety(unittest.TestCase):
    """Tests for ClientCredentialsAuthProvider thread safety."""

    @patch("stkai._auth.requests.post")
    def test_concurrent_calls_only_fetch_once(self, mock_post):
        """Multiple threads should share cached token."""
        call_count = 0

        def mock_post_fn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            time.sleep(0.1)  # Simulate network latency
            mock_response = Mock()
            mock_response.json.return_value = {
                "access_token": f"token-{call_count}",
                "expires_in": 1199,
            }
            mock_response.raise_for_status = Mock()
            return mock_response

        mock_post.side_effect = mock_post_fn

        auth = ClientCredentialsAuthProvider(
            client_id="test-id",
            client_secret="test-secret",
        )

        results = []
        errors = []

        def get_token():
            try:
                token = auth.get_access_token()
                results.append(token)
            except Exception as e:
                errors.append(e)

        # Start multiple threads simultaneously
        threads = [threading.Thread(target=get_token) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have no errors
        self.assertEqual(len(errors), 0)
        # All threads should get a token
        self.assertEqual(len(results), 5)
        # API should only be called once (or twice if race condition)
        self.assertLessEqual(call_count, 2)


class TestCreateStandaloneAuth(unittest.TestCase):
    """Tests for create_standalone_auth helper function."""

    def setUp(self):
        STKAI.reset()

    def tearDown(self):
        STKAI.reset()

    def test_raises_when_no_credentials_configured(self):
        """Should raise ValueError when credentials not configured."""
        with self.assertRaises(ValueError) as context:
            create_standalone_auth()
        self.assertIn("Client credentials not configured", str(context.exception))

    @patch.dict("os.environ", {
        "STKAI_AUTH_CLIENT_ID": "env-id",
        "STKAI_AUTH_CLIENT_SECRET": "env-secret",
    })
    def test_uses_credentials_from_env(self):
        """Should use credentials from environment variables."""
        STKAI.reset()  # Re-read env vars
        auth = create_standalone_auth()

        self.assertIsInstance(auth, ClientCredentialsAuthProvider)
        self.assertEqual(auth._client_id, "env-id")
        self.assertEqual(auth._client_secret, "env-secret")

    def test_uses_custom_config(self):
        """Should use credentials from provided config."""
        from stkai._config import AuthConfig

        config = AuthConfig(
            client_id="custom-id",
            client_secret="custom-secret",
            token_url="https://custom.url/token",
        )
        auth = create_standalone_auth(config=config)

        self.assertIsInstance(auth, ClientCredentialsAuthProvider)
        self.assertEqual(auth._client_id, "custom-id")
        self.assertEqual(auth._client_secret, "custom-secret")
        self.assertEqual(auth._token_url, "https://custom.url/token")


class TestAuthProviderIsAbstract(unittest.TestCase):
    """Tests for AuthProvider abstract base class."""

    def test_cannot_instantiate_directly(self):
        """Should not be able to instantiate AuthProvider directly."""
        with self.assertRaises(TypeError):
            AuthProvider()  # type: ignore

    def test_subclass_must_implement_get_access_token(self):
        """Subclass must implement get_access_token."""
        class IncompleteAuth(AuthProvider):
            pass

        with self.assertRaises(TypeError):
            IncompleteAuth()  # type: ignore

    def test_subclass_inherits_get_auth_headers(self):
        """Subclass should inherit get_auth_headers implementation."""
        class MockAuth(AuthProvider):
            def get_access_token(self) -> str:
                return "mock-token"

        auth = MockAuth()
        headers = auth.get_auth_headers()

        self.assertEqual(headers, {"Authorization": "Bearer mock-token"})


if __name__ == "__main__":
    unittest.main()
