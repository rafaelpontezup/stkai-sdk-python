"""
Data models for StackSpot AI Agents.

This module contains the data classes used to represent requests and responses
when interacting with StackSpot AI Agents API.
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChatStatus(Enum):
    """
    Status of a chat response.

    Attributes:
        SUCCESS: Response received successfully from the Agent.
        ERROR: Client-side error (HTTP error, network issue, parsing error).
        TIMEOUT: Request timed out waiting for response.
    """
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"

    @classmethod
    def from_exception(cls, exc: Exception) -> "ChatStatus":
        """
        Determine the appropriate status for an exception.

        Args:
            exc: The exception that occurred during the chat request.

        Returns:
            TIMEOUT for timeout exceptions, ERROR for all others.

        Example:
            >>> try:
            ...     response = agent.chat(request)
            ... except Exception as e:
            ...     status = ChatStatus.from_exception(e)
            ...     # status is TIMEOUT if e is a timeout, ERROR otherwise
        """
        from stkai._utils import is_timeout_exception
        return cls.TIMEOUT if is_timeout_exception(exc) else cls.ERROR


@dataclass(frozen=True)
class ChatTokenUsage:
    """
    Token usage information from a chat response.

    Tracks the number of tokens consumed in different stages of processing.

    Attributes:
        user: Tokens from the user prompt.
        enrichment: Tokens from knowledge source enrichment.
        output: Tokens in the generated output.

    Example:
        >>> usage = ChatTokenUsage(user=100, enrichment=50, output=200)
        >>> print(f"Total tokens: {usage.total}")
        Total tokens: 350
    """
    user: int
    enrichment: int
    output: int

    @property
    def total(self) -> int:
        """Returns the total number of tokens used."""
        return self.user + self.enrichment + self.output


@dataclass
class ChatRequest:
    """
    Represents a chat request to be sent to a StackSpot AI Agent.

    This class encapsulates all data needed to send a message to an Agent,
    including the prompt, conversation context, and knowledge source settings.

    Attributes:
        user_prompt: The message/prompt to send to the Agent.
        id: Unique identifier for this request. Auto-generated as UUID if not provided.
        conversation_id: Optional ID to continue an existing conversation.
        use_conversation: Whether to maintain conversation context (default: False).
        use_knowledge_sources: Whether to use StackSpot knowledge sources (default: True).
        return_knowledge_sources: Whether to return knowledge source IDs in response (default: False).
        metadata: Optional dictionary for storing custom metadata.

    Example:
        >>> request = ChatRequest(
        ...     user_prompt="Explain what SOLID principles are",
        ...     use_knowledge_sources=True,
        ...     metadata={"source": "cli"}
        ... )
    """
    user_prompt: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str | None = None
    use_conversation: bool = False
    use_knowledge_sources: bool = True
    return_knowledge_sources: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        assert self.id, "Request ID cannot be empty."
        assert self.user_prompt, "User prompt cannot be empty."

    def to_api_payload(self) -> dict[str, Any]:
        """
        Converts the request to the API payload format.

        Returns:
            Dictionary formatted for the Agent API.
        """
        payload: dict[str, Any] = {
            "user_prompt": self.user_prompt,
            "streaming": False,
            "use_conversation": self.use_conversation,
            "stackspot_knowledge": str(self.use_knowledge_sources).lower(),
            "return_ks_in_response": self.return_knowledge_sources,
        }

        if self.conversation_id:
            payload["conversation_id"] = self.conversation_id

        return payload


@dataclass
class ChatResponse:
    """
    Represents a response from a StackSpot AI Agent.

    This class encapsulates the Agent's response including the message,
    token usage, status, and any error information. Properties are lazily
    extracted from raw_response (source of truth).

    Attributes:
        request: The original request that generated this response.
        status: The status of the response (SUCCESS, ERROR, TIMEOUT).
        result: The processed result from the result handler.
            By default (RawResultHandler), this is the same as raw_result.
            When using JsonResultHandler, this is the parsed JSON object.
        error: Error message if the request failed.
        raw_response: The raw API response dictionary (source of truth for properties).

    Properties (derived from raw_response):
        raw_result: The Agent's response message (raw text from API).
        stop_reason: Reason why the Agent stopped generating (e.g., "stop").
        tokens: Token usage information.
        conversation_id: ID for continuing the conversation.
        knowledge_sources: List of knowledge source IDs used in the response.

    Example:
        >>> if response.is_success():
        ...     print(response.raw_result)  # Raw text
        ...     print(response.result)      # Processed by handler
        ...     print(f"Tokens used: {response.tokens.total}")
        ... elif response.is_timeout():
        ...     print("Request timed out")
        ... else:
        ...     print(f"Error: {response.error}")
    """
    request: ChatRequest
    status: ChatStatus
    result: Any | None = None
    error: str | None = None
    raw_response: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        assert self.request, "Request cannot be empty."
        assert self.status, "Status cannot be empty."

    @property
    def raw_result(self) -> str | None:
        """Extracts the 'message' field from the raw API response."""
        if not self.raw_response:
            return None
        return self.raw_response.get("message")

    @property
    def stop_reason(self) -> str | None:
        """Extracts the 'stop_reason' field from the raw API response."""
        if not self.raw_response:
            return None
        return self.raw_response.get("stop_reason")

    @property
    def tokens(self) -> ChatTokenUsage | None:
        """Extracts and parses token usage from the raw API response."""
        if not self.raw_response:
            return None
        tokens_data = self.raw_response.get("tokens")
        if tokens_data is None:
            return None
        return ChatTokenUsage(
            user=tokens_data.get("user") or 0,
            enrichment=tokens_data.get("enrichment") or 0,
            output=tokens_data.get("output") or 0,
        )

    @property
    def conversation_id(self) -> str | None:
        """Extracts the 'conversation_id' field from the raw API response."""
        if not self.raw_response:
            return None
        return self.raw_response.get("conversation_id")

    @property
    def knowledge_sources(self) -> list[str]:
        """Extracts the 'knowledge_source_id' field from the raw API response."""
        if not self.raw_response:
            return []
        result: list[str] = self.raw_response.get("knowledge_source_id", [])
        return result

    def is_success(self) -> bool:
        """Returns True if the response was successful."""
        return self.status == ChatStatus.SUCCESS

    def is_error(self) -> bool:
        """Returns True if there was an error."""
        return self.status == ChatStatus.ERROR

    def is_timeout(self) -> bool:
        """Returns True if the request timed out."""
        return self.status == ChatStatus.TIMEOUT

    def error_with_details(self) -> dict[str, Any]:
        """Returns a dictionary with error details for non-success responses."""
        if self.is_success():
            return {}

        return {
            "status": self.status,
            "error_message": self.error,
            "response_body": self.raw_response or {},
        }
