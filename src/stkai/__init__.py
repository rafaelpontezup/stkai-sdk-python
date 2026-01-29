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
    >>> print(response.result)

Global Configuration:
    >>> from stkai import STKAI
    >>>
    >>> # Pre-loaded with defaults + env vars
    >>> timeout = STKAI.config.agent.request_timeout
    >>>
    >>> # Custom configuration
    >>> STKAI.configure(
    ...     auth={"client_id": "x", "client_secret": "y"},
    ...     rqc={"request_timeout": 60, "max_retries": 5},
    ...     agent={"request_timeout": 120},
    ...     rate_limit={"enabled": True, "strategy": "token_bucket", "max_requests": 10},
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

CLI:
    - StkCLI: Abstraction for StackSpot CLI (oscli) detection and configuration.

Configuration:
    - STKAI: Global SDK singleton for configuration.
    - STKAIConfig: Root configuration dataclass.
    - AuthConfig: Authentication configuration.
    - RqcConfig: RemoteQuickCommand configuration.
    - AgentConfig: Agent configuration.
    - RateLimitConfig: Rate limiting configuration.
    - RateLimitStrategy: Type alias for valid rate limiting strategies.
    - ConfigEnvVarError: Exception raised when env var parsing fails.
    - ConfigValidationError: Exception raised when config validation fails.

Authentication (Standalone):
    - AuthProvider: Abstract base class for authentication providers.
    - ClientCredentialsAuthProvider: OAuth2 client credentials implementation.
    - AuthenticationError: Exception raised when authentication fails.
    - create_standalone_auth: Helper to create auth provider from config.

HTTP Client:
    - HttpClient: Abstract base class for HTTP clients.
    - EnvironmentAwareHttpClient: Auto-detects environment (CLI or standalone). Default.
    - StkCLIHttpClient: HTTP client using StackSpot CLI for authentication.
    - StandaloneHttpClient: HTTP client using AuthProvider for standalone auth.
    - TokenBucketRateLimitedHttpClient: HTTP client decorator with rate limiting.
    - AdaptiveRateLimitedHttpClient: HTTP client decorator with adaptive rate limiting.
    - CongestionControlledHttpClient: HTTP client decorator with congestion control (EXPERIMENTAL).
    - ClientSideRateLimitError: Base exception for client-side rate limiting errors.
    - TokenAcquisitionTimeoutError: Exception raised when rate limiter exceeds max_wait_time.
    - ServerSideRateLimitError: Exception raised when server returns HTTP 429.

Retry:
    - Retrying: Context manager for retry with exponential backoff.
    - RetryableError: Base class for exceptions that trigger automatic retry.
    - MaxRetriesExceededError: Exception raised when all retry attempts are exhausted.
"""

from importlib.metadata import version as _get_version

__version__ = _get_version("stkai")

from stkai._auth import (
    AuthenticationError,
    AuthProvider,
    ClientCredentialsAuthProvider,
    create_standalone_auth,
)
from stkai._cli import StkCLI
from stkai._config import (
    STKAI,
    AgentConfig,
    AuthConfig,
    ConfigEntry,
    ConfigEnvVarError,
    ConfigValidationError,
    RateLimitConfig,
    RateLimitStrategy,
    RqcConfig,
    SdkConfig,
    STKAIConfig,
)
from stkai._http import (
    EnvironmentAwareHttpClient,
    HttpClient,
    StandaloneHttpClient,
    StkCLIHttpClient,
)
from stkai._rate_limit import (
    AdaptiveRateLimitedHttpClient,
    ClientSideRateLimitError,
    CongestionControlledHttpClient,
    ServerSideRateLimitError,
    TokenAcquisitionTimeoutError,
    TokenBucketRateLimitedHttpClient,
)
from stkai._retry import (
    MaxRetriesExceededError,
    RetryableError,
    Retrying,
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
    RqcOptions,
    RqcRequest,
    RqcResponse,
)

__all__ = [
    "__version__",
    # CLI
    "StkCLI",
    # Configuration
    "STKAI",
    "STKAIConfig",
    "SdkConfig",
    "ConfigEntry",
    "ConfigEnvVarError",
    "ConfigValidationError",
    "AuthConfig",
    "RqcConfig",
    "AgentConfig",
    "RateLimitConfig",
    "RateLimitStrategy",
    # Authentication (Standalone)
    "AuthProvider",
    "ClientCredentialsAuthProvider",
    "AuthenticationError",
    "create_standalone_auth",
    # HTTP Client
    "HttpClient",
    "EnvironmentAwareHttpClient",
    "StkCLIHttpClient",
    "StandaloneHttpClient",
    "TokenBucketRateLimitedHttpClient",
    "AdaptiveRateLimitedHttpClient",
    "CongestionControlledHttpClient",
    "ClientSideRateLimitError",
    "TokenAcquisitionTimeoutError",
    "ServerSideRateLimitError",
    # Retry
    "Retrying",
    "RetryableError",
    "MaxRetriesExceededError",
    # RQC
    "RemoteQuickCommand",
    "RqcOptions",
    "RqcRequest",
    "RqcResponse",
    "RqcExecutionStatus",
    # Agents
    "Agent",
    "ChatRequest",
    "ChatResponse",
    "ChatStatus",
]
