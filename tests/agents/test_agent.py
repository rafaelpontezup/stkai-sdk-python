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
        agent = Agent(agent_id="my-agent", http_client=mock_client)

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


if __name__ == "__main__":
    unittest.main()
