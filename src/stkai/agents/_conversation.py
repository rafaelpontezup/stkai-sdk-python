"""
Conversation context manager for StackSpot AI Agents.

This module provides `UseConversation`, a context manager that automatically
tracks and propagates `conversation_id` across all `Agent.chat()` calls
within the block.

Before:
    >>> r1 = agent.chat(ChatRequest(user_prompt="Hello", use_conversation=True))
    >>> conv_id = r1.conversation_id
    >>> r2 = agent.chat(ChatRequest(user_prompt="Follow up", conversation_id=conv_id, use_conversation=True))

After:
    >>> with UseConversation() as conv:
    ...     r1 = agent.chat(ChatRequest(user_prompt="Hello"))
    ...     r2 = agent.chat(ChatRequest(user_prompt="Follow up"))  # auto-uses conv_id from r1

Inspired by DBOS's `SetWorkflowID` context manager.
"""

import dataclasses
import functools
import logging
import threading
from collections.abc import Callable
from contextvars import ContextVar, Token
from typing import Any, TypeVar

from ulid import ULID

from stkai.agents._models import ChatRequest

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class ConversationContext:
    """
    Holds the mutable conversation state within a `UseConversation` block.

    Thread-safe: ``_update_if_absent()`` uses a lock for safe auto-tracking
    from concurrent threads (e.g., ``chat_many()``).

    Attributes:
        conversation_id: The current conversation ID, or None if not yet captured.
    """

    def __init__(self, conversation_id: str | None = None) -> None:
        self._conversation_id = conversation_id
        self._lock = threading.Lock()

    @property
    def conversation_id(self) -> str | None:
        return self._conversation_id

    def has_conversation_id(self) -> bool:
        """Returns True if a conversation_id is already set."""
        return self._conversation_id is not None

    def enrich(self, request: ChatRequest) -> ChatRequest:
        """
        Returns a new ``ChatRequest`` enriched with the current conversation state.

        Sets ``use_conversation=True`` and ``conversation_id`` (if already captured).
        If the request already has a ``conversation_id``, returns it unchanged
        (explicit takes precedence).

        The original request is never mutated.

        Example:
            >>> with UseConversation() as conv:
            ...     request = conv.enrich(ChatRequest(user_prompt="Hello"))
            ...     response = agent.chat(request)
            ...     # response.request.conversation_id reflects what was sent
        """
        if request.conversation_id:
            return request
        return dataclasses.replace(
            request,
            use_conversation=True,
            conversation_id=self.conversation_id,
        )

    def update_if_absent(self, conversation_id: str) -> str:
        """
        Set the conversation_id only if not already set. Returns the
        current conversation_id (either the existing one or the newly set one).

        Thread-safe via lock so concurrent ``chat_many()`` workers
        can safely race to capture the first response's conversation_id.
        """
        if self._conversation_id is not None:
            return self._conversation_id
        with self._lock:
            if self._conversation_id is None:
                self._conversation_id = conversation_id
            return self._conversation_id


class ConversationScope:
    """
    Manages the active ``ConversationContext`` for the current execution scope.

    Encapsulates the ``ContextVar`` that holds the conversation state,
    providing static methods to get, set, and reset it. Used internally
    by ``UseConversation`` and ``Agent._do_chat()``.
    """

    _current: ContextVar[ConversationContext | None] = ContextVar(
        "_current_conversation", default=None
    )

    @staticmethod
    def get_current() -> ConversationContext | None:
        """Returns the active ``ConversationContext``, or None if outside a ``UseConversation`` block."""
        return ConversationScope._current.get()

    @staticmethod
    def _set(ctx: ConversationContext) -> Token[ConversationContext | None]:
        """Sets the active context. Returns a token for later reset."""
        return ConversationScope._current.set(ctx)

    @staticmethod
    def _reset(token: Token[ConversationContext | None]) -> None:
        """Restores the previous context using the token from ``_set()``."""
        ConversationScope._current.reset(token)

    @staticmethod
    def propagate(fn: Callable[..., _T]) -> Callable[..., _T]:
        """
        Wraps ``fn`` so it runs with the current conversation context.

        Captures the active ``ConversationContext`` at wrap-time (caller thread)
        and installs it at call-time (worker thread). Only the conversation
        context is propagated — not the entire ``contextvars`` snapshot.

        If no conversation context is active, returns ``fn`` unchanged (no-op).

        Designed for ``ThreadPoolExecutor.submit()``::

            executor.submit(ConversationScope.propagate(self._do_chat), request=req)
        """
        conv_ctx = ConversationScope.get_current()
        if conv_ctx is None:
            return fn

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> _T:
            token = ConversationScope._set(conv_ctx)
            try:
                return fn(*args, **kwargs)
            finally:
                ConversationScope._reset(token)

        return wrapper


class UseConversation:
    """
    Context manager that automatically tracks and propagates ``conversation_id``
    across all ``Agent.chat()`` calls within the block.

    Precedence rules:
        1. ``ChatRequest.conversation_id`` (explicit) wins over ``UseConversation`` (implicit).
        2. ``use_conversation=True`` is automatically set inside the block.
        3. If no ``conversation_id`` is provided, captures from the first successful response.

    Nestable: inner ``UseConversation`` overrides outer; restores on exit.

    Args:
        conversation_id: Optional initial conversation ID. If None, auto-captures
            from the first successful ``Agent.chat()`` response.

    Example:
        >>> with UseConversation() as conv:
        ...     r1 = agent.chat(ChatRequest(user_prompt="Hello"))
        ...     print(conv.conversation_id)  # captured from r1
        ...     r2 = agent.chat(ChatRequest(user_prompt="Follow up"))
    """

    def __init__(self, conversation_id: str | None = None) -> None:
        if conversation_id is not None:
            self._warn_if_not_ulid(conversation_id)
        self._context = ConversationContext(conversation_id=conversation_id)
        self._token: Token[ConversationContext | None] | None = None

    @classmethod
    def with_generated_id(cls) -> "UseConversation":
        """
        Factory method that creates a ``UseConversation`` with a pre-generated
        conversation ID in ULID format.

        This is useful when you want the conversation ID available before
        the first request, especially with ``chat_many()`` where concurrent
        requests would otherwise race to capture the server-assigned ID.

        Example:
            >>> with UseConversation.with_generated_id() as conv:
            ...     print(conv.conversation_id)  # ULID already available
            ...     agent.chat(ChatRequest(user_prompt="Hello"))
        """
        return cls(conversation_id=str(ULID()))

    def __enter__(self) -> ConversationContext:
        self._token = ConversationScope._set(self._context)
        return self._context

    def __exit__(self, *args: object) -> None:
        assert self._token is not None, \
            "UseConversation.__exit__ called without __enter__"
        ConversationScope._reset(self._token)
        self._token = None

    @staticmethod
    def _warn_if_not_ulid(conversation_id: str) -> None:
        """Logs a warning if ``conversation_id`` is not a valid ULID."""
        try:
            ULID.from_str(conversation_id)
        except ValueError:
            logger.warning(
                "⚠️ conversation_id '%s' is not a valid ULID. "
                "The StackSpot AI API currently expects ULID format — "
                "an invalid ID may be ignored by the server or start a new conversation scope. "
                "Consider using UseConversation.with_generated_id() for automatic ULID generation.",
                conversation_id,
            )
