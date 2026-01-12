"""
Global configuration for the stkai SDK.

This module provides a simple configuration system following Convention over Configuration (CoC).
Users can optionally call configure() at application startup to customize defaults.
If not called, sensible defaults are used.

Hierarchy of precedence (highest to lowest):
1. *Options passed to client constructors
2. Values set via configure()
3. Environment variables (STKAI_*)
4. Hardcoded defaults (in dataclass fields)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, replace
from typing import Any


@dataclass(frozen=True)
class RqcConfig:
    """
    Configuration specific to RemoteQuickCommand.

    These settings are used as defaults when creating RemoteQuickCommand instances
    without explicitly providing CreateExecutionOptions or GetResultOptions.

    Attributes:
        request_timeout: HTTP request timeout in seconds for API calls.
            Env var: STKAI_RQC_REQUEST_TIMEOUT

        max_retries: Maximum retry attempts for failed create-execution calls.
            Env var: STKAI_RQC_MAX_RETRIES

        backoff_factor: Multiplier for exponential backoff between retries
            (delay = factor * 2^attempt).
            Env var: STKAI_RQC_BACKOFF_FACTOR

        poll_interval: Seconds to wait between polling status checks.
            Env var: STKAI_RQC_POLL_INTERVAL

        poll_max_duration: Maximum seconds to wait for execution completion
            before timing out.
            Env var: STKAI_RQC_POLL_MAX_DURATION

        overload_timeout: Maximum seconds to tolerate CREATED status before
            assuming server overload.
            Env var: STKAI_RQC_OVERLOAD_TIMEOUT

        max_workers: Maximum number of concurrent threads for execute_many().
            Env var: STKAI_RQC_MAX_WORKERS

        base_url: Base URL for the RQC API.
            Env var: STKAI_RQC_BASE_URL

    Example:
        >>> from stkai import config
        >>> config.rqc.request_timeout
        30
        >>> config.rqc.max_retries
        3
    """

    request_timeout: int = 30
    max_retries: int = 3
    backoff_factor: float = 0.5
    poll_interval: float = 10.0
    poll_max_duration: float = 600.0
    overload_timeout: float = 60.0
    max_workers: int = 8
    base_url: str | None = None


@dataclass(frozen=True)
class AgentConfig:
    """
    Configuration specific to Agent.

    These settings are used as defaults when creating Agent instances
    without explicitly providing AgentOptions.

    Attributes:
        request_timeout: HTTP request timeout in seconds for chat requests.
            Env var: STKAI_AGENT_REQUEST_TIMEOUT

        base_url: Base URL for the Agent API.
            Env var: STKAI_AGENT_BASE_URL

    Example:
        >>> from stkai import config
        >>> config.agent.request_timeout
        60
        >>> config.agent.base_url
        'https://genai-inference-app.stackspot.com'
    """

    request_timeout: int = 60
    base_url: str = "https://genai-inference-app.stackspot.com"


@dataclass
class StkAiConfig:
    """
    Global configuration for the stkai SDK.

    Provides access to resolved configuration values, combining:
    defaults < env vars < configure().

    Attributes:
        client_id: StackSpot client ID for authentication.
            Env var: STKAI_CLIENT_ID

        client_secret: StackSpot client secret for authentication.
            Env var: STKAI_CLIENT_SECRET

        rqc: Configuration specific to RemoteQuickCommand clients.

        agent: Configuration specific to Agent clients.

    Example:
        >>> from stkai import config
        >>> config.rqc.request_timeout
        30
        >>> config.agent.base_url
        'https://genai-inference-app.stackspot.com'
    """

    client_id: str | None = None
    client_secret: str | None = None
    rqc: RqcConfig = field(default_factory=RqcConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)

    def has_credentials(self) -> bool:
        """Check if both client_id and client_secret are set."""
        return bool(self.client_id and self.client_secret)


def _merge_dataclass(base: Any, overrides: dict[str, Any]) -> Any:
    """
    Merge a dataclass instance with a dict of overrides.

    Only applies overrides for keys that exist in the dataclass.
    """
    if not overrides:
        return base
    valid_fields = {f.name for f in fields(base)}
    filtered = {k: v for k, v in overrides.items() if k in valid_fields and v is not None}
    return replace(base, **filtered) if filtered else base


def _get_rqc_from_env() -> dict[str, Any]:
    """Read RQC config values from environment variables."""
    result: dict[str, Any] = {}
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
            result[key] = type_fn(value)
    return result


def _get_agent_from_env() -> dict[str, Any]:
    """Read Agent config values from environment variables."""
    result: dict[str, Any] = {}
    env_mapping: list[tuple[str, str, type]] = [
        ("base_url", "STKAI_AGENT_BASE_URL", str),
        ("request_timeout", "STKAI_AGENT_REQUEST_TIMEOUT", int),
    ]
    for key, env_var, type_fn in env_mapping:
        if value := os.environ.get(env_var):
            result[key] = type_fn(value)
    return result


def _get_credentials_from_env() -> dict[str, Any]:
    """Read credentials from environment variables."""
    result: dict[str, Any] = {}
    if client_id := os.environ.get("STKAI_CLIENT_ID"):
        result["client_id"] = client_id
    if client_secret := os.environ.get("STKAI_CLIENT_SECRET"):
        result["client_secret"] = client_secret
    return result


# Global state for user overrides via configure()
_user_config: dict[str, Any] = {}


def configure(
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    rqc: dict[str, Any] | None = None,
    agent: dict[str, Any] | None = None,
) -> None:
    """
    Configure global SDK settings.

    Call this at application startup to customize defaults.
    If not called, sensible defaults are used (Convention over Configuration).

    Args:
        client_id: StackSpot client ID for authentication (future use).
        client_secret: StackSpot client secret for authentication (future use).
        rqc: Configuration dict for RemoteQuickCommand clients.
        agent: Configuration dict for Agent clients.

    Example:
        >>> import stkai
        >>> stkai.configure(
        ...     rqc={"request_timeout": 60, "max_retries": 5},
        ...     agent={"request_timeout": 120},
        ... )
    """
    global _user_config
    if client_id is not None:
        _user_config["client_id"] = client_id
    if client_secret is not None:
        _user_config["client_secret"] = client_secret
    if rqc is not None:
        _user_config["rqc"] = {**_user_config.get("rqc", {}), **rqc}
    if agent is not None:
        _user_config["agent"] = {**_user_config.get("agent", {}), **agent}


def _build_config() -> StkAiConfig:
    """
    Build the resolved configuration.

    Merges: defaults (dataclass) < env vars < configure().
    """
    # Start with defaults (from dataclass)
    rqc_config = RqcConfig()
    agent_config = AgentConfig()

    # Apply env vars
    rqc_config = _merge_dataclass(rqc_config, _get_rqc_from_env())
    agent_config = _merge_dataclass(agent_config, _get_agent_from_env())

    # Apply user config from configure()
    rqc_config = _merge_dataclass(rqc_config, _user_config.get("rqc", {}))
    agent_config = _merge_dataclass(agent_config, _user_config.get("agent", {}))

    # Build credentials
    creds = _get_credentials_from_env()
    client_id = _user_config.get("client_id") or creds.get("client_id")
    client_secret = _user_config.get("client_secret") or creds.get("client_secret")

    return StkAiConfig(
        client_id=client_id,
        client_secret=client_secret,
        rqc=rqc_config,
        agent=agent_config,
    )


class _ConfigProxy:
    """
    Proxy that provides attribute access to resolved configuration.

    Values are resolved dynamically on each access, respecting the hierarchy:
    defaults < env vars < configure().

    Example:
        >>> from stkai import config
        >>> config.rqc.request_timeout
        30
        >>> config.agent.base_url
        'https://genai-inference-app.stackspot.com'
    """

    @property
    def rqc(self) -> RqcConfig:
        """Get resolved RQC configuration."""
        return _build_config().rqc

    @property
    def agent(self) -> AgentConfig:
        """Get resolved Agent configuration."""
        return _build_config().agent

    @property
    def client_id(self) -> str | None:
        """Get resolved client_id."""
        return _build_config().client_id

    @property
    def client_secret(self) -> str | None:
        """Get resolved client_secret."""
        return _build_config().client_secret

    def has_credentials(self) -> bool:
        """Check if both client_id and client_secret are set."""
        return _build_config().has_credentials()


# Global config instance - ready to use on import
config = _ConfigProxy()


def reset() -> None:
    """
    Reset configuration to defaults.

    Useful for testing to ensure clean state between tests.
    """
    global _user_config
    _user_config = {}
