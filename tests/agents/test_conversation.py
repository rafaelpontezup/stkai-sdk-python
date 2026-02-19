"""Tests for UseConversation context manager and ConversationContext."""

import threading
import unittest
from typing import Any
from unittest.mock import MagicMock

import requests

from stkai import HttpClient
from stkai.agents import (
    Agent,
    AgentOptions,
    ChatRequest,
    ConversationContext,
    UseConversation,
)
from stkai.agents._conversation import ConversationScope


class MockHttpClient(HttpClient):
    """Mock HTTP client that records payloads and returns configurable responses."""

    def __init__(
        self,
        response_data: dict | None = None,
        responses: list[dict] | None = None,
        status_code: int = 200,
    ):
        self.response_data = response_data or {}
        self.responses = list(responses) if responses else None
        self.status_code = status_code
        self.calls: list[tuple[str, dict | None, int]] = []
        self._lock = threading.Lock()
        self._call_count = 0

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        raise NotImplementedError

    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        with self._lock:
            self.calls.append((url, data, timeout))
            idx = self._call_count
            self._call_count += 1

        if self.responses and idx < len(self.responses):
            resp_data = self.responses[idx]
        else:
            resp_data = self.response_data

        response = MagicMock(spec=requests.Response)
        response.status_code = self.status_code
        response.json.return_value = resp_data
        response.text = str(resp_data)

        if self.status_code >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(
                response=response
            )
        else:
            response.raise_for_status.return_value = None

        return response


# =============================================================================
# Unit tests: ConversationContext
# =============================================================================


class TestConversationContext(unittest.TestCase):
    """Tests for ConversationContext."""

    def test_initial_state_is_none_by_default(self):
        """Should have None conversation_id by default."""
        ctx = ConversationContext()

        self.assertIsNone(ctx.conversation_id)

    def test_initial_state_from_constructor(self):
        """Should accept initial conversation_id."""
        ctx = ConversationContext(conversation_id="conv-123")

        self.assertEqual(ctx.conversation_id, "conv-123")

    def test_enrich_returns_new_request_with_conversation_fields(self):
        """Should return a new ChatRequest with use_conversation and conversation_id set."""
        ctx = ConversationContext(conversation_id="conv-123")
        original = ChatRequest(user_prompt="Hello")

        enriched = ctx.enrich(original)

        self.assertIsNot(enriched, original)
        self.assertTrue(enriched.use_conversation)
        self.assertEqual(enriched.conversation_id, "conv-123")
        # original unchanged
        self.assertFalse(original.use_conversation)
        self.assertIsNone(original.conversation_id)

    def test_enrich_preserves_other_request_fields(self):
        """Should preserve all other fields from the original request."""
        ctx = ConversationContext(conversation_id="conv-123")
        original = ChatRequest(
            user_prompt="Hello",
            id="my-id",
            use_knowledge_sources=False,
            return_knowledge_sources=True,
            metadata={"key": "value"},
        )

        enriched = ctx.enrich(original)

        self.assertEqual(enriched.user_prompt, "Hello")
        self.assertEqual(enriched.id, "my-id")
        self.assertFalse(enriched.use_knowledge_sources)
        self.assertTrue(enriched.return_knowledge_sources)
        self.assertEqual(enriched.metadata, {"key": "value"})

    def test_enrich_respects_explicit_conversation_id(self):
        """Should return the same request when conversation_id is already set."""
        ctx = ConversationContext(conversation_id="ctx-conv")
        original = ChatRequest(
            user_prompt="Hello",
            conversation_id="explicit-conv",
            use_conversation=True,
        )

        enriched = ctx.enrich(original)

        self.assertIs(enriched, original)
        self.assertEqual(enriched.conversation_id, "explicit-conv")

    def test_enrich_without_conversation_id_sets_use_conversation_only(self):
        """On first call (no conversation_id captured yet), should set use_conversation=True only."""
        ctx = ConversationContext()  # no conversation_id yet
        original = ChatRequest(user_prompt="Hello")

        enriched = ctx.enrich(original)

        self.assertTrue(enriched.use_conversation)
        self.assertIsNone(enriched.conversation_id)

    def test_enrich_is_idempotent(self):
        """Calling enrich twice should return the same enriched request on second call."""
        ctx = ConversationContext(conversation_id="conv-123")
        original = ChatRequest(user_prompt="Hello")

        enriched1 = ctx.enrich(original)
        enriched2 = ctx.enrich(enriched1)

        self.assertIs(enriched2, enriched1)  # same object, no-op

    def testupdate_if_absent_sets_when_none(self):
        """Should set conversation_id when currently None."""
        ctx = ConversationContext()

        ctx.update_if_absent("conv-abc")

        self.assertEqual(ctx.conversation_id, "conv-abc")

    def testupdate_if_absent_noop_when_already_set(self):
        """Should not overwrite existing conversation_id."""
        ctx = ConversationContext(conversation_id="original")

        ctx.update_if_absent("new-value")

        self.assertEqual(ctx.conversation_id, "original")

    def testupdate_if_absent_thread_safety(self):
        """Should safely handle concurrent update_if_absent calls."""
        ctx = ConversationContext()
        results: list[str | None] = []
        barrier = threading.Barrier(10)

        def updater(value: str) -> None:
            barrier.wait()
            ctx.update_if_absent(value)
            results.append(ctx.conversation_id)

        threads = [
            threading.Thread(target=updater, args=(f"conv-{i}",))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should see the same final value
        self.assertIsNotNone(ctx.conversation_id)
        self.assertTrue(all(r == ctx.conversation_id for r in results))


# =============================================================================
# Unit tests: UseConversation
# =============================================================================


class TestUseConversation(unittest.TestCase):
    """Tests for UseConversation context manager."""

    def test_enter_returns_conversation_context(self):
        """__enter__ should return a ConversationContext."""
        with UseConversation() as conv:
            self.assertIsInstance(conv, ConversationContext)

    def test_context_active_inside_block(self):
        """ConversationScope.get_current() should return context inside block."""
        with UseConversation() as conv:
            current = ConversationScope.get_current()
            self.assertIs(current, conv)

    def test_context_none_outside_block(self):
        """ConversationScope.get_current() should return None outside block."""
        with UseConversation():
            pass

        self.assertIsNone(ConversationScope.get_current())

    def test_initial_conversation_id_is_none(self):
        """Should start with None conversation_id when not provided."""
        with UseConversation() as conv:
            self.assertIsNone(conv.conversation_id)

    def test_initial_conversation_id_from_constructor(self):
        """Should use provided conversation_id."""
        with UseConversation(conversation_id="conv-xyz") as conv:
            self.assertEqual(conv.conversation_id, "conv-xyz")

    def test_nesting_inner_overrides_outer(self):
        """Inner UseConversation should override outer."""
        with UseConversation(conversation_id="outer") as outer:
            self.assertEqual(ConversationScope.get_current().conversation_id, "outer")

            with UseConversation(conversation_id="inner") as inner:
                self.assertEqual(ConversationScope.get_current().conversation_id, "inner")
                self.assertIs(ConversationScope.get_current(), inner)

            # After inner exits, outer should be restored
            self.assertIs(ConversationScope.get_current(), outer)
            self.assertEqual(ConversationScope.get_current().conversation_id, "outer")

    def test_cleanup_on_exception(self):
        """Should restore context even when exception occurs."""
        try:
            with UseConversation():
                raise ValueError("test error")
        except ValueError:
            pass

        self.assertIsNone(ConversationScope.get_current())

    def test_warns_when_conversation_id_is_not_ulid(self):
        """Should log a warning when conversation_id is not a valid ULID."""
        with self.assertLogs("stkai.agents._conversation", level="WARNING") as cm:
            UseConversation(conversation_id="not-a-ulid")

        self.assertTrue(
            any("not a valid ULID" in msg for msg in cm.output),
            f"Expected warning about invalid ULID, got: {cm.output}"
        )

    def test_no_warning_when_conversation_id_is_valid_ulid(self):
        """Should NOT warn when conversation_id is a valid ULID."""
        from ulid import ULID
        valid_ulid = str(ULID())

        with self.assertNoLogs("stkai.agents._conversation", level="WARNING"):
            UseConversation(conversation_id=valid_ulid)

    def test_no_warning_when_conversation_id_is_none(self):
        """Should NOT warn when no conversation_id is provided."""
        with self.assertNoLogs("stkai.agents._conversation", level="WARNING"):
            UseConversation()


# =============================================================================
# Integration tests: Agent.chat + UseConversation
# =============================================================================


class TestAgentChatWithUseConversation(unittest.TestCase):
    """Integration tests for Agent.chat() with UseConversation."""

    def _make_agent(self, http_client: HttpClient) -> Agent:
        return Agent(
            agent_id="test-agent",
            options=AgentOptions(retry_max_retries=0),
            http_client=http_client,
        )

    def test_use_conversation_auto_sets_flag_in_payload(self):
        """Should auto-set use_conversation=True in payload inside UseConversation block."""
        mock = MockHttpClient(response_data={"message": "Hi", "conversation_id": "conv-1"})
        agent = self._make_agent(mock)

        with UseConversation():
            agent.chat(ChatRequest(user_prompt="Hello"))

        _, payload, _ = mock.calls[0]
        self.assertTrue(payload["use_conversation"])

    def test_auto_captures_conversation_id_from_first_response(self):
        """Should capture conversation_id from first successful response."""
        mock = MockHttpClient(
            responses=[
                {"message": "Hi", "conversation_id": "conv-auto-1"},
                {"message": "Follow up", "conversation_id": "conv-auto-1"},
            ]
        )
        agent = self._make_agent(mock)

        with UseConversation() as conv:
            agent.chat(ChatRequest(user_prompt="Hello"))
            self.assertEqual(conv.conversation_id, "conv-auto-1")

            agent.chat(ChatRequest(user_prompt="Follow up"))

        # Second call should have used the captured conversation_id
        _, payload2, _ = mock.calls[1]
        self.assertEqual(payload2["conversation_id"], "conv-auto-1")
        self.assertTrue(payload2["use_conversation"])

    def test_user_provided_conversation_id_used_from_start(self):
        """Should use user-provided conversation_id from the start."""
        mock = MockHttpClient(response_data={"message": "Hi", "conversation_id": "conv-user"})
        agent = self._make_agent(mock)

        with UseConversation(conversation_id="conv-user"):
            agent.chat(ChatRequest(user_prompt="Hello"))

        _, payload, _ = mock.calls[0]
        self.assertEqual(payload["conversation_id"], "conv-user")
        self.assertTrue(payload["use_conversation"])

    def test_explicit_request_conversation_id_overrides_context(self):
        """ChatRequest.conversation_id should override UseConversation context."""
        mock = MockHttpClient(response_data={"message": "Hi", "conversation_id": "conv-ctx"})
        agent = self._make_agent(mock)

        with UseConversation(conversation_id="conv-ctx"):
            # Explicit conversation_id on ChatRequest takes precedence
            agent.chat(ChatRequest(
                user_prompt="Hello",
                conversation_id="conv-explicit",
                use_conversation=True,
            ))

        _, payload, _ = mock.calls[0]
        # ChatRequest's conversation_id wins
        self.assertEqual(payload["conversation_id"], "conv-explicit")

    def test_multiple_agents_share_context(self):
        """Multiple agents should share the UseConversation context."""
        mock1 = MockHttpClient(response_data={"message": "Hi", "conversation_id": "shared-conv"})
        mock2 = MockHttpClient(response_data={"message": "Hi2", "conversation_id": "shared-conv"})
        agent1 = self._make_agent(mock1)
        agent2 = self._make_agent(mock2)

        with UseConversation() as conv:
            agent1.chat(ChatRequest(user_prompt="Hello from agent1"))
            self.assertEqual(conv.conversation_id, "shared-conv")

            agent2.chat(ChatRequest(user_prompt="Hello from agent2"))

        _, payload2, _ = mock2.calls[0]
        self.assertEqual(payload2["conversation_id"], "shared-conv")
        self.assertTrue(payload2["use_conversation"])

    def test_no_effect_outside_use_conversation_block(self):
        """Agent.chat() should work normally outside UseConversation block."""
        mock = MockHttpClient(response_data={"message": "Hi"})
        agent = self._make_agent(mock)

        agent.chat(ChatRequest(user_prompt="Hello"))

        _, payload, _ = mock.calls[0]
        # Default ChatRequest has use_conversation=False
        self.assertFalse(payload["use_conversation"])
        self.assertNotIn("conversation_id", payload)

    def test_failed_response_does_not_break_context(self):
        """Failed response should not update context but context should still work."""
        mock = MockHttpClient(
            responses=[
                {"error": "Server error"},  # will fail via status_code
                {"message": "Success", "conversation_id": "conv-after-fail"},
            ],
        )
        # First call fails (500), second succeeds (200)
        call_count = 0
        original_post = mock.post

        def alternating_post(url, data=None, headers=None, timeout=30):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                mock.status_code = 500
            else:
                mock.status_code = 200
            return original_post(url, data, headers, timeout)

        mock.post = alternating_post  # type: ignore[method-assign]
        agent = self._make_agent(mock)

        with UseConversation() as conv:
            r1 = agent.chat(ChatRequest(user_prompt="Fail"))
            self.assertTrue(r1.is_error())
            self.assertIsNone(conv.conversation_id)

            r2 = agent.chat(ChatRequest(user_prompt="Succeed"))
            self.assertTrue(r2.is_success())
            self.assertEqual(conv.conversation_id, "conv-after-fail")

    def test_first_call_without_conversation_id_in_payload(self):
        """First call should not include conversation_id if context has none."""
        mock = MockHttpClient(response_data={"message": "Hi", "conversation_id": "new-conv"})
        agent = self._make_agent(mock)

        with UseConversation():
            agent.chat(ChatRequest(user_prompt="Hello"))

        _, payload, _ = mock.calls[0]
        self.assertTrue(payload["use_conversation"])
        self.assertNotIn("conversation_id", payload)

    def test_does_not_mutate_chat_request(self):
        """UseConversation should modify payload, not the ChatRequest object."""
        mock = MockHttpClient(response_data={"message": "Hi", "conversation_id": "conv-1"})
        agent = self._make_agent(mock)
        request = ChatRequest(user_prompt="Hello")

        with UseConversation(conversation_id="conv-1"):
            agent.chat(request)

        # The original ChatRequest should not be mutated
        self.assertFalse(request.use_conversation)
        self.assertIsNone(request.conversation_id)


# =============================================================================
# Integration tests: Agent.chat_many + UseConversation
# =============================================================================


class TestAgentChatManyWithUseConversation(unittest.TestCase):
    """Integration tests for Agent.chat_many() with UseConversation."""

    def _make_agent(self, http_client: HttpClient) -> Agent:
        return Agent(
            agent_id="test-agent",
            options=AgentOptions(retry_max_retries=0, max_workers=3),
            http_client=http_client,
        )

    def test_context_propagated_to_worker_threads(self):
        """UseConversation context should be propagated to chat_many worker threads."""
        mock = MockHttpClient(response_data={"message": "Hi", "conversation_id": "batch-conv"})
        agent = self._make_agent(mock)

        with UseConversation(conversation_id="batch-conv"):
            requests_list = [
                ChatRequest(user_prompt=f"Q{i}") for i in range(3)
            ]
            responses = agent.chat_many(requests_list)

        self.assertEqual(len(responses), 3)
        # All payloads should have the conversation context applied
        for _, payload, _ in mock.calls:
            self.assertTrue(payload["use_conversation"])
            self.assertEqual(payload["conversation_id"], "batch-conv")

    def test_without_conversation_id_each_request_starts_its_own_conversation(self):
        """When UseConversation has no initial conversation_id, chat_many sends all
        requests concurrently without a conversation_id — each request starts its
        own independent conversation on the server. The first response back sets
        the context, but it's too late for the other in-flight requests."""
        num_requests = 3
        barrier = threading.Barrier(num_requests)

        mock = MockHttpClient(
            responses=[
                {"message": "R1", "conversation_id": "conv-from-r1"},
                {"message": "R2", "conversation_id": "conv-from-r2"},
                {"message": "R3", "conversation_id": "conv-from-r3"},
            ]
        )
        # Force all workers to reach the HTTP POST before any response returns,
        # so that all payloads are built while conversation_id is still None.
        original_post = mock.post

        def synchronized_post(url, data=None, headers=None, timeout=30):
            barrier.wait()  # wait for all workers to be in-flight
            return original_post(url, data, headers, timeout)

        mock.post = synchronized_post  # type: ignore[method-assign]
        agent = self._make_agent(mock)

        with UseConversation() as conv:
            requests_list = [
                ChatRequest(user_prompt=f"Q{i}") for i in range(num_requests)
            ]
            responses = agent.chat_many(requests_list)

        self.assertEqual(len(responses), 3)

        # All payloads were sent with use_conversation=True but WITHOUT conversation_id,
        # because conv_ctx.conversation_id was None when all workers started concurrently
        for _, payload, _ in mock.calls:
            self.assertTrue(payload["use_conversation"])
            self.assertNotIn("conversation_id", payload)

        # After chat_many, the context captured ONE conversation_id (from whichever responded first)
        self.assertIsNotNone(conv.conversation_id)

    def test_without_conversation_id_captured_id_is_usable_in_subsequent_calls(self):
        """After chat_many auto-captures a conversation_id, subsequent chat() calls
        within the same UseConversation block use it."""
        mock = MockHttpClient(
            responses=[
                {"message": "Batch R1", "conversation_id": "captured-conv"},
                {"message": "Batch R2", "conversation_id": "captured-conv"},
                {"message": "Follow up", "conversation_id": "captured-conv"},
            ]
        )
        agent = self._make_agent(mock)

        with UseConversation() as conv:
            agent.chat_many([
                ChatRequest(user_prompt="Q1"),
                ChatRequest(user_prompt="Q2"),
            ])
            self.assertIsNotNone(conv.conversation_id)

            # Subsequent chat() should use the captured conversation_id
            agent.chat(ChatRequest(user_prompt="Follow up"))

        # The last call (chat) should have the captured conversation_id
        _, followup_payload, _ = mock.calls[2]
        self.assertTrue(followup_payload["use_conversation"])
        self.assertEqual(followup_payload["conversation_id"], "captured-conv")


# =============================================================================
# Unit tests: UseConversation.with_generated_id()
# =============================================================================


class TestUseConversationWithGeneratedId(unittest.TestCase):
    """Tests for UseConversation.with_generated_id() factory method."""

    def test_returns_use_conversation_with_non_none_id(self):
        """Should return a UseConversation whose context has a non-None conversation_id."""
        with UseConversation.with_generated_id() as conv:
            self.assertIsNotNone(conv.conversation_id)

    def test_generated_id_is_valid_ulid(self):
        """Should generate a valid ULID string (26 uppercase Crockford Base32 characters)."""
        from ulid import ULID

        with UseConversation.with_generated_id() as conv:
            # Should parse without error
            parsed = ULID.from_str(conv.conversation_id)
            self.assertEqual(str(parsed), conv.conversation_id)

    def test_successive_calls_produce_different_ids(self):
        """Each call should generate a unique ID."""
        ids = set()
        for _ in range(10):
            with UseConversation.with_generated_id() as conv:
                ids.add(conv.conversation_id)

        self.assertEqual(len(ids), 10)

    def test_generated_id_sent_in_first_request_payload(self):
        """Integration: with_generated_id() should send the generated ID in the very first request."""
        mock = MockHttpClient(response_data={"message": "Hi", "conversation_id": "server-conv"})
        agent = Agent(
            agent_id="test-agent",
            options=AgentOptions(retry_max_retries=0),
            http_client=mock,
        )

        with UseConversation.with_generated_id() as conv:
            generated_id = conv.conversation_id
            agent.chat(ChatRequest(user_prompt="Hello"))

        _, payload, _ = mock.calls[0]
        self.assertTrue(payload["use_conversation"])
        self.assertEqual(payload["conversation_id"], generated_id)


# =============================================================================
# Tests: chat_many() warning when inside UseConversation without conversation_id
# =============================================================================


class TestChatManyConversationWarning(unittest.TestCase):
    """Tests for the warning logged when chat_many() is called inside UseConversation without a pre-set conversation_id."""

    def _make_agent(self, http_client: HttpClient) -> Agent:
        return Agent(
            agent_id="test-agent",
            options=AgentOptions(retry_max_retries=0, max_workers=3),
            http_client=http_client,
        )

    def test_warns_when_no_conversation_id_and_multiple_requests(self):
        """Should log a warning when inside UseConversation without conversation_id and >1 requests."""
        mock = MockHttpClient(response_data={"message": "Hi", "conversation_id": "conv-1"})
        agent = self._make_agent(mock)

        with self.assertLogs("stkai.agents._agent", level="WARNING") as cm:
            with UseConversation():
                agent.chat_many([
                    ChatRequest(user_prompt="Q1"),
                    ChatRequest(user_prompt="Q2"),
                ])

        self.assertTrue(
            any("with_generated_id()" in msg for msg in cm.output),
            f"Expected warning mentioning with_generated_id(), got: {cm.output}"
        )

    def test_no_warning_when_conversation_id_is_set(self):
        """Should NOT warn when UseConversation has a pre-set conversation_id."""

        mock = MockHttpClient(response_data={"message": "Hi", "conversation_id": "conv-1"})
        agent = self._make_agent(mock)

        with UseConversation(conversation_id="pre-set-id"):
            # Capture all logs at WARNING level — we expect none from chat_many
            with self.assertNoLogs("stkai.agents._agent", level="WARNING"):
                agent.chat_many([
                    ChatRequest(user_prompt="Q1"),
                    ChatRequest(user_prompt="Q2"),
                ])

    def test_no_warning_when_single_request(self):
        """Should NOT warn when there's only one request (no race condition)."""
        mock = MockHttpClient(response_data={"message": "Hi", "conversation_id": "conv-1"})
        agent = self._make_agent(mock)

        with UseConversation():
            with self.assertNoLogs("stkai.agents._agent", level="WARNING"):
                agent.chat_many([
                    ChatRequest(user_prompt="Q1"),
                ])

    def test_no_warning_outside_use_conversation(self):
        """Should NOT warn when not inside UseConversation."""
        mock = MockHttpClient(response_data={"message": "Hi"})
        agent = self._make_agent(mock)

        with self.assertNoLogs("stkai.agents._agent", level="WARNING"):
            agent.chat_many([
                ChatRequest(user_prompt="Q1"),
                ChatRequest(user_prompt="Q2"),
            ])


if __name__ == "__main__":
    unittest.main()
