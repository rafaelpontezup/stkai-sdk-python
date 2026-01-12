"""
Global configuration for the stkai SDK.

This module provides a simple configuration system following Convention over Configuration (CoC).
Users can optionally call configure() at application startup to customize defaults.
If not called, sensible defaults are used.

Hierarchy of precedence (highest to lowest):
1. *Options passed to client constructors
2. Values set via configure()
3. Environment variables (STKAI_*)
4. Hardcoded defaults
"""

from __future__ import annotations

import os
from typing import TypedDict


class StkAiConfig(TypedDict, total=False):
    """
    Global configuration for the stkai SDK.

    This is the top-level configuration that can be passed to configure().
    It contains authentication credentials (for future use) and per-client
    configurations for RemoteQuickCommand and Agent.

    Attributes:
        client_id: StackSpot client ID for authentication.
            Env var: STKAI_CLIENT_ID
            Default: None (uses StackSpot CLI for auth)

        client_secret: StackSpot client secret for authentication.
            Env var: STKAI_CLIENT_SECRET
            Default: None (uses StackSpot CLI for auth)

        rqc: Configuration specific to RemoteQuickCommand clients.
            See RqcConfig for available options.

        agent: Configuration specific to Agent clients.
            See AgentConfig for available options.

    Example:
        >>> import stkai
        >>> stkai.configure(
        ...     client_id="my-client-id",
        ...     client_secret="my-client-secret",
        ...     rqc={"request_timeout": 60, "max_retries": 5},
        ...     agent={"request_timeout": 120},
        ... )
    """

    client_id: str
    client_secret: str
    rqc: RqcConfig
    agent: AgentConfig


class RqcConfig(TypedDict, total=False):
    """
    Configuration specific to RemoteQuickCommand.

    These settings are used as defaults when creating RemoteQuickCommand instances
    without explicitly providing CreateExecutionOptions or GetResultOptions.

    Attributes:
        base_url: Base URL for the RQC API.
            Env var: STKAI_RQC_BASE_URL
            Default: Retrieved from StackSpot CLI (oscli).

        request_timeout: HTTP request timeout in seconds for API calls.
            Env var: STKAI_RQC_REQUEST_TIMEOUT
            Default: 30

        max_retries: Maximum retry attempts for failed create-execution calls.
            Env var: STKAI_RQC_MAX_RETRIES
            Default: 3

        backoff_factor: Multiplier for exponential backoff between retries
            (delay = factor * 2^attempt).
            Env var: STKAI_RQC_BACKOFF_FACTOR
            Default: 0.5

        poll_interval: Seconds to wait between polling status checks.
            Env var: STKAI_RQC_POLL_INTERVAL
            Default: 10.0

        poll_max_duration: Maximum seconds to wait for execution completion
            before timing out.
            Env var: STKAI_RQC_POLL_MAX_DURATION
            Default: 600.0 (10 minutes)

        overload_timeout: Maximum seconds to tolerate CREATED status before
            assuming server overload.
            Env var: STKAI_RQC_OVERLOAD_TIMEOUT
            Default: 60.0

        max_workers: Maximum number of concurrent threads for execute_many().
            Env var: STKAI_RQC_MAX_WORKERS
            Default: 8

    Example:
        >>> import stkai
        >>> stkai.configure(
        ...     rqc={
        ...         "request_timeout": 60,
        ...         "max_retries": 5,
        ...         "poll_interval": 15.0,
        ...     }
        ... )
    """

    base_url: str
    request_timeout: int
    max_retries: int
    backoff_factor: float
    poll_interval: float
    poll_max_duration: float
    overload_timeout: float
    max_workers: int


class AgentConfig(TypedDict, total=False):
    """
    Configuration specific to Agent.

    These settings are used as defaults when creating Agent instances
    without explicitly providing AgentOptions.

    Attributes:
        base_url: Base URL for the Agent API.
            Env var: STKAI_AGENT_BASE_URL
            Default: "https://genai-inference-app.stackspot.com"

        request_timeout: HTTP request timeout in seconds for chat requests.
            Env var: STKAI_AGENT_REQUEST_TIMEOUT
            Default: 60

    Example:
        >>> import stkai
        >>> stkai.configure(
        ...     agent={
        ...         "request_timeout": 120,
        ...         "base_url": "https://custom-agent-api.example.com",
        ...     }
        ... )
    """

    base_url: str
    request_timeout: int


# Default values
_RQC_DEFAULTS: RqcConfig = {
    "request_timeout": 30,
    "max_retries": 3,
    "backoff_factor": 0.5,
    "poll_interval": 10.0,
    "poll_max_duration": 600.0,
    "overload_timeout": 60.0,
    "max_workers": 8,
}

_AGENT_DEFAULTS: AgentConfig = {
    "base_url": "https://genai-inference-app.stackspot.com",
    "request_timeout": 60,
}

# Global state
_config: StkAiConfig = {}


def configure(
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    rqc: RqcConfig | None = None,
    agent: AgentConfig | None = None,
) -> None:
    """
    Configure global SDK settings.

    Call this at application startup to customize defaults.
    If not called, sensible defaults are used (Convention over Configuration).

    Args:
        client_id: StackSpot client ID for authentication (future use).
        client_secret: StackSpot client secret for authentication (future use).
        rqc: Configuration for RemoteQuickCommand clients.
        agent: Configuration for Agent clients.

    Example:
        >>> import stkai
        >>> stkai.configure(
        ...     rqc={"request_timeout": 60, "max_retries": 5},
        ...     agent={"request_timeout": 120},
        ... )
    """
    global _config
    if client_id is not None:
        _config["client_id"] = client_id
    if client_secret is not None:
        _config["client_secret"] = client_secret
    if rqc is not None:
        _config["rqc"] = {**_config.get("rqc", {}), **rqc}
    if agent is not None:
        _config["agent"] = {**_config.get("agent", {}), **agent}


def get_rqc_config() -> RqcConfig:
    """
    Get the merged RQC configuration.

    Returns config merged in order: defaults < env vars < configure().
    """
    return {**_RQC_DEFAULTS, **_get_rqc_from_env(), **_config.get("rqc", {})}


def get_agent_config() -> AgentConfig:
    """
    Get the merged Agent configuration.

    Returns config merged in order: defaults < env vars < configure().
    """
    return {**_AGENT_DEFAULTS, **_get_agent_from_env(), **_config.get("agent", {})}


def get_credentials() -> tuple[str | None, str | None]:
    """
    Get credentials with fallback to environment variables.

    Returns:
        Tuple of (client_id, client_secret). Either or both may be None.
    """
    return (
        _config.get("client_id") or os.environ.get("STKAI_CLIENT_ID"),
        _config.get("client_secret") or os.environ.get("STKAI_CLIENT_SECRET"),
    )


def has_credentials() -> bool:
    """
    Check if credentials are configured (for future use).

    Returns:
        True if both client_id and client_secret are set.
    """
    client_id, client_secret = get_credentials()
    return bool(client_id and client_secret)


def reset() -> None:
    """
    Reset configuration to defaults.

    Useful for testing to ensure clean state between tests.
    """
    global _config
    _config = {}


def _get_rqc_from_env() -> RqcConfig:
    """Read RQC config values from environment variables."""
    result: RqcConfig = {}
    env_mapping: list[tuple[str, str, type]] = [
        ("base_url", "STKAI_RQC_BASE_URL", str),
        ("request_timeout", "STKAI_RQC_REQUEST_TIMEOUT", int),
        ("max_retries", "STKAI_RQC_MAX_RETRIES", int),
        ("backoff_factor", "STKAI_RQC_BACKOFF_FACTOR", float),
        ("poll_interval", "STKAI_RQC_POLL_INTERVAL", float),
        ("poll_max_duration", "STKAI_RQC_POLL_MAX_DURATION", float),
        ("overload_timeout", "STKAI_RQC_OVERLOAD_TIMEOUT", float),
        ("max_workers", "STKAI_RQC_MAX_WORKERS", int),
    ]
    for key, env_var, type_fn in env_mapping:
        if value := os.environ.get(env_var):
            result[key] = type_fn(value)  # type: ignore[literal-required]
    return result


def _get_agent_from_env() -> AgentConfig:
    """Read Agent config values from environment variables."""
    result: AgentConfig = {}
    env_mapping: list[tuple[str, str, type]] = [
        ("base_url", "STKAI_AGENT_BASE_URL", str),
        ("request_timeout", "STKAI_AGENT_REQUEST_TIMEOUT", int),
    ]
    for key, env_var, type_fn in env_mapping:
        if value := os.environ.get(env_var):
            result[key] = type_fn(value)  # type: ignore[literal-required]
    return result
