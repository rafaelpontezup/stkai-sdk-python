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

Global Configuration:
    >>> from stkai import STKAI_CONFIG, configure_stkai
    >>>
    >>> # Pre-loaded with defaults + env vars
    >>> timeout = STKAI_CONFIG.agent.request_timeout
    >>>
    >>> # Custom configuration
    >>> configure_stkai(
    ...     auth={"client_id": "x", "client_secret": "y"},
    ...     rqc={"request_timeout": 60, "max_retries": 5},
    ...     agent={"request_timeout": 120},
    ... )

Main Classes:
    - RemoteQuickCommand: Client for executing Remote Quick Commands.
    - RqcRequest: Represents a request to be sent to the RQC API.
    - RqcResponse: Represents the response received from the RQC API.
    - RqcExecutionStatus: Enum with execution lifecycle statuses.
    - Agent: Client for interacting with StackSpot AI Agents.
    - ChatRequest: Represents a chat request to be sent to an Agent.
    - ChatResponse: Represents the chat response received from an Agent.
    - ChatStatus: Enum with chat response statuses.

Configuration:
    - STKAI_CONFIG: Global configuration instance (pre-loaded).
    - configure_stkai: Function to customize global settings.
    - StkAiConfig: Root configuration dataclass.
    - AuthConfig: Authentication configuration.
    - RqcConfig: RemoteQuickCommand configuration.
    - AgentConfig: Agent configuration.
"""

__version__ = "0.1.0"

from stkai._config import (
    STKAI_CONFIG,
    AgentConfig,
    AuthConfig,
    RqcConfig,
    StkAiConfig,
    configure_stkai,
)
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
    # Configuration
    "STKAI_CONFIG",
    "configure_stkai",
    "StkAiConfig",
    "AuthConfig",
    "RqcConfig",
    "AgentConfig",
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
