"""Tests for HTTP client implementations."""

import threading
from unittest.mock import MagicMock, patch

import pytest
import requests

from stkai import (
    AuthProvider,
    EnvironmentAwareHttpClient,
    HttpClient,
    StandaloneHttpClient,
    StkCLIHttpClient,
)

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
# StkCLIHttpClient Tests
# =============================================================================


class TestStkCLIHttpClientGet:
    """Tests for StkCLIHttpClient.get() method."""

    def test_get_delegates_to_oscli(self):
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200

        # Create a mock module structure
        mock_oscli = MagicMock()
        mock_oscli.core.http.get_with_authorization.return_value = mock_response

        with patch.dict("sys.modules", {"oscli": mock_oscli, "oscli.core": mock_oscli.core, "oscli.core.http": mock_oscli.core.http}):
            client = StkCLIHttpClient()
            response = client.get("http://example.com/api", headers={"X-Custom": "value"}, timeout=60)

            mock_oscli.core.http.get_with_authorization.assert_called_once_with(
                url="http://example.com/api",
                timeout=60,
                headers={"X-Custom": "value"},
                use_cache=False,
            )
            assert response == mock_response

    def test_get_uses_default_timeout(self):
        mock_response = MagicMock(spec=requests.Response)

        mock_oscli = MagicMock()
        mock_oscli.core.http.get_with_authorization.return_value = mock_response

        with patch.dict("sys.modules", {"oscli": mock_oscli, "oscli.core": mock_oscli.core, "oscli.core.http": mock_oscli.core.http}):
            client = StkCLIHttpClient()
            client.get("http://example.com/api")

            mock_oscli.core.http.get_with_authorization.assert_called_once_with(
                url="http://example.com/api",
                timeout=30,
                headers=None,
                use_cache=False,
            )

    def test_get_fails_when_url_is_empty(self):
        client = StkCLIHttpClient()

        with pytest.raises(AssertionError, match="URL cannot be empty"):
            client.get("")

    def test_get_fails_when_url_is_none(self):
        client = StkCLIHttpClient()

        with pytest.raises(AssertionError, match="URL cannot be empty"):
            client.get(None)

    def test_get_fails_when_timeout_is_none(self):
        client = StkCLIHttpClient()

        with pytest.raises(AssertionError, match="Timeout cannot be None"):
            client.get("http://example.com", timeout=None)

    def test_get_fails_when_timeout_is_zero(self):
        client = StkCLIHttpClient()

        with pytest.raises(AssertionError, match="Timeout must be greater than 0"):
            client.get("http://example.com", timeout=0)

    def test_get_fails_when_timeout_is_negative(self):
        client = StkCLIHttpClient()

        with pytest.raises(AssertionError, match="Timeout must be greater than 0"):
            client.get("http://example.com", timeout=-1)


class TestStkCLIHttpClientPost:
    """Tests for StkCLIHttpClient.post() method."""

    def test_post_delegates_to_oscli(self):
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 201

        mock_oscli = MagicMock()
        mock_oscli.core.http.post_with_authorization.return_value = mock_response

        with patch.dict("sys.modules", {"oscli": mock_oscli, "oscli.core": mock_oscli.core, "oscli.core.http": mock_oscli.core.http}):
            client = StkCLIHttpClient()
            response = client.post(
                "http://example.com/api",
                data={"key": "value"},
                headers={"X-Custom": "header"},
                timeout=45,
            )

            mock_oscli.core.http.post_with_authorization.assert_called_once_with(
                url="http://example.com/api",
                body={"key": "value"},
                timeout=45,
                headers={"X-Custom": "header"},
            )
            assert response == mock_response

    def test_post_uses_default_timeout(self):
        mock_response = MagicMock(spec=requests.Response)

        mock_oscli = MagicMock()
        mock_oscli.core.http.post_with_authorization.return_value = mock_response

        with patch.dict("sys.modules", {"oscli": mock_oscli, "oscli.core": mock_oscli.core, "oscli.core.http": mock_oscli.core.http}):
            client = StkCLIHttpClient()
            client.post("http://example.com/api", data={"foo": "bar"})

            mock_oscli.core.http.post_with_authorization.assert_called_once_with(
                url="http://example.com/api",
                body={"foo": "bar"},
                timeout=30,
                headers=None,
            )

    def test_post_allows_none_data(self):
        mock_response = MagicMock(spec=requests.Response)

        mock_oscli = MagicMock()
        mock_oscli.core.http.post_with_authorization.return_value = mock_response

        with patch.dict("sys.modules", {"oscli": mock_oscli, "oscli.core": mock_oscli.core, "oscli.core.http": mock_oscli.core.http}):
            client = StkCLIHttpClient()
            client.post("http://example.com/api")

            mock_oscli.core.http.post_with_authorization.assert_called_once_with(
                url="http://example.com/api",
                body=None,
                timeout=30,
                headers=None,
            )

    def test_post_fails_when_url_is_empty(self):
        client = StkCLIHttpClient()

        with pytest.raises(AssertionError, match="URL cannot be empty"):
            client.post("")

    def test_post_fails_when_url_is_none(self):
        client = StkCLIHttpClient()

        with pytest.raises(AssertionError, match="URL cannot be empty"):
            client.post(None)

    def test_post_fails_when_timeout_is_none(self):
        client = StkCLIHttpClient()

        with pytest.raises(AssertionError, match="Timeout cannot be None"):
            client.post("http://example.com", timeout=None)

    def test_post_fails_when_timeout_is_zero(self):
        client = StkCLIHttpClient()

        with pytest.raises(AssertionError, match="Timeout must be greater than 0"):
            client.post("http://example.com", timeout=0)

    def test_post_fails_when_timeout_is_negative(self):
        client = StkCLIHttpClient()

        with pytest.raises(AssertionError, match="Timeout must be greater than 0"):
            client.post("http://example.com", timeout=-1)


# =============================================================================
# StandaloneHttpClient Tests
# =============================================================================


class MockAuthProvider(AuthProvider):
    """Mock AuthProvider for testing."""

    def __init__(self, token: str = "mock-token"):
        self._token = token

    def get_access_token(self) -> str:
        return self._token


class TestStandaloneHttpClientInit:
    """Tests for StandaloneHttpClient initialization."""

    def test_init_with_valid_auth_provider(self):
        auth = MockAuthProvider()

        client = StandaloneHttpClient(auth_provider=auth)

        assert client._auth == auth

    def test_init_fails_when_auth_provider_is_none(self):
        with pytest.raises(AssertionError, match="auth_provider cannot be None"):
            StandaloneHttpClient(auth_provider=None)

    def test_init_fails_when_auth_provider_is_wrong_type(self):
        with pytest.raises(AssertionError, match="auth_provider must be an AuthProvider instance"):
            StandaloneHttpClient(auth_provider="not-an-auth-provider")

    def test_init_fails_when_auth_provider_is_dict(self):
        with pytest.raises(AssertionError, match="auth_provider must be an AuthProvider instance"):
            StandaloneHttpClient(auth_provider={"token": "abc"})


class TestStandaloneHttpClientGet:
    """Tests for StandaloneHttpClient.get() method."""

    def test_get_includes_auth_headers(self):
        auth = MockAuthProvider(token="test-token-123")
        client = StandaloneHttpClient(auth_provider=auth)
        mock_response = MagicMock(spec=requests.Response)

        with patch("requests.get", return_value=mock_response) as mock_get:
            client.get("http://example.com/api")

            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args.kwargs
            assert "Authorization" in call_kwargs["headers"]
            assert call_kwargs["headers"]["Authorization"] == "Bearer test-token-123"

    def test_get_merges_custom_headers_with_auth_headers(self):
        auth = MockAuthProvider(token="my-token")
        client = StandaloneHttpClient(auth_provider=auth)
        mock_response = MagicMock(spec=requests.Response)

        with patch("requests.get", return_value=mock_response) as mock_get:
            client.get("http://example.com/api", headers={"X-Custom": "value"})

            call_kwargs = mock_get.call_args.kwargs
            assert call_kwargs["headers"]["Authorization"] == "Bearer my-token"
            assert call_kwargs["headers"]["X-Custom"] == "value"

    def test_get_custom_headers_override_auth_headers(self):
        auth = MockAuthProvider(token="original-token")
        client = StandaloneHttpClient(auth_provider=auth)
        mock_response = MagicMock(spec=requests.Response)

        with patch("requests.get", return_value=mock_response) as mock_get:
            # Custom Authorization header should override the auth provider's
            client.get("http://example.com/api", headers={"Authorization": "Custom token"})

            call_kwargs = mock_get.call_args.kwargs
            assert call_kwargs["headers"]["Authorization"] == "Custom token"

    def test_get_passes_url_and_timeout(self):
        auth = MockAuthProvider()
        client = StandaloneHttpClient(auth_provider=auth)
        mock_response = MagicMock(spec=requests.Response)

        with patch("requests.get", return_value=mock_response) as mock_get:
            client.get("http://example.com/api/resource", timeout=60)

            mock_get.assert_called_once_with(
                "http://example.com/api/resource",
                headers={"Authorization": "Bearer mock-token"},
                timeout=60,
            )

    def test_get_uses_default_timeout(self):
        auth = MockAuthProvider()
        client = StandaloneHttpClient(auth_provider=auth)
        mock_response = MagicMock(spec=requests.Response)

        with patch("requests.get", return_value=mock_response) as mock_get:
            client.get("http://example.com/api")

            call_kwargs = mock_get.call_args.kwargs
            assert call_kwargs["timeout"] == 30

    def test_get_fails_when_url_is_empty(self):
        auth = MockAuthProvider()
        client = StandaloneHttpClient(auth_provider=auth)

        with pytest.raises(AssertionError, match="URL cannot be empty"):
            client.get("")

    def test_get_fails_when_timeout_is_none(self):
        auth = MockAuthProvider()
        client = StandaloneHttpClient(auth_provider=auth)

        with pytest.raises(AssertionError, match="Timeout cannot be None"):
            client.get("http://example.com", timeout=None)

    def test_get_fails_when_timeout_is_zero(self):
        auth = MockAuthProvider()
        client = StandaloneHttpClient(auth_provider=auth)

        with pytest.raises(AssertionError, match="Timeout must be greater than 0"):
            client.get("http://example.com", timeout=0)

    def test_get_fails_when_timeout_is_negative(self):
        auth = MockAuthProvider()
        client = StandaloneHttpClient(auth_provider=auth)

        with pytest.raises(AssertionError, match="Timeout must be greater than 0"):
            client.get("http://example.com", timeout=-1)


class TestStandaloneHttpClientPost:
    """Tests for StandaloneHttpClient.post() method."""

    def test_post_includes_auth_headers(self):
        auth = MockAuthProvider(token="post-token")
        client = StandaloneHttpClient(auth_provider=auth)
        mock_response = MagicMock(spec=requests.Response)

        with patch("requests.post", return_value=mock_response) as mock_post:
            client.post("http://example.com/api", data={"key": "value"})

            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs["headers"]["Authorization"] == "Bearer post-token"

    def test_post_sends_json_body(self):
        auth = MockAuthProvider()
        client = StandaloneHttpClient(auth_provider=auth)
        mock_response = MagicMock(spec=requests.Response)

        with patch("requests.post", return_value=mock_response) as mock_post:
            client.post("http://example.com/api", data={"name": "test", "value": 123})

            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs["json"] == {"name": "test", "value": 123}

    def test_post_merges_custom_headers_with_auth_headers(self):
        auth = MockAuthProvider(token="my-token")
        client = StandaloneHttpClient(auth_provider=auth)
        mock_response = MagicMock(spec=requests.Response)

        with patch("requests.post", return_value=mock_response) as mock_post:
            client.post("http://example.com/api", headers={"Content-Type": "application/json"})

            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs["headers"]["Authorization"] == "Bearer my-token"
            assert call_kwargs["headers"]["Content-Type"] == "application/json"

    def test_post_passes_url_and_timeout(self):
        auth = MockAuthProvider()
        client = StandaloneHttpClient(auth_provider=auth)
        mock_response = MagicMock(spec=requests.Response)

        with patch("requests.post", return_value=mock_response) as mock_post:
            client.post("http://example.com/api/create", data={}, timeout=90)

            mock_post.assert_called_once_with(
                "http://example.com/api/create",
                json={},
                headers={"Authorization": "Bearer mock-token"},
                timeout=90,
            )

    def test_post_uses_default_timeout(self):
        auth = MockAuthProvider()
        client = StandaloneHttpClient(auth_provider=auth)
        mock_response = MagicMock(spec=requests.Response)

        with patch("requests.post", return_value=mock_response) as mock_post:
            client.post("http://example.com/api")

            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs["timeout"] == 30

    def test_post_allows_none_data(self):
        auth = MockAuthProvider()
        client = StandaloneHttpClient(auth_provider=auth)
        mock_response = MagicMock(spec=requests.Response)

        with patch("requests.post", return_value=mock_response) as mock_post:
            client.post("http://example.com/api")

            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs["json"] is None

    def test_post_fails_when_url_is_empty(self):
        auth = MockAuthProvider()
        client = StandaloneHttpClient(auth_provider=auth)

        with pytest.raises(AssertionError, match="URL cannot be empty"):
            client.post("")

    def test_post_fails_when_timeout_is_none(self):
        auth = MockAuthProvider()
        client = StandaloneHttpClient(auth_provider=auth)

        with pytest.raises(AssertionError, match="Timeout cannot be None"):
            client.post("http://example.com", timeout=None)

    def test_post_fails_when_timeout_is_zero(self):
        auth = MockAuthProvider()
        client = StandaloneHttpClient(auth_provider=auth)

        with pytest.raises(AssertionError, match="Timeout must be greater than 0"):
            client.post("http://example.com", timeout=0)

    def test_post_fails_when_timeout_is_negative(self):
        auth = MockAuthProvider()
        client = StandaloneHttpClient(auth_provider=auth)

        with pytest.raises(AssertionError, match="Timeout must be greater than 0"):
            client.post("http://example.com", timeout=-1)


# =============================================================================
# EnvironmentAwareHttpClient Tests
# =============================================================================


class TestEnvironmentAwareHttpClientInit:
    """Tests for EnvironmentAwareHttpClient initialization."""

    def test_init_creates_instance_without_delegate(self):
        client = EnvironmentAwareHttpClient()

        assert client._delegate is None

    def test_delegate_is_lazy_initialized(self):
        client = EnvironmentAwareHttpClient()

        # Delegate should not be created until first request
        assert client._delegate is None


class TestEnvironmentAwareHttpClientCLIDetection:
    """Tests for CLI detection in EnvironmentAwareHttpClient."""

    def test_uses_stk_cli_client_when_oscli_is_available(self):
        client = EnvironmentAwareHttpClient()

        # Mock oscli being available
        mock_oscli = MagicMock()
        with patch.dict("sys.modules", {"oscli": mock_oscli}):
            assert client._is_cli_available() is True

    def test_falls_back_when_oscli_import_fails(self):
        client = EnvironmentAwareHttpClient()

        # Ensure oscli is not available
        with patch.dict("sys.modules", {"oscli": None}):
            # Force ImportError by patching __import__
            original_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

            def mock_import(name, *args, **kwargs):
                if name == "oscli":
                    raise ImportError("No module named 'oscli'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                assert client._is_cli_available() is False


class TestEnvironmentAwareHttpClientDelegateCreation:
    """Tests for delegate creation in EnvironmentAwareHttpClient."""

    def test_creates_stk_cli_client_when_oscli_available(self):
        client = EnvironmentAwareHttpClient()

        # Mock oscli being available
        mock_oscli = MagicMock()
        with patch.dict("sys.modules", {"oscli": mock_oscli, "oscli.core": mock_oscli.core, "oscli.core.http": mock_oscli.core.http}):
            with patch.object(client, "_is_cli_available", return_value=True):
                delegate = client._create_delegate()

                assert isinstance(delegate, StkCLIHttpClient)

    def test_creates_standalone_client_when_oscli_not_available_but_credentials_configured(self):
        client = EnvironmentAwareHttpClient()

        # Mock config with credentials
        mock_auth_config = MagicMock()
        mock_auth_config.has_credentials.return_value = True
        mock_auth_config.client_id = "test-client-id"
        mock_auth_config.client_secret = "test-client-secret"
        mock_auth_config.token_url = "https://example.com/token"

        # Mock rate limit config (disabled)
        mock_rate_limit_config = MagicMock()
        mock_rate_limit_config.enabled = False

        mock_config = MagicMock()
        mock_config.auth = mock_auth_config
        mock_config.rate_limit = mock_rate_limit_config

        mock_stkai = MagicMock()
        mock_stkai.config = mock_config

        with patch.object(client, "_is_cli_available", return_value=False):
            with patch("stkai._config.STKAI", mock_stkai):
                with patch("stkai._auth.create_standalone_auth") as mock_create_auth:
                    mock_auth_provider = MagicMock(spec=AuthProvider)
                    mock_create_auth.return_value = mock_auth_provider

                    delegate = client._create_delegate()

                    assert isinstance(delegate, StandaloneHttpClient)
                    mock_create_auth.assert_called_once()

    def test_raises_value_error_when_no_authentication_available(self):
        client = EnvironmentAwareHttpClient()

        # Mock config without credentials
        mock_auth_config = MagicMock()
        mock_auth_config.has_credentials.return_value = False

        mock_config = MagicMock()
        mock_config.auth = mock_auth_config

        mock_stkai = MagicMock()
        mock_stkai.config = mock_config

        with patch.object(client, "_is_cli_available", return_value=False):
            with patch("stkai._config.STKAI", mock_stkai):
                with pytest.raises(ValueError, match="No authentication method available"):
                    client._create_delegate()

    def test_error_message_contains_helpful_instructions(self):
        client = EnvironmentAwareHttpClient()

        mock_auth_config = MagicMock()
        mock_auth_config.has_credentials.return_value = False

        mock_config = MagicMock()
        mock_config.auth = mock_auth_config

        mock_stkai = MagicMock()
        mock_stkai.config = mock_config

        with patch.object(client, "_is_cli_available", return_value=False):
            with patch("stkai._config.STKAI", mock_stkai):
                with pytest.raises(ValueError) as exc_info:
                    client._create_delegate()

                error_message = str(exc_info.value)
                assert "stk login" in error_message
                assert "STKAI_AUTH_CLIENT_ID" in error_message
                assert "STKAI_AUTH_CLIENT_SECRET" in error_message
                assert "STKAI.configure" in error_message


class TestEnvironmentAwareHttpClientGet:
    """Tests for GET requests in EnvironmentAwareHttpClient."""

    def test_get_delegates_to_underlying_client(self):
        client = EnvironmentAwareHttpClient()
        mock_delegate = MockHttpClient()
        client._delegate = mock_delegate

        client.get("http://example.com/api")

        assert len(mock_delegate.get_calls) == 1
        assert mock_delegate.get_calls[0]["url"] == "http://example.com/api"

    def test_get_passes_headers_to_delegate(self):
        client = EnvironmentAwareHttpClient()
        mock_delegate = MockHttpClient()
        client._delegate = mock_delegate

        client.get("http://example.com/api", headers={"X-Custom": "value"})

        assert mock_delegate.get_calls[0]["headers"] == {"X-Custom": "value"}

    def test_get_passes_timeout_to_delegate(self):
        client = EnvironmentAwareHttpClient()
        mock_delegate = MockHttpClient()
        client._delegate = mock_delegate

        client.get("http://example.com/api", timeout=60)

        assert mock_delegate.get_calls[0]["timeout"] == 60

    def test_get_creates_delegate_on_first_call(self):
        client = EnvironmentAwareHttpClient()

        mock_delegate = MockHttpClient()
        with patch.object(client, "_create_delegate", return_value=mock_delegate) as mock_create:
            client.get("http://example.com/api")

            mock_create.assert_called_once()
            assert client._delegate is mock_delegate


class TestEnvironmentAwareHttpClientPost:
    """Tests for POST requests in EnvironmentAwareHttpClient."""

    def test_post_delegates_to_underlying_client(self):
        client = EnvironmentAwareHttpClient()
        mock_delegate = MockHttpClient()
        client._delegate = mock_delegate

        client.post("http://example.com/api", data={"key": "value"})

        assert len(mock_delegate.post_calls) == 1
        assert mock_delegate.post_calls[0]["url"] == "http://example.com/api"
        assert mock_delegate.post_calls[0]["data"] == {"key": "value"}

    def test_post_passes_headers_to_delegate(self):
        client = EnvironmentAwareHttpClient()
        mock_delegate = MockHttpClient()
        client._delegate = mock_delegate

        client.post("http://example.com/api", headers={"X-Custom": "value"})

        assert mock_delegate.post_calls[0]["headers"] == {"X-Custom": "value"}

    def test_post_passes_timeout_to_delegate(self):
        client = EnvironmentAwareHttpClient()
        mock_delegate = MockHttpClient()
        client._delegate = mock_delegate

        client.post("http://example.com/api", timeout=60)

        assert mock_delegate.post_calls[0]["timeout"] == 60

    def test_post_creates_delegate_on_first_call(self):
        client = EnvironmentAwareHttpClient()

        mock_delegate = MockHttpClient()
        with patch.object(client, "_create_delegate", return_value=mock_delegate) as mock_create:
            client.post("http://example.com/api")

            mock_create.assert_called_once()
            assert client._delegate is mock_delegate


class TestEnvironmentAwareHttpClientLazyInitialization:
    """Tests for lazy initialization behavior."""

    def test_delegate_is_cached_after_first_request(self):
        client = EnvironmentAwareHttpClient()
        mock_delegate = MockHttpClient()

        with patch.object(client, "_create_delegate", return_value=mock_delegate) as mock_create:
            # First call
            client.get("http://example.com/api")
            # Second call
            client.get("http://example.com/api")

            # Should only create delegate once
            mock_create.assert_called_once()

    def test_allows_stkai_configure_after_import(self):
        """Test that lazy initialization allows STKAI.configure() to be called after import."""
        client = EnvironmentAwareHttpClient()

        # At this point, no delegate is created
        assert client._delegate is None

        mock_delegate = MockHttpClient()

        # First request triggers delegate creation with the current config
        with patch.object(client, "_create_delegate", return_value=mock_delegate):
            client.get("http://example.com/api")

        # Delegate was created
        assert client._delegate is not None

    def test_thread_safe_delegate_creation(self):
        """Test that delegate is created only once even with concurrent access."""
        import time
        from concurrent.futures import ThreadPoolExecutor

        client = EnvironmentAwareHttpClient()
        creation_count = 0
        creation_lock = threading.Lock()

        def counting_create_delegate():
            nonlocal creation_count
            with creation_lock:
                creation_count += 1
            time.sleep(0.01)  # Simulate slow creation to increase race condition window
            return MockHttpClient()

        with patch.object(client, "_create_delegate", side_effect=counting_create_delegate):
            # Launch multiple threads simultaneously
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [
                    executor.submit(client.get, "http://example.com/api")
                    for _ in range(10)
                ]
                # Wait for all to complete
                for f in futures:
                    f.result()

        # Delegate should be created exactly once
        assert creation_count == 1
        assert client._delegate is not None
