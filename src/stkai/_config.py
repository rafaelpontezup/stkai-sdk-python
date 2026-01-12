"""
Global configuration for the stkai SDK.

This module provides a simple configuration system following Convention over Configuration (CoC).
Users can optionally call configure_stkai() at application startup to customize defaults.
If not called, sensible defaults are used.

Hierarchy of precedence (highest to lowest):
1. *Options passed to client constructors
2. Environment variables (STKAI_*) - when allow_env_override=True
3. Values set via configure_stkai()
4. Hardcoded defaults (in dataclass fields)

Example:
    >>> from stkai import STKAI_CONFIG, configure_stkai
    >>>
    >>> # Pre-loaded with defaults + env vars
    >>> timeout = STKAI_CONFIG.agent.request_timeout
    >>>
    >>> # Custom configuration
    >>> configure_stkai(
    ...     auth={"client_id": "x", "client_secret": "y"},
    ...     rqc={"request_timeout": 60},
    ... )
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, replace
from typing import Any, Self

# =============================================================================
# Base Class
# =============================================================================


@dataclass(frozen=True)
class OverridableConfig:
    """
    Base class for immutable configuration dataclasses.

    Provides `.with_overrides()` method for creating new instances
    with partial field updates. Uses strict validation to catch
    typos and invalid field names early.

    Example:
        >>> config = RqcConfig()
        >>> custom = config.with_overrides({"request_timeout": 60})
        >>> custom.request_timeout
        60
    """

    def with_overrides(self, overrides: dict[str, Any]) -> Self:
        """
        Return a new instance with specified fields overridden.

        Args:
            overrides: Dict of field names to new values.
                       Only existing fields are allowed.

        Returns:
            New instance with updated values.

        Raises:
            ValueError: If overrides contains unknown field names.

        Example:
            >>> config.with_overrides({"request_timeout": 60})
        """
        if not overrides:
            return self

        valid_fields = {f.name for f in fields(self)}
        invalid_fields = set(overrides.keys()) - valid_fields

        if invalid_fields:
            raise ValueError(
                f"Unknown config fields: {invalid_fields}. "
                f"Valid fields are: {valid_fields}"
            )

        filtered = {k: v for k, v in overrides.items() if v is not None}
        return replace(self, **filtered) if filtered else self


# =============================================================================
# Configuration Dataclasses
# =============================================================================


@dataclass(frozen=True)
class AuthConfig(OverridableConfig):
    """
    Authentication configuration for StackSpot AI.

    Credentials are used for future native authentication support.
    Currently, authentication is delegated to StackSpot CLI (stk).

    Attributes:
        client_id: StackSpot client ID for authentication.
            Env var: STKAI_AUTH_CLIENT_ID

        client_secret: StackSpot client secret for authentication.
            Env var: STKAI_AUTH_CLIENT_SECRET

    Example:
        >>> from stkai import STKAI_CONFIG
        >>> if STKAI_CONFIG.auth.has_credentials():
        ...     print("Credentials configured")
    """

    client_id: str | None = None
    client_secret: str | None = None

    def has_credentials(self) -> bool:
        """Check if both client_id and client_secret are set."""
        return bool(self.client_id and self.client_secret)


@dataclass(frozen=True)
class RqcConfig(OverridableConfig):
    """
    Configuration for RemoteQuickCommand clients.

    These settings are used as defaults when creating RemoteQuickCommand
    instances without explicitly providing CreateExecutionOptions or
    GetResultOptions.

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

        base_url: Base URL for the RQC API. If None, uses StackSpot CLI.
            Env var: STKAI_RQC_BASE_URL

    Example:
        >>> from stkai import STKAI_CONFIG
        >>> STKAI_CONFIG.rqc.request_timeout
        30
        >>> STKAI_CONFIG.rqc.max_retries
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
class AgentConfig(OverridableConfig):
    """
    Configuration for Agent clients.

    These settings are used as defaults when creating Agent instances
    without explicitly providing AgentOptions.

    Attributes:
        request_timeout: HTTP request timeout in seconds for chat requests.
            Env var: STKAI_AGENT_REQUEST_TIMEOUT

        base_url: Base URL for the Agent API.
            Env var: STKAI_AGENT_BASE_URL

    Example:
        >>> from stkai import STKAI_CONFIG
        >>> STKAI_CONFIG.agent.request_timeout
        60
        >>> STKAI_CONFIG.agent.base_url
        'https://genai-inference-app.stackspot.com'
    """

    request_timeout: int = 60
    base_url: str = "https://genai-inference-app.stackspot.com"


@dataclass(frozen=True)
class StkAiConfig:
    """
    Global configuration for the stkai SDK.

    Aggregates all configuration sections: auth, rqc, and agent.
    Access via the global `STKAI_CONFIG` constant.

    Attributes:
        auth: Authentication configuration.
        rqc: RemoteQuickCommand configuration.
        agent: Agent configuration.

    Example:
        >>> from stkai import STKAI_CONFIG
        >>> STKAI_CONFIG.rqc.request_timeout
        30
        >>> STKAI_CONFIG.auth.has_credentials()
        False
    """

    auth: AuthConfig = field(default_factory=AuthConfig)
    rqc: RqcConfig = field(default_factory=RqcConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)


# =============================================================================
# Environment Variable Helpers
# =============================================================================


def _get_auth_from_env() -> dict[str, Any]:
    """Read AuthConfig values from environment variables."""
    result: dict[str, Any] = {}
    env_mapping: list[tuple[str, str, type]] = [
        ("client_id", "STKAI_AUTH_CLIENT_ID", str),
        ("client_secret", "STKAI_AUTH_CLIENT_SECRET", str),
    ]
    for key, env_var, type_fn in env_mapping:
        if value := os.environ.get(env_var):
            result[key] = type_fn(value)
    return result


def _get_rqc_from_env() -> dict[str, Any]:
    """Read RqcConfig values from environment variables."""
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
    """Read AgentConfig values from environment variables."""
    result: dict[str, Any] = {}
    env_mapping: list[tuple[str, str, type]] = [
        ("base_url", "STKAI_AGENT_BASE_URL", str),
        ("request_timeout", "STKAI_AGENT_REQUEST_TIMEOUT", int),
    ]
    for key, env_var, type_fn in env_mapping:
        if value := os.environ.get(env_var):
            result[key] = type_fn(value)
    return result


def _build_config_from_env() -> StkAiConfig:
    """
    Build StkAiConfig with defaults merged with environment variables.

    This is used to initialize STKAI_CONFIG at module load time.
    """
    auth_config = AuthConfig().with_overrides(_get_auth_from_env())
    rqc_config = RqcConfig().with_overrides(_get_rqc_from_env())
    agent_config = AgentConfig().with_overrides(_get_agent_from_env())

    return StkAiConfig(
        auth=auth_config,
        rqc=rqc_config,
        agent=agent_config,
    )


# =============================================================================
# Global Configuration Instance
# =============================================================================


# Internal mutable reference to the current config
_current_config: StkAiConfig = _build_config_from_env()


class _StkAiConfigProxy:
    """
    Proxy that provides attribute access to the current global configuration.

    This proxy ensures that `STKAI_CONFIG.rqc.request_timeout` always returns
    the current value, even after `configure_stkai()` is called. Without this,
    importing `STKAI_CONFIG` would copy the reference and not see updates.

    Example:
        >>> from stkai import STKAI_CONFIG
        >>> STKAI_CONFIG.rqc.request_timeout  # Always current value
        30
    """

    @property
    def auth(self) -> AuthConfig:
        """Get current authentication configuration."""
        return _current_config.auth

    @property
    def rqc(self) -> RqcConfig:
        """Get current RQC configuration."""
        return _current_config.rqc

    @property
    def agent(self) -> AgentConfig:
        """Get current Agent configuration."""
        return _current_config.agent

    def __repr__(self) -> str:
        return repr(_current_config)


# Global config proxy - always reflects current configuration
STKAI_CONFIG: _StkAiConfigProxy = _StkAiConfigProxy()


# =============================================================================
# Public API
# =============================================================================


def configure_stkai(
    *,
    auth: dict[str, Any] | None = None,
    rqc: dict[str, Any] | None = None,
    agent: dict[str, Any] | None = None,
    allow_env_override: bool = True,
) -> StkAiConfig:
    """
    Configure global SDK settings.

    Call at application startup to customize defaults. Updates the
    global `STKAI_CONFIG` and returns the configured instance.

    Args:
        auth: Authentication config overrides (client_id, client_secret).
        rqc: RemoteQuickCommand config overrides.
        agent: Agent config overrides.
        allow_env_override: If True (default), env vars take precedence
            over provided values. If False, ignores env vars entirely.

    Returns:
        The configured StkAiConfig instance.

    Raises:
        ValueError: If any dict contains unknown field names.

    Precedence (allow_env_override=True):
        ENV vars > configure_stkai() > defaults

    Precedence (allow_env_override=False):
        configure_stkai() > defaults

    Example:
        >>> from stkai import configure_stkai
        >>> config = configure_stkai(
        ...     auth={"client_id": "x", "client_secret": "y"},
        ...     rqc={"request_timeout": 60},
        ... )
    """
    global _current_config

    # Start with defaults
    auth_config = AuthConfig()
    rqc_config = RqcConfig()
    agent_config = AgentConfig()

    # Apply user overrides from configure_stkai()
    if auth:
        auth_config = auth_config.with_overrides(auth)
    if rqc:
        rqc_config = rqc_config.with_overrides(rqc)
    if agent:
        agent_config = agent_config.with_overrides(agent)

    # Apply env vars on top (if enabled) - env vars have highest priority
    if allow_env_override:
        auth_config = auth_config.with_overrides(_get_auth_from_env())
        rqc_config = rqc_config.with_overrides(_get_rqc_from_env())
        agent_config = agent_config.with_overrides(_get_agent_from_env())

    _current_config = StkAiConfig(
        auth=auth_config,
        rqc=rqc_config,
        agent=agent_config,
    )

    return _current_config


def reset_stkai_config() -> StkAiConfig:
    """
    Reset configuration to defaults + env vars.

    Useful for testing to ensure clean state between tests.

    Returns:
        The reset StkAiConfig instance.

    Example:
        >>> from stkai._config import reset_stkai_config
        >>> reset_stkai_config()
    """
    global _current_config
    _current_config = _build_config_from_env()
    return _current_config
