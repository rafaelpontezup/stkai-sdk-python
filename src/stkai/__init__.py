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

Authentication (Standalone):
    - AuthProvider: Abstract base class for authentication providers.
    - ClientCredentialsAuthProvider: OAuth2 client credentials implementation.
    - AuthenticationError: Exception raised when authentication fails.
    - create_standalone_auth: Helper to create auth provider from config.

HTTP Client:
    - HttpClient: Abstract base class for HTTP clients.
    - StkCLIHttpClient: HTTP client using StackSpot CLI for authentication.
    - StandaloneHttpClient: HTTP client using AuthProvider for standalone auth.
    - RateLimitedHttpClient: HTTP client decorator with rate limiting.
    - AdaptiveRateLimitedHttpClient: HTTP client decorator with adaptive rate limiting.
    - RateLimitTimeoutError: Exception raised when rate limiter exceeds max_wait_time.
"""

__version__ = "0.1.0"

from stkai._auth import (
    AuthenticationError,
    AuthProvider,
    ClientCredentialsAuthProvider,
    create_standalone_auth,
)
from stkai._config import (
    STKAI_CONFIG,
    AgentConfig,
    AuthConfig,
    RqcConfig,
    StkAiConfig,
    configure_stkai,
)
from stkai._http import (
    AdaptiveRateLimitedHttpClient,
    HttpClient,
    RateLimitedHttpClient,
    RateLimitTimeoutError,
    StandaloneHttpClient,
    StkCLIHttpClient,
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
    # Authentication (Standalone)
    "AuthProvider",
    "ClientCredentialsAuthProvider",
    "AuthenticationError",
    "create_standalone_auth",
    # HTTP Client
    "HttpClient",
    "StkCLIHttpClient",
    "StandaloneHttpClient",
    "RateLimitedHttpClient",
    "AdaptiveRateLimitedHttpClient",
    "RateLimitTimeoutError",
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
