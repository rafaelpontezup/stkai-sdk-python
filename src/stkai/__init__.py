"""
StackSpot AI SDK for Python.

A Python SDK for integrating with StackSpot AI services,
including Remote Quick Commands (RQC) and Agents.

Quick Start (RQC):
    >>> from stkai import RemoteQuickCommand, RqcRequest
    >>> rqc = RemoteQuickCommand(slug_name="my-quick-command")
    >>> request = RqcRequest(payload={"prompt": "Hello, AI!"})
    >>> response = rqc.execute(request)
    >>> print(response.result)

Quick Start (Agent):
    >>> from stkai import Agent, ChatRequest
    >>> agent = Agent(agent_id="my-agent-slug")
    >>> response = agent.chat(ChatRequest(user_prompt="What is SOLID?"))
    >>> print(response.message)

Main Classes:
    - RemoteQuickCommand: Client for executing Remote Quick Commands.
    - RqcRequest: Represents a request to be sent to the RQC API.
    - RqcResponse: Represents the response received from the RQC API.
    - RqcExecutionStatus: Enum with execution lifecycle statuses.
    - Agent: Client for interacting with StackSpot AI Agents.
    - ChatRequest: Represents a chat request to be sent to an Agent.
    - ChatResponse: Represents the chat response received from an Agent.
    - ChatStatus: Enum with chat response statuses.
"""

__version__ = "0.1.0"

from stkai.agents import (
    Agent,
    ChatRequest,
    ChatResponse,
    ChatStatus,
)
from stkai.rqc import (
    RemoteQuickCommand,
    RqcExecutionStatus,
    RqcRequest,
    RqcResponse,
)

__all__ = [
    "__version__",
    # RQC
    "RemoteQuickCommand",
    "RqcRequest",
    "RqcResponse",
    "RqcExecutionStatus",
    # Agents
    "Agent",
    "ChatRequest",
    "ChatResponse",
    "ChatStatus",
]
