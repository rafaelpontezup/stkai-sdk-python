"""Tests for Agent client and related classes."""

import unittest
from typing import Any
from unittest.mock import MagicMock

import requests

from stkai import HttpClient
from stkai.agents import (
    Agent,
    AgentOptions,
    ChatRequest,
    ChatResponse,
    ChatStatus,
    ChatTokenUsage,
)


class MockHttpClient(HttpClient):
    """Mock HTTP client for testing."""

    def __init__(self, response_data: dict | None = None, status_code: int = 200):
        self.response_data = response_data or {}
        self.status_code = status_code
        self.calls: list[tuple[str, dict | None, int]] = []

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        self.calls.append((url, None, timeout))
        response = MagicMock(spec=requests.Response)
        response.status_code = self.status_code
        response.json.return_value = self.response_data
        response.text = str(self.response_data)

        if self.status_code >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(
                response=response
            )
        else:
            response.raise_for_status.return_value = None

        return response

    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        self.calls.append((url, data, timeout))
        response = MagicMock(spec=requests.Response)
        response.status_code = self.status_code
        response.json.return_value = self.response_data
        response.text = str(self.response_data)

        if self.status_code >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(
                response=response
            )
        else:
            response.raise_for_status.return_value = None

        return response


class TestChatTokenUsage(unittest.TestCase):
    """Tests for ChatTokenUsage data class."""

    def test_total_returns_sum_of_all_tokens(self):
        """Should return sum of user, enrichment, and output tokens."""
        usage = ChatTokenUsage(user=100, enrichment=50, output=200)

        self.assertEqual(usage.total, 350)

    def test_total_with_zero_values(self):
        """Should handle zero values correctly."""
        usage = ChatTokenUsage(user=0, enrichment=0, output=0)

        self.assertEqual(usage.total, 0)

    def test_is_frozen(self):
        """Should be immutable."""
        usage = ChatTokenUsage(user=100, enrichment=50, output=200)

        with self.assertRaises(AttributeError):
            usage.user = 200  # type: ignore


class TestChatResponseTokensProperty(unittest.TestCase):
    """Tests for ChatResponse.tokens property handling null values from API."""

    def test_tokens_with_all_null_values(self):
        """Should handle tokens with all null values from API."""
        request = ChatRequest(user_prompt="Hello!")
        response = ChatResponse(
            request=request,
            status=ChatStatus.SUCCESS,
            raw_response={
                "message": "Response",
                "tokens": {"user": None, "enrichment": None, "output": None},
            },
        )

        tokens = response.tokens
        self.assertIsNotNone(tokens)
        self.assertEqual(tokens.user, 0)
        self.assertEqual(tokens.enrichment, 0)
        self.assertEqual(tokens.output, 0)
        self.assertEqual(tokens.total, 0)

    def test_tokens_with_some_null_values(self):
        """Should handle tokens with some null values from API."""
        request = ChatRequest(user_prompt="Hello!")
        response = ChatResponse(
            request=request,
            status=ChatStatus.SUCCESS,
            raw_response={
                "message": "Response",
                "tokens": {"user": 100, "enrichment": None, "output": 50},
            },
        )

        tokens = response.tokens
        self.assertIsNotNone(tokens)
        self.assertEqual(tokens.user, 100)
        self.assertEqual(tokens.enrichment, 0)
        self.assertEqual(tokens.output, 50)
        self.assertEqual(tokens.total, 150)

    def test_tokens_with_missing_keys(self):
        """Should handle tokens with missing keys from API."""
        request = ChatRequest(user_prompt="Hello!")
        response = ChatResponse(
            request=request,
            status=ChatStatus.SUCCESS,
            raw_response={
                "message": "Response",
                "tokens": {"user": 100},  # enrichment and output missing
            },
        )

        tokens = response.tokens
        self.assertIsNotNone(tokens)
        self.assertEqual(tokens.user, 100)
        self.assertEqual(tokens.enrichment, 0)
        self.assertEqual(tokens.output, 0)
        self.assertEqual(tokens.total, 100)

    def test_tokens_with_empty_object(self):
        """Should handle empty tokens object from API."""
        request = ChatRequest(user_prompt="Hello!")
        response = ChatResponse(
            request=request,
            status=ChatStatus.SUCCESS,
            raw_response={
                "message": "Response",
                "tokens": {},
            },
        )

        tokens = response.tokens
        self.assertIsNotNone(tokens)
        self.assertEqual(tokens.user, 0)
        self.assertEqual(tokens.enrichment, 0)
        self.assertEqual(tokens.output, 0)
        self.assertEqual(tokens.total, 0)


class TestChatRequest(unittest.TestCase):
    """Tests for ChatRequest data class."""

    def test_creation_with_prompt_only(self):
        """Should create request with auto-generated ID and default values."""
        request = ChatRequest(user_prompt="Hello!")

        self.assertEqual(request.user_prompt, "Hello!")
        self.assertIsNotNone(request.id)
        self.assertIsNone(request.conversation_id)
        self.assertEqual(request.use_conversation, False)
        self.assertEqual(request.use_knowledge_sources, True)
        self.assertEqual(request.return_knowledge_sources, False)
        self.assertEqual(request.metadata, {})

    def test_creation_with_all_fields(self):
        """Should create request with all fields."""
        request = ChatRequest(
            user_prompt="Hello!",
            id="custom-id",
            conversation_id="conv-123",
            use_conversation=True,
            use_knowledge_sources=False,
            return_knowledge_sources=True,
            metadata={"source": "test"},
        )

        self.assertEqual(request.user_prompt, "Hello!")
        self.assertEqual(request.id, "custom-id")
        self.assertEqual(request.conversation_id, "conv-123")
        self.assertEqual(request.use_conversation, True)
        self.assertEqual(request.use_knowledge_sources, False)
        self.assertEqual(request.return_knowledge_sources, True)
        self.assertEqual(request.metadata, {"source": "test"})

    def test_creation_fails_when_prompt_is_empty(self):
        """Should fail when user_prompt is empty."""
        with self.assertRaises(AssertionError):
            ChatRequest(user_prompt="")

    def test_creation_fails_when_id_is_empty(self):
        """Should fail when id is explicitly empty."""
        with self.assertRaises(AssertionError):
            ChatRequest(user_prompt="Hello!", id="")

    def test_to_api_payload_with_defaults(self):
        """Should convert to API payload with default values."""
        request = ChatRequest(user_prompt="Hello!")

        payload = request.to_api_payload()

        self.assertEqual(payload["user_prompt"], "Hello!")
        self.assertEqual(payload["streaming"], False)
        self.assertEqual(payload["use_conversation"], False)
        self.assertEqual(payload["stackspot_knowledge"], "true")
        self.assertEqual(payload["return_ks_in_response"], False)
        self.assertNotIn("conversation_id", payload)

    def test_to_api_payload_with_conversation(self):
        """Should include conversation_id when provided."""
        request = ChatRequest(
            user_prompt="Hello!",
            conversation_id="conv-123",
            use_conversation=True,
        )

        payload = request.to_api_payload()

        self.assertEqual(payload["use_conversation"], True)
        self.assertEqual(payload["conversation_id"], "conv-123")

    def test_to_api_payload_with_knowledge_sources_disabled(self):
        """Should set stackspot_knowledge to false when disabled."""
        request = ChatRequest(
            user_prompt="Hello!",
            use_knowledge_sources=False,
        )

        payload = request.to_api_payload()

        self.assertEqual(payload["stackspot_knowledge"], "false")

    def test_to_api_payload_with_return_knowledge_sources(self):
        """Should set return_ks_in_response when enabled."""
        request = ChatRequest(
            user_prompt="Hello!",
            return_knowledge_sources=True,
        )

        payload = request.to_api_payload()

        self.assertEqual(payload["return_ks_in_response"], True)


class TestChatResponse(unittest.TestCase):
    """Tests for ChatResponse data class."""

    def test_is_success_returns_true_when_status_is_success(self):
        """Should return True when status is SUCCESS."""
        request = ChatRequest(user_prompt="Hello!")
        response = ChatResponse(
            request=request,
            status=ChatStatus.SUCCESS,
            raw_response={"message": "Hi there!"},
        )

        self.assertTrue(response.is_success())
        self.assertFalse(response.is_error())
        self.assertFalse(response.is_timeout())
        self.assertEqual(response.raw_result, "Hi there!")

    def test_is_error_returns_true_when_status_is_error(self):
        """Should return True when status is ERROR."""
        request = ChatRequest(user_prompt="Hello!")
        response = ChatResponse(
            request=request,
            status=ChatStatus.ERROR,
            error="Something went wrong",
        )

        self.assertTrue(response.is_error())
        self.assertFalse(response.is_success())
        self.assertFalse(response.is_timeout())

    def test_is_timeout_returns_true_when_status_is_timeout(self):
        """Should return True when status is TIMEOUT."""
        request = ChatRequest(user_prompt="Hello!")
        response = ChatResponse(
            request=request,
            status=ChatStatus.TIMEOUT,
            error="Request timed out",
        )

        self.assertTrue(response.is_timeout())
        self.assertFalse(response.is_success())
        self.assertFalse(response.is_error())

    def test_creation_fails_when_request_is_none(self):
        """Should fail when request is None."""
        with self.assertRaises(AssertionError):
            ChatResponse(request=None, status=ChatStatus.SUCCESS)  # type: ignore

    def test_creation_fails_when_status_is_none(self):
        """Should fail when status is None."""
        request = ChatRequest(user_prompt="Hello!")
        with self.assertRaises(AssertionError):
            ChatResponse(request=request, status=None)  # type: ignore

    def test_error_with_details_returns_empty_dict_for_success(self):
        """Should return empty dict when response is successful."""
        request = ChatRequest(user_prompt="Hello!")
        response = ChatResponse(
            request=request,
            status=ChatStatus.SUCCESS,
            raw_response={"message": "Hi there!"},
        )

        self.assertEqual(response.error_with_details(), {})

    def test_error_with_details_returns_details_for_error(self):
        """Should return error details when response has error status."""
        request = ChatRequest(user_prompt="Hello!")
        raw_response = {"error": "Internal server error"}
        response = ChatResponse(
            request=request,
            status=ChatStatus.ERROR,
            error="HTTP error 500",
            raw_response=raw_response,
        )

        details = response.error_with_details()

        self.assertEqual(details["status"], ChatStatus.ERROR)
        self.assertEqual(details["error_message"], "HTTP error 500")
        self.assertEqual(details["response_body"], raw_response)

    def test_error_with_details_returns_details_for_timeout(self):
        """Should return error details when response has timeout status."""
        request = ChatRequest(user_prompt="Hello!")
        response = ChatResponse(
            request=request,
            status=ChatStatus.TIMEOUT,
            error="Request timed out",
        )

        details = response.error_with_details()

        self.assertEqual(details["status"], ChatStatus.TIMEOUT)
        self.assertEqual(details["error_message"], "Request timed out")
        self.assertEqual(details["response_body"], {})


class TestAgentOptions(unittest.TestCase):
    """Tests for AgentOptions data class."""

    def test_default_values_are_none(self):
        """Should have None as default values (to be filled from config)."""
        options = AgentOptions()

        self.assertIsNone(options.request_timeout)

    def test_custom_values(self):
        """Should accept custom values."""
        options = AgentOptions(request_timeout=120)

        self.assertEqual(options.request_timeout, 120)

    def test_is_frozen(self):
        """Should be immutable."""
        options = AgentOptions()

        with self.assertRaises(AttributeError):
            options.request_timeout = 120  # type: ignore

    def test_with_defaults_from_fills_none_values(self):
        """Should fill None values from config defaults."""
        from stkai._config import STKAI

        cfg = STKAI.config.agent

        # Options with all None values
        options = AgentOptions()
        resolved = options.with_defaults_from(cfg)

        # All values should be filled from config
        self.assertEqual(resolved.request_timeout, cfg.request_timeout)

    def test_with_defaults_from_preserves_user_values(self):
        """Should preserve user-provided values and only fill None values."""
        from stkai._config import STKAI

        cfg = STKAI.config.agent

        # Options with user-provided value
        options = AgentOptions(request_timeout=999)
        resolved = options.with_defaults_from(cfg)

        # User value should be preserved
        self.assertEqual(resolved.request_timeout, 999)
        self.assertNotEqual(resolved.request_timeout, cfg.request_timeout)


class TestAgent(unittest.TestCase):
    """Tests for Agent client."""

    def test_init_with_agent_id_only(self):
        """Should initialize with agent_id and defaults."""
        agent = Agent(agent_id="my-agent")

        self.assertEqual(agent.agent_id, "my-agent")
        self.assertIsNotNone(agent.options)
        self.assertIsNotNone(agent.http_client)

    def test_init_with_custom_options(self):
        """Should initialize with custom options."""
        options = AgentOptions(request_timeout=120)
        agent = Agent(agent_id="my-agent", options=options)

        self.assertEqual(agent.options.request_timeout, 120)

    def test_init_with_custom_http_client(self):
        """Should initialize with custom HTTP client."""
        mock_client = MockHttpClient()
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        self.assertEqual(agent.http_client, mock_client)

    def test_init_fails_when_agent_id_is_empty(self):
        """Should fail when agent_id is empty."""
        with self.assertRaises(AssertionError):
            Agent(agent_id="")

    def test_chat_success(self):
        """Should return successful response."""
        mock_client = MockHttpClient(
            response_data={
                "message": "Hello! I'm an AI assistant.",
                "stop_reason": "stop",
                "tokens": {"user": 10, "enrichment": 5, "output": 20},
                "conversation_id": "conv-123",
            }
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        response = agent.chat(ChatRequest(user_prompt="Hello!"))

        self.assertTrue(response.is_success())
        self.assertEqual(response.raw_result, "Hello! I'm an AI assistant.")
        self.assertEqual(response.stop_reason, "stop")
        self.assertEqual(response.conversation_id, "conv-123")
        self.assertIsNotNone(response.tokens)
        self.assertEqual(response.tokens.total, 35)

    def test_chat_with_conversation(self):
        """Should send conversation_id when use_conversation is True."""
        mock_client = MockHttpClient(
            response_data={"message": "Response", "conversation_id": "conv-456"}
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        request = ChatRequest(
            user_prompt="Continue",
            conversation_id="conv-123",
            use_conversation=True,
        )
        agent.chat(request)

        # Verify the payload sent to the HTTP client
        _, payload, _ = mock_client.calls[0]
        self.assertEqual(payload["use_conversation"], True)
        self.assertEqual(payload["conversation_id"], "conv-123")

    def test_chat_with_knowledge_sources_disabled(self):
        """Should disable knowledge sources when configured in request."""
        mock_client = MockHttpClient(response_data={"message": "Response"})
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        request = ChatRequest(
            user_prompt="Hello!",
            use_knowledge_sources=False,
        )
        agent.chat(request)

        _, payload, _ = mock_client.calls[0]
        self.assertEqual(payload["stackspot_knowledge"], "false")

    def test_chat_with_return_knowledge_sources(self):
        """Should return knowledge source IDs when configured in request."""
        mock_client = MockHttpClient(
            response_data={
                "message": "Response",
                "knowledge_source_id": ["ks-1", "ks-2"],
            }
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        request = ChatRequest(
            user_prompt="Hello!",
            return_knowledge_sources=True,
        )
        response = agent.chat(request)

        _, payload, _ = mock_client.calls[0]
        self.assertEqual(payload["return_ks_in_response"], True)
        self.assertEqual(response.knowledge_sources, ["ks-1", "ks-2"])

    def test_chat_http_error(self):
        """Should return error response on HTTP error."""
        mock_client = MockHttpClient(
            response_data={"error": "Internal error"},
            status_code=500,
        )
        # Disable retry to test HTTP error handling directly
        options = AgentOptions(retry_max_retries=0)
        agent = Agent(agent_id="my-agent", options=options, http_client=mock_client)

        response = agent.chat(ChatRequest(user_prompt="Hello!"))

        self.assertTrue(response.is_error())
        self.assertEqual(response.status, ChatStatus.ERROR)
        self.assertIn("HTTP error", response.error)

    def test_chat_success_has_correct_status(self):
        """Should return SUCCESS status on successful response."""
        mock_client = MockHttpClient(
            response_data={"message": "Response"}
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        response = agent.chat(ChatRequest(user_prompt="Hello!"))

        self.assertEqual(response.status, ChatStatus.SUCCESS)
        self.assertTrue(response.is_success())

    def test_chat_uses_custom_timeout(self):
        """Should use timeout from options."""
        mock_client = MockHttpClient(response_data={"message": "Response"})
        options = AgentOptions(request_timeout=120)
        agent = Agent(agent_id="my-agent", options=options, http_client=mock_client)

        agent.chat(ChatRequest(user_prompt="Hello!"))

        _, _, timeout = mock_client.calls[0]
        self.assertEqual(timeout, 120)

    def test_chat_sends_to_correct_agent_id(self):
        """Should send request to the configured agent_id."""
        mock_client = MockHttpClient(response_data={"message": "Response"})
        agent = Agent(agent_id="specific-agent", http_client=mock_client)

        agent.chat(ChatRequest(user_prompt="Hello!"))

        url, _, _ = mock_client.calls[0]
        self.assertIn("/v1/agent/specific-agent/chat", url)

    def test_chat_response_without_tokens(self):
        """Should handle response without tokens field."""
        mock_client = MockHttpClient(
            response_data={"message": "Response without tokens"}
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        response = agent.chat(ChatRequest(user_prompt="Hello!"))

        self.assertTrue(response.is_success())
        self.assertIsNone(response.tokens)


class TestAgentBaseUrl(unittest.TestCase):
    """Tests for Agent base_url parameter."""

    def test_custom_base_url_is_used(self):
        """Should use custom base_url when provided."""
        mock_client = MockHttpClient(response_data={"message": "Response"})
        agent = Agent(
            agent_id="my-agent",
            base_url="https://custom.api.com",
            http_client=mock_client,
        )

        agent.chat(ChatRequest(user_prompt="Hello!"))

        url, _, _ = mock_client.calls[0]
        self.assertIn("https://custom.api.com", url)

    def test_default_base_url_from_config(self):
        """Should use config base_url when not provided."""
        from stkai._config import STKAI

        agent = Agent(agent_id="my-agent")

        self.assertEqual(agent.base_url, STKAI.config.agent.base_url.rstrip("/"))

    def test_base_url_attribute_is_set(self):
        """Should set base_url as instance attribute."""
        agent = Agent(
            agent_id="my-agent",
            base_url="https://custom.api.com/",
            http_client=MockHttpClient(),
        )

        # Should strip trailing slash
        self.assertEqual(agent.base_url, "https://custom.api.com")


class FailThenSucceedHttpClient(HttpClient):
    """HTTP client that fails N times then succeeds."""

    def __init__(
        self,
        fail_count: int,
        failure_status_code: int = 503,
        success_data: dict | None = None,
    ):
        self.fail_count = fail_count
        self.failure_status_code = failure_status_code
        self.success_data = success_data or {"message": "Success"}
        self.call_count = 0

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        return self._make_response()

    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        return self._make_response()

    def _make_response(self) -> requests.Response:
        self.call_count += 1
        response = MagicMock(spec=requests.Response)

        if self.call_count <= self.fail_count:
            response.status_code = self.failure_status_code
            response.json.return_value = {"error": "Server error"}
            response.text = "Server error"
            error = requests.HTTPError(response=response)
            response.raise_for_status.side_effect = error
        else:
            response.status_code = 200
            response.json.return_value = self.success_data
            response.text = str(self.success_data)
            response.raise_for_status.return_value = None

        return response


class TestAgentOptionsRetry(unittest.TestCase):
    """Tests for AgentOptions retry fields."""

    def test_default_retry_values_are_none(self):
        """Should have None as default retry values (to be filled from config)."""
        options = AgentOptions()

        self.assertIsNone(options.retry_max_retries)
        self.assertIsNone(options.retry_initial_delay)

    def test_custom_retry_values(self):
        """Should accept custom retry values."""
        options = AgentOptions(
            retry_max_retries=5,
            retry_initial_delay=1.0,
        )

        self.assertEqual(options.retry_max_retries, 5)
        self.assertEqual(options.retry_initial_delay, 1.0)

    def test_with_defaults_from_fills_retry_values(self):
        """Should fill retry values from config defaults."""
        from stkai._config import STKAI

        cfg = STKAI.config.agent

        options = AgentOptions()
        resolved = options.with_defaults_from(cfg)

        self.assertEqual(resolved.retry_max_retries, cfg.retry_max_retries)
        self.assertEqual(resolved.retry_initial_delay, cfg.retry_initial_delay)

    def test_with_defaults_from_preserves_user_retry_values(self):
        """Should preserve user-provided retry values."""
        from stkai._config import STKAI

        cfg = STKAI.config.agent

        options = AgentOptions(retry_max_retries=10, retry_initial_delay=2.0)
        resolved = options.with_defaults_from(cfg)

        self.assertEqual(resolved.retry_max_retries, 10)
        self.assertEqual(resolved.retry_initial_delay, 2.0)


class TestAgentRetry(unittest.TestCase):
    """Tests for Agent retry behavior."""

    def test_no_retry_when_retry_disabled(self):
        """Should not retry when retry_max_retries is 0."""
        mock_client = MockHttpClient(
            response_data={"error": "Server error"},
            status_code=503,
        )
        options = AgentOptions(retry_max_retries=0)
        agent = Agent(agent_id="my-agent", options=options, http_client=mock_client)

        response = agent.chat(ChatRequest(user_prompt="Hello!"))

        self.assertEqual(len(mock_client.calls), 1)  # Only 1 attempt
        self.assertTrue(response.is_error())

    @unittest.mock.patch("stkai._retry.sleep_with_jitter")
    def test_retry_success_after_failures(self, mock_sleep: MagicMock):
        """Should succeed after retrying failed requests."""
        # Fail twice, then succeed
        mock_client = FailThenSucceedHttpClient(
            fail_count=2,
            failure_status_code=503,
            success_data={"message": "Success after retry"},
        )
        options = AgentOptions(retry_max_retries=3, retry_initial_delay=0.1)
        agent = Agent(agent_id="my-agent", options=options, http_client=mock_client)

        response = agent.chat(ChatRequest(user_prompt="Hello!"))

        self.assertEqual(mock_client.call_count, 3)  # 2 failures + 1 success
        self.assertTrue(response.is_success())
        self.assertEqual(response.raw_result, "Success after retry")

    @unittest.mock.patch("stkai._retry.sleep_with_jitter")
    def test_retry_exhausted_returns_error(self, mock_sleep: MagicMock):
        """Should return error response when all retries exhausted."""
        mock_client = MockHttpClient(
            response_data={"error": "Server error"},
            status_code=503,
        )
        options = AgentOptions(retry_max_retries=2, retry_initial_delay=0.1)
        agent = Agent(agent_id="my-agent", options=options, http_client=mock_client)

        response = agent.chat(ChatRequest(user_prompt="Hello!"))

        self.assertEqual(len(mock_client.calls), 3)  # 1 original + 2 retries
        self.assertTrue(response.is_error())
        self.assertIn("Max retries exceeded", response.error)

    def test_no_retry_on_4xx_errors(self):
        """Should not retry on 4xx client errors."""
        mock_client = MockHttpClient(
            response_data={"error": "Bad request"},
            status_code=400,
        )
        options = AgentOptions(retry_max_retries=3)
        agent = Agent(agent_id="my-agent", options=options, http_client=mock_client)

        response = agent.chat(ChatRequest(user_prompt="Hello!"))

        self.assertEqual(len(mock_client.calls), 1)  # No retry
        self.assertTrue(response.is_error())
        self.assertIn("HTTP error 400", response.error)

    def test_no_retry_on_401_unauthorized(self):
        """Should not retry on 401 Unauthorized."""
        mock_client = MockHttpClient(
            response_data={"error": "Unauthorized"},
            status_code=401,
        )
        options = AgentOptions(retry_max_retries=3)
        agent = Agent(agent_id="my-agent", options=options, http_client=mock_client)

        response = agent.chat(ChatRequest(user_prompt="Hello!"))

        self.assertEqual(len(mock_client.calls), 1)  # No retry
        self.assertTrue(response.is_error())

    def test_no_retry_on_404_not_found(self):
        """Should not retry on 404 Not Found."""
        mock_client = MockHttpClient(
            response_data={"error": "Not found"},
            status_code=404,
        )
        options = AgentOptions(retry_max_retries=3)
        agent = Agent(agent_id="my-agent", options=options, http_client=mock_client)

        response = agent.chat(ChatRequest(user_prompt="Hello!"))

        self.assertEqual(len(mock_client.calls), 1)  # No retry
        self.assertTrue(response.is_error())


class TestAgentChatMany(unittest.TestCase):
    """Tests for Agent.chat_many() batch execution."""

    def test_chat_many_returns_empty_list_for_empty_request_list(self):
        """Should return empty list when request_list is empty."""
        mock_client = MockHttpClient(response_data={"message": "Response"})
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        responses = agent.chat_many([])

        self.assertEqual(responses, [])
        self.assertEqual(len(mock_client.calls), 0)

    def test_chat_many_executes_all_requests_concurrently(self):
        """Should execute all requests and return responses for each."""
        mock_client = MockHttpClient(
            response_data={"message": "Hello!"}
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        requests_list = [
            ChatRequest(user_prompt="Question 1"),
            ChatRequest(user_prompt="Question 2"),
            ChatRequest(user_prompt="Question 3"),
        ]
        responses = agent.chat_many(requests_list)

        self.assertEqual(len(responses), 3)
        self.assertTrue(all(r.is_success() for r in responses))
        self.assertEqual(len(mock_client.calls), 3)

    def test_chat_many_preserves_request_order_in_responses(self):
        """Should return responses in the same order as requests."""
        mock_client = MockHttpClient(
            response_data={"message": "Response"}
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        requests_list = [
            ChatRequest(user_prompt="First", id="req-1"),
            ChatRequest(user_prompt="Second", id="req-2"),
            ChatRequest(user_prompt="Third", id="req-3"),
        ]
        responses = agent.chat_many(requests_list)

        # Each response should reference its corresponding request (identity check)
        for req, resp in zip(requests_list, responses, strict=True):
            self.assertIs(resp.request, req)

    def test_chat_many_handles_individual_failures_without_affecting_others(self):
        """Should handle individual failures without affecting other requests."""
        call_count = 0

        class AlternatingHttpClient(HttpClient):
            """Fails on even-indexed calls, succeeds on odd."""

            def get(self, url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> requests.Response:
                raise NotImplementedError

            def post(self, url: str, data: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 30) -> requests.Response:
                nonlocal call_count
                current = call_count
                call_count += 1
                response = MagicMock(spec=requests.Response)
                if current % 2 == 0:
                    # Fail
                    response.status_code = 500
                    response.json.return_value = {"error": "Server error"}
                    response.text = "Server error"
                    response.raise_for_status.side_effect = requests.HTTPError(response=response)
                else:
                    # Succeed
                    response.status_code = 200
                    response.json.return_value = {"message": f"Success-{current}"}
                    response.text = f"Success-{current}"
                    response.raise_for_status.return_value = None
                return response

        options = AgentOptions(retry_max_retries=0)
        agent = Agent(agent_id="my-agent", options=options, http_client=AlternatingHttpClient())

        requests_list = [
            ChatRequest(user_prompt="Q1"),
            ChatRequest(user_prompt="Q2"),
            ChatRequest(user_prompt="Q3"),
        ]
        responses = agent.chat_many(requests_list)

        # All responses should be present regardless of individual failures
        self.assertEqual(len(responses), 3)
        # No exception should have been raised — each response has a status
        for resp in responses:
            self.assertIn(resp.status, (ChatStatus.SUCCESS, ChatStatus.ERROR))

    def test_chat_many_passes_result_handler_to_each_request(self):
        """Should pass result_handler to each chat() call."""
        mock_client = MockHttpClient(
            response_data={"message": '{"key": "value"}'}
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        from stkai.agents import JSON_RESULT_HANDLER
        requests_list = [
            ChatRequest(user_prompt="Q1"),
            ChatRequest(user_prompt="Q2"),
        ]
        responses = agent.chat_many(requests_list, result_handler=JSON_RESULT_HANDLER)

        self.assertEqual(len(responses), 2)
        for resp in responses:
            self.assertTrue(resp.is_success())
            self.assertEqual(resp.result, {"key": "value"})

    def test_chat_many_with_max_workers_option(self):
        """Should respect max_workers from AgentOptions."""
        mock_client = MockHttpClient(
            response_data={"message": "Response"}
        )
        options = AgentOptions(max_workers=2)
        agent = Agent(agent_id="my-agent", options=options, http_client=mock_client)

        self.assertEqual(agent.max_workers, 2)

        requests_list = [
            ChatRequest(user_prompt=f"Q{i}") for i in range(5)
        ]
        responses = agent.chat_many(requests_list)

        self.assertEqual(len(responses), 5)
        self.assertTrue(all(r.is_success() for r in responses))


class TestAgentMaxWorkers(unittest.TestCase):
    """Tests for Agent max_workers configuration."""

    def test_default_max_workers_from_config(self):
        """Should use default max_workers from config."""
        from stkai._config import STKAI

        agent = Agent(agent_id="my-agent")

        self.assertEqual(agent.max_workers, STKAI.config.agent.max_workers)

    def test_custom_max_workers_from_options(self):
        """Should use max_workers from AgentOptions."""
        options = AgentOptions(max_workers=4)
        agent = Agent(agent_id="my-agent", options=options)

        self.assertEqual(agent.max_workers, 4)

    def test_agent_options_with_defaults_from_fills_max_workers(self):
        """Should fill max_workers from config defaults."""
        from stkai._config import STKAI

        cfg = STKAI.config.agent
        options = AgentOptions()
        resolved = options.with_defaults_from(cfg)

        self.assertEqual(resolved.max_workers, cfg.max_workers)

    def test_agent_options_with_defaults_from_preserves_user_max_workers(self):
        """Should preserve user-provided max_workers."""
        from stkai._config import STKAI

        cfg = STKAI.config.agent
        options = AgentOptions(max_workers=16)
        resolved = options.with_defaults_from(cfg)

        self.assertEqual(resolved.max_workers, 16)


if __name__ == "__main__":
    unittest.main()
