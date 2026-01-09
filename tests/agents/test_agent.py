"""Tests for Agent client and related classes."""

import unittest
from unittest.mock import MagicMock

import requests

from stkai.agents import (
    Agent,
    AgentHttpClient,
    AgentOptions,
    ChatRequest,
    ChatResponse,
    ChatStatus,
    ChatTokenUsage,
)


class MockAgentHttpClient(AgentHttpClient):
    """Mock HTTP client for testing."""

    def __init__(self, response_data: dict | None = None, status_code: int = 200):
        self.response_data = response_data or {}
        self.status_code = status_code
        self.calls: list[tuple[str, dict, int]] = []

    def send_message(
        self,
        agent_id: str,
        data: dict,
        timeout: int = 60,
    ) -> requests.Response:
        self.calls.append((agent_id, data, timeout))
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
            message="Hi there!",
        )

        self.assertTrue(response.is_success())
        self.assertFalse(response.is_error())
        self.assertFalse(response.is_timeout())

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


class TestAgentOptions(unittest.TestCase):
    """Tests for AgentOptions data class."""

    def test_default_values(self):
        """Should have correct default values."""
        options = AgentOptions()

        self.assertEqual(options.request_timeout, 60)

    def test_custom_values(self):
        """Should accept custom values."""
        options = AgentOptions(request_timeout=120)

        self.assertEqual(options.request_timeout, 120)

    def test_is_frozen(self):
        """Should be immutable."""
        options = AgentOptions()

        with self.assertRaises(AttributeError):
            options.request_timeout = 120  # type: ignore


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
        mock_client = MockAgentHttpClient()
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        self.assertEqual(agent.http_client, mock_client)

    def test_init_fails_when_agent_id_is_empty(self):
        """Should fail when agent_id is empty."""
        with self.assertRaises(AssertionError):
            Agent(agent_id="")

    def test_chat_success(self):
        """Should return successful response."""
        mock_client = MockAgentHttpClient(
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
        self.assertEqual(response.message, "Hello! I'm an AI assistant.")
        self.assertEqual(response.stop_reason, "stop")
        self.assertEqual(response.conversation_id, "conv-123")
        self.assertIsNotNone(response.tokens)
        self.assertEqual(response.tokens.total, 35)

    def test_chat_with_conversation(self):
        """Should send conversation_id when use_conversation is True."""
        mock_client = MockAgentHttpClient(
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
        mock_client = MockAgentHttpClient(response_data={"message": "Response"})
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
        mock_client = MockAgentHttpClient(
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
        mock_client = MockAgentHttpClient(
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
        mock_client = MockAgentHttpClient(
            response_data={"message": "Response"}
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        response = agent.chat(ChatRequest(user_prompt="Hello!"))

        self.assertEqual(response.status, ChatStatus.SUCCESS)
        self.assertTrue(response.is_success())

    def test_chat_uses_custom_timeout(self):
        """Should use timeout from options."""
        mock_client = MockAgentHttpClient(response_data={"message": "Response"})
        options = AgentOptions(request_timeout=120)
        agent = Agent(agent_id="my-agent", options=options, http_client=mock_client)

        agent.chat(ChatRequest(user_prompt="Hello!"))

        _, _, timeout = mock_client.calls[0]
        self.assertEqual(timeout, 120)

    def test_chat_sends_to_correct_agent_id(self):
        """Should send request to the configured agent_id."""
        mock_client = MockAgentHttpClient(response_data={"message": "Response"})
        agent = Agent(agent_id="specific-agent", http_client=mock_client)

        agent.chat(ChatRequest(user_prompt="Hello!"))

        agent_id, _, _ = mock_client.calls[0]
        self.assertEqual(agent_id, "specific-agent")

    def test_chat_response_without_tokens(self):
        """Should handle response without tokens field."""
        mock_client = MockAgentHttpClient(
            response_data={"message": "Response without tokens"}
        )
        agent = Agent(agent_id="my-agent", http_client=mock_client)

        response = agent.chat(ChatRequest(user_prompt="Hello!"))

        self.assertTrue(response.is_success())
        self.assertIsNone(response.tokens)


if __name__ == "__main__":
    unittest.main()
