"""
Global configuration for the stkai SDK.

This module provides a simple configuration system following Convention over Configuration (CoC).
Users can optionally call STKAI.configure() at application startup to customize defaults.
If not called, sensible defaults are used.

Hierarchy of precedence (highest to lowest):
1. *Options passed to client constructors
2. Environment variables (STKAI_*) - when allow_env_override=True
3. Values set via STKAI.configure()
4. Hardcoded defaults (in dataclass fields)

Example:
    >>> from stkai import STKAI
    >>>
    >>> # Pre-loaded with defaults + env vars
    >>> timeout = STKAI.config.agent.request_timeout
    >>>
    >>> # Custom configuration
    >>> STKAI.configure(
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

    Credentials are used for standalone authentication without StackSpot CLI.
    When using oscli-based HTTP clients, authentication is delegated to the CLI.

    Attributes:
        client_id: StackSpot client ID for authentication.
            Env var: STKAI_AUTH_CLIENT_ID

        client_secret: StackSpot client secret for authentication.
            Env var: STKAI_AUTH_CLIENT_SECRET

        token_url: OAuth2 token endpoint URL for client credentials flow.
            Env var: STKAI_AUTH_TOKEN_URL

    Example:
        >>> from stkai import STKAI
        >>> if STKAI.config.auth.has_credentials():
        ...     print("Credentials configured")
    """

    client_id: str | None = None
    client_secret: str | None = None
    token_url: str = "https://idm.stackspot.com/stackspot-dev/oidc/oauth/token"

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
        >>> from stkai import STKAI
        >>> STKAI.config.rqc.request_timeout
        30
        >>> STKAI.config.rqc.max_retries
        3
    """

    request_timeout: int = 30
    max_retries: int = 3
    backoff_factor: float = 0.5
    poll_interval: float = 10.0
    poll_max_duration: float = 600.0
    overload_timeout: float = 60.0
    max_workers: int = 8
    base_url: str = "https://genai-code-buddy-api.stackspot.com"


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
        >>> from stkai import STKAI
        >>> STKAI.config.agent.request_timeout
        60
        >>> STKAI.config.agent.base_url
        'https://genai-inference-app.stackspot.com'
    """

    request_timeout: int = 60
    base_url: str = "https://genai-inference-app.stackspot.com"


@dataclass(frozen=True)
class STKAIConfig:
    """
    Global configuration for the stkai SDK.

    Aggregates all configuration sections: auth, rqc, and agent.
    Access via the global `STKAI.config` property.

    Attributes:
        auth: Authentication configuration.
        rqc: RemoteQuickCommand configuration.
        agent: Agent configuration.

    Example:
        >>> from stkai import STKAI
        >>> STKAI.config.rqc.request_timeout
        30
        >>> STKAI.config.auth.has_credentials()
        False
    """

    auth: AuthConfig = field(default_factory=AuthConfig)
    rqc: RqcConfig = field(default_factory=RqcConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)

    def with_env_vars(self) -> STKAIConfig:
        """
        Return a new config with environment variables applied on top.

        Reads STKAI_* environment variables and applies them over the
        current configuration values.

        Returns:
            New STKAIConfig instance with env vars applied.

        Example:
            >>> config = STKAIConfig().with_env_vars()
            >>> # Or apply on top of custom config
            >>> custom = STKAIConfig(rqc=RqcConfig(request_timeout=60))
            >>> final = custom.with_env_vars()
        """
        return STKAIConfig(
            auth=self.auth.with_overrides(_get_auth_from_env()),
            rqc=self.rqc.with_overrides(_get_rqc_from_env()),
            agent=self.agent.with_overrides(_get_agent_from_env()),
        )


# =============================================================================
# Environment Variable Helpers
# =============================================================================


def _get_auth_from_env() -> dict[str, Any]:
    """Read AuthConfig values from environment variables."""
    result: dict[str, Any] = {}
    env_mapping: list[tuple[str, str, type]] = [
        ("client_id", "STKAI_AUTH_CLIENT_ID", str),
        ("client_secret", "STKAI_AUTH_CLIENT_SECRET", str),
        ("token_url", "STKAI_AUTH_TOKEN_URL", str),
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


# =============================================================================
# Global Configuration Singleton
# =============================================================================


class _STKAI:
    """
    Singleton for SDK configuration.

    Provides a centralized configuration system for the stkai SDK.
    Use `STKAI.configure()` to customize settings and `STKAI.config`
    to access current configuration.

    Example:
        >>> from stkai import STKAI
        >>> STKAI.configure(auth={"client_id": "..."})
        >>> print(STKAI.config.rqc.request_timeout)
    """

    def __init__(self) -> None:
        """Initialize with defaults and apply environment variables."""
        self._config: STKAIConfig = STKAIConfig().with_env_vars()

    def configure(
        self,
        *,
        auth: dict[str, Any] | None = None,
        rqc: dict[str, Any] | None = None,
        agent: dict[str, Any] | None = None,
        allow_env_override: bool = True,
    ) -> STKAIConfig:
        """
        Configure SDK settings.

        Call at application startup to customize defaults. Updates the
        internal configuration and returns the configured instance.

        Args:
            auth: Authentication config overrides (client_id, client_secret, token_url).
            rqc: RemoteQuickCommand config overrides (timeouts, retries, polling).
            agent: Agent config overrides (timeout, base_url).
            allow_env_override: If True (default), env vars take precedence
                over provided values. If False, ignores env vars entirely.

        Returns:
            The configured STKAIConfig instance.

        Raises:
            ValueError: If any dict contains unknown field names.

        Precedence (allow_env_override=True):
            ENV vars > STKAI.configure() > defaults

        Precedence (allow_env_override=False):
            STKAI.configure() > defaults

        Example:
            >>> from stkai import STKAI
            >>> STKAI.configure(
            ...     auth={"client_id": "x", "client_secret": "y"},
            ...     rqc={"request_timeout": 60},
            ... )
        """
        # Start with defaults and apply user overrides
        self._config = STKAIConfig(
            auth=AuthConfig().with_overrides(auth or {}),
            rqc=RqcConfig().with_overrides(rqc or {}),
            agent=AgentConfig().with_overrides(agent or {}),
        )

        # Apply env vars on top (if enabled) - env vars have highest priority
        if allow_env_override:
            self._config = self._config.with_env_vars()

        return self._config

    @property
    def config(self) -> STKAIConfig:
        """
        Access current configuration (read-only).

        Returns:
            The current STKAIConfig instance.

        Example:
            >>> from stkai import STKAI
            >>> STKAI.config.rqc.request_timeout
            30
        """
        return self._config

    def reset(self) -> STKAIConfig:
        """
        Reset configuration to defaults + env vars.

        Useful for testing to ensure clean state between tests.

        Returns:
            The reset STKAIConfig instance.

        Example:
            >>> from stkai import STKAI
            >>> STKAI.reset()
        """
        self._config = STKAIConfig().with_env_vars()
        return self._config

    def __repr__(self) -> str:
        return f"STKAI(config={self._config!r})"


# Global singleton instance - always reflects current configuration
STKAI: _STKAI = _STKAI()
