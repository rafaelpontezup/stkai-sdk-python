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
    token usage, status, and any error information.

    Attributes:
        request: The original request that generated this response.
        status: The status of the response (SUCCESS, ERROR, TIMEOUT).
        message: The Agent's response message (raw text from API).
        result: The processed result from the result handler.
            By default (RawResultHandler), this is the same as message.
            When using JsonResultHandler, this is the parsed JSON object.
        stop_reason: Reason why the Agent stopped generating (e.g., "stop").
        tokens: Token usage information.
        conversation_id: ID for continuing the conversation.
        knowledge_sources: List of knowledge source IDs used in the response.
        error: Error message if the request failed.
        raw_response: The raw API response dictionary.

    Example:
        >>> if response.is_success():
        ...     print(response.message)  # Raw text
        ...     print(response.result)   # Processed by handler
        ...     print(f"Tokens used: {response.tokens.total}")
        ... elif response.is_timeout():
        ...     print("Request timed out")
        ... else:
        ...     print(f"Error: {response.error}")
    """
    request: ChatRequest
    status: ChatStatus
    message: str | None = None
    result: Any | None = None
    stop_reason: str | None = None
    tokens: ChatTokenUsage | None = None
    conversation_id: str | None = None
    knowledge_sources: list[str] = field(default_factory=list)
    error: str | None = None
    raw_response: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        assert self.request, "Request cannot be empty."
        assert self.status, "Status cannot be empty."

    def is_success(self) -> bool:
        """Returns True if the response was successful."""
        return self.status == ChatStatus.SUCCESS

    def is_error(self) -> bool:
        """Returns True if there was an error."""
        return self.status == ChatStatus.ERROR

    def is_timeout(self) -> bool:
        """Returns True if the request timed out."""
        return self.status == ChatStatus.TIMEOUT
