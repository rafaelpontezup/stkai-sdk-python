"""
Global configuration for the stkai SDK.

This module provides a simple configuration system following Convention over Configuration (CoC).
Users can optionally call STKAI.configure() at application startup to customize defaults.
If not called, sensible defaults are used.

Hierarchy of precedence (highest to lowest):
1. *Options passed to client constructors
2. Values set via STKAI.configure()
3. StackSpot CLI values (oscli) - if CLI is available
4. Environment variables (STKAI_*) - when allow_env_override=True
5. Hardcoded defaults (in dataclass fields)

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
from collections.abc import Callable
from dataclasses import dataclass, field, fields, replace
from functools import wraps
from typing import Any, Literal, Self

# Type alias for rate limit strategies
RateLimitStrategy = Literal["token_bucket", "adaptive"]

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

    def with_overrides(
        self,
        overrides: dict[str, Any],
        allow_none_fields: set[str] | None = None,
    ) -> Self:
        """
        Return a new instance with specified fields overridden.

        Args:
            overrides: Dict of field names to new values.
                       Only existing fields are allowed.
            allow_none_fields: Set of field names that accept None as a valid value.
                       By default, None values are filtered out.

        Returns:
            New instance with updated values.

        Raises:
            ValueError: If overrides contains unknown field names.

        Example:
            >>> config.with_overrides({"request_timeout": 60})
            >>> config.with_overrides({"max_wait_time": None}, allow_none_fields={"max_wait_time"})
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

        allow_none = allow_none_fields or set()
        filtered = {k: v for k, v in overrides.items() if v is not None or k in allow_none}
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
class RateLimitConfig(OverridableConfig):
    """
    Configuration for HTTP client rate limiting.

    When enabled, the EnvironmentAwareHttpClient automatically wraps the
    underlying HTTP client with rate limiting based on the selected strategy.

    Available strategies:
        - "token_bucket": Simple Token Bucket algorithm. Limits requests to
            max_requests per time_window. Blocks if limit exceeded.
        - "adaptive": Adaptive rate limiting with AIMD (Additive Increase,
            Multiplicative Decrease). Automatically adjusts rate based on
            HTTP 429 responses from the server.

    Attributes:
        enabled: Whether to enable rate limiting.
            Env var: STKAI_RATE_LIMIT_ENABLED

        strategy: Rate limiting strategy to use.
            Env var: STKAI_RATE_LIMIT_STRATEGY

        max_requests: Maximum requests allowed in the time window.
            Env var: STKAI_RATE_LIMIT_MAX_REQUESTS

        time_window: Time window in seconds for the rate limit.
            Env var: STKAI_RATE_LIMIT_TIME_WINDOW

        max_wait_time: Maximum seconds to wait for a token before raising
            RateLimitTimeoutError. None means wait indefinitely.
            Env var: STKAI_RATE_LIMIT_MAX_WAIT_TIME

        min_rate_floor: (adaptive only) Minimum rate as fraction of max_requests.
            Prevents rate from dropping below this floor.
            Env var: STKAI_RATE_LIMIT_MIN_RATE_FLOOR

        max_retries_on_429: (adaptive only) Maximum retries on HTTP 429.
            Env var: STKAI_RATE_LIMIT_MAX_RETRIES_ON_429

        penalty_factor: (adaptive only) Rate reduction factor on 429 (0-1).
            Env var: STKAI_RATE_LIMIT_PENALTY_FACTOR

        recovery_factor: (adaptive only) Rate increase factor on success (0-1).
            Env var: STKAI_RATE_LIMIT_RECOVERY_FACTOR

    Example:
        >>> from stkai import STKAI
        >>> STKAI.configure(
        ...     rate_limit={
        ...         "enabled": True,
        ...         "strategy": "token_bucket",
        ...         "max_requests": 10,
        ...         "time_window": 60.0,
        ...     }
        ... )

        >>> # Or with adaptive strategy
        >>> STKAI.configure(
        ...     rate_limit={
        ...         "enabled": True,
        ...         "strategy": "adaptive",
        ...         "max_requests": 100,
        ...         "min_rate_floor": 0.1,
        ...     }
        ... )
    """

    enabled: bool = False
    strategy: RateLimitStrategy = "token_bucket"

    # Common parameters
    max_requests: int = 100
    time_window: float = 60.0
    max_wait_time: float | None = 60.0

    # Adaptive strategy parameters (ignored if strategy != "adaptive")
    min_rate_floor: float = 0.1
    max_retries_on_429: int = 3
    penalty_factor: float = 0.2
    recovery_factor: float = 0.01

    def with_overrides(
        self,
        overrides: dict[str, Any],
        allow_none_fields: set[str] | None = None,
    ) -> Self:
        """
        Return a new instance with specified fields overridden.

        Extends base implementation to support special values:
        - max_wait_time: Can be None, a float, or "unlimited"/"none"/"null"
          (strings are converted to None for unlimited waiting).

        Args:
            overrides: Dict of field names to new values.
            allow_none_fields: Additional fields that accept None (merged with max_wait_time).

        Returns:
            New instance with updated values.
        """
        if not overrides:
            return self

        # Convert "unlimited"/"none"/"null" strings to None for max_wait_time
        processed = dict(overrides)
        if "max_wait_time" in processed:
            value = processed["max_wait_time"]
            if isinstance(value, str) and value.lower() in ("none", "null", "unlimited"):
                processed["max_wait_time"] = None

        # Always allow None for max_wait_time, plus any additional fields
        merged_allow_none = {"max_wait_time"} | (allow_none_fields or set())
        return super().with_overrides(processed, allow_none_fields=merged_allow_none)


@dataclass(frozen=True)
class ConfigEntry:
    """
    A configuration field with its resolved value and source.

    Represents a single configuration entry with metadata about where
    the value came from. Used by explain_data() for structured output.

    Attributes:
        name: The field name (e.g., "request_timeout").
        value: The resolved value.
        source: Where the value came from:
            - "default": Hardcoded default value
            - "env:VAR_NAME": Environment variable
            - "CLI": StackSpot CLI (oscli)
            - "configure": Set via STKAI.configure()

    Example:
        >>> entry = ConfigEntry("request_timeout", 60, "configure")
        >>> entry.name
        'request_timeout'
        >>> entry.value
        60
        >>> entry.source
        'configure'
        >>> entry.formatted_value
        '60'
    """

    name: str
    value: Any
    source: str

    @property
    def formatted_value(self) -> str:
        """
        Return value formatted for display.

        Masks sensitive fields (e.g., client_secret) showing only
        first and last 4 characters, and truncates long strings.

        Returns:
            Formatted string representation of the value.

        Examples:
            >>> ConfigEntry("client_secret", "super-secret-key", "configure").formatted_value
            'supe********-key'
            >>> ConfigEntry("client_secret", "short", "configure").formatted_value
            '********t'
        """
        # Mask sensitive fields
        if self.name in ("client_secret",) and self.value is not None:
            secret = str(self.value)
            # Long secrets: show first 4 and last 4 chars
            if len(secret) >= 12:
                return f"{secret[:4]}********{secret[-4:]}"
            # Short secrets: show last 1/3 of chars
            if len(secret) >= 3:
                visible = max(1, len(secret) // 3)
                return f"********{secret[-visible:]}"
            return "********"

        # Handle None
        if self.value is None:
            return "None"

        # Convert to string and truncate if needed
        str_value = str(self.value)
        max_length = 50
        if len(str_value) > max_length:
            return str_value[: max_length - 3] + "..."

        return str_value


@dataclass(frozen=True)
class STKAIConfigTracker:
    """
    Tracks the source of config field values.

    An immutable tracker that records where each configuration value came from
    (default, env var, CLI, or configure()). Used internally by STKAIConfig
    for debugging via STKAI.explain().

    Attributes:
        sources: Dict tracking source of each field value.
            Structure: {"section": {"field": "source"}}
            Source values: "default", "env:VAR_NAME", "CLI", "configure"

    Example:
        >>> tracker = STKAIConfigTracker()
        >>> tracker = tracker.with_changes_tracked(old_cfg, new_cfg, "env")
        >>> tracker.sources.get("rqc", {}).get("request_timeout")
        'env:STKAI_RQC_REQUEST_TIMEOUT'
    """

    sources: dict[str, dict[str, str]] = field(default_factory=dict)

    @staticmethod
    def track_changes(
        source_type: str,
    ) -> Callable[[Callable[..., STKAIConfig]], Callable[..., STKAIConfig]]:
        """
        Decorator that tracks config changes made by the decorated method.

        Wraps methods that return a new STKAIConfig, automatically detecting
        changes between the original config (self) and the returned config,
        then recording those changes in the tracker.

        Args:
            source_type: Source label for tracking ("env", "CLI", or "configure").

        Returns:
            Decorator function that wraps the method.

        Example:
            >>> @STKAIConfigTracker.track_changes("env")
            ... def with_env_vars(self) -> STKAIConfig:
            ...     return STKAIConfig(...)
        """

        def decorator(
            method: Callable[..., STKAIConfig],
        ) -> Callable[..., STKAIConfig]:
            @wraps(method)
            def wrapper(self: STKAIConfig, *args: Any, **kwargs: Any) -> STKAIConfig:
                new_config = method(self, *args, **kwargs)
                new_tracker = self._tracker.with_changes_tracked(
                    self, new_config, source_type
                )
                return replace(new_config, _tracker=new_tracker)

            return wrapper

        return decorator

    def with_changes_tracked(
        self,
        old_config: STKAIConfig,
        new_config: STKAIConfig,
        source_type: str,
    ) -> STKAIConfigTracker:
        """
        Return new tracker with changes between configs tracked.

        Compares old and new configs, detects changed fields, and returns
        a new tracker with those changes recorded.

        Args:
            old_config: The config before changes.
            new_config: The config after changes.
            source_type: Source label ("env", "CLI", or "configure").

        Returns:
            New STKAIConfigTracker with detected changes tracked.
        """
        changes = self._detect_changes(old_config, new_config)
        new_sources = self._merge_sources(changes, source_type)
        return STKAIConfigTracker(sources=new_sources)

    def _detect_changes(
        self,
        old_config: STKAIConfig,
        new_config: STKAIConfig,
    ) -> dict[str, list[str]]:
        """
        Detect which fields changed between two configs.

        Args:
            old_config: The config before changes.
            new_config: The config after changes.

        Returns:
            Dict mapping section names to lists of changed field names.
            Example: {"rqc": ["request_timeout", "base_url"]}
        """
        changes: dict[str, list[str]] = {}

        for section_name in ("auth", "rqc", "agent", "rate_limit"):
            old_section = getattr(old_config, section_name)
            new_section = getattr(new_config, section_name)

            changed_fields = []
            for f in fields(old_section):
                old_val = getattr(old_section, f.name)
                new_val = getattr(new_section, f.name)
                if old_val != new_val:
                    changed_fields.append(f.name)

            if changed_fields:
                changes[section_name] = changed_fields

        return changes

    def _merge_sources(
        self,
        changes: dict[str, list[str]],
        source_type: str,
    ) -> dict[str, dict[str, str]]:
        """
        Merge detected changes into existing sources.

        Args:
            changes: Dict of section -> list of changed field names.
            source_type: Source label ("env", "CLI", or "configure").

        Returns:
            New sources dict with changes merged in.
        """
        new_sources = self._copy_sources()

        for section, field_names in changes.items():
            section_sources = new_sources.setdefault(section, {})
            for field_name in field_names:
                if source_type == "env":
                    # Generate env var name based on convention
                    env_var = f"STKAI_{section.upper()}_{field_name.upper()}"
                    section_sources[field_name] = f"env:{env_var}"
                else:
                    section_sources[field_name] = source_type

        return new_sources

    def _copy_sources(self) -> dict[str, dict[str, str]]:
        """Create a deep copy of current sources."""
        return {section: dict(flds) for section, flds in self.sources.items()}


@dataclass(frozen=True)
class STKAIConfig:
    """
    Global configuration for the stkai SDK.

    Aggregates all configuration sections: auth, rqc, agent, and rate_limit.
    Access via the global `STKAI.config` property.

    Attributes:
        auth: Authentication configuration.
        rqc: RemoteQuickCommand configuration.
        agent: Agent configuration.
        rate_limit: Rate limiting configuration for HTTP clients.

    Example:
        >>> from stkai import STKAI
        >>> STKAI.config.rqc.request_timeout
        30
        >>> STKAI.config.auth.has_credentials()
        False
        >>> STKAI.config.rate_limit.enabled
        False
    """

    auth: AuthConfig = field(default_factory=AuthConfig)
    rqc: RqcConfig = field(default_factory=RqcConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    _tracker: STKAIConfigTracker = field(default_factory=STKAIConfigTracker, repr=False)

    @STKAIConfigTracker.track_changes("env")
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
            rate_limit=self.rate_limit.with_overrides(_get_rate_limit_from_env()),
        )

    @STKAIConfigTracker.track_changes("CLI")
    def with_cli_defaults(self) -> STKAIConfig:
        """
        Return a new config with CLI-provided values applied.

        CLI values take precedence over env vars. When running in CLI mode,
        the CLI knows the correct endpoints for the current environment.

        Returns:
            New STKAIConfig instance with CLI values applied.

        Example:
            >>> # Apply CLI defaults on top of env vars
            >>> config = STKAIConfig().with_env_vars().with_cli_defaults()
        """
        from stkai._cli import StkCLI

        cli_rqc_overrides: dict[str, Any] = {}
        if cli_base_url := StkCLI.get_codebuddy_base_url():
            cli_rqc_overrides["base_url"] = cli_base_url

        return STKAIConfig(
            auth=self.auth,
            rqc=self.rqc.with_overrides(cli_rqc_overrides),
            agent=self.agent,
            rate_limit=self.rate_limit,
        )

    @STKAIConfigTracker.track_changes("configure")
    def with_section_overrides(
        self,
        *,
        auth: dict[str, Any] | None = None,
        rqc: dict[str, Any] | None = None,
        agent: dict[str, Any] | None = None,
        rate_limit: dict[str, Any] | None = None,
    ) -> STKAIConfig:
        """
        Return a new config with overrides applied to nested sections.

        Each section dict is merged with the existing section config,
        only overriding the specified fields.

        Args:
            auth: Authentication config overrides.
            rqc: RemoteQuickCommand config overrides.
            agent: Agent config overrides.
            rate_limit: Rate limiting config overrides.

        Returns:
            New STKAIConfig instance with overrides applied.

        Example:
            >>> config = STKAIConfig()
            >>> custom = config.with_section_overrides(
            ...     rqc={"request_timeout": 60},
            ...     agent={"request_timeout": 120},
            ... )
        """
        return STKAIConfig(
            auth=self.auth.with_overrides(auth or {}),
            rqc=self.rqc.with_overrides(rqc or {}),
            agent=self.agent.with_overrides(agent or {}),
            rate_limit=self.rate_limit.with_overrides(rate_limit or {}),
        )

    def explain_data(self) -> dict[str, list[ConfigEntry]]:
        """
        Return config data structured for explain output.

        Provides a structured representation of all config values and their
        sources, useful for debugging, testing, or custom formatting.

        Returns:
            Dict mapping section names to list of ConfigEntry objects.

        Example:
            >>> config = STKAIConfig().with_env_vars()
            >>> data = config.explain_data()
            >>> data["rqc"][0].name
            'request_timeout'
            >>> data["rqc"][0].source
            'env:STKAI_RQC_REQUEST_TIMEOUT'
        """
        result: dict[str, list[ConfigEntry]] = {}

        for section_name in ("auth", "rqc", "agent", "rate_limit"):
            section_config = getattr(self, section_name)
            section_sources = self._tracker.sources.get(section_name, {})
            result[section_name] = [
                ConfigEntry(
                    name=f.name,
                    value=getattr(section_config, f.name),
                    source=section_sources.get(f.name, "default"),
                )
                for f in fields(section_config)
            ]

        return result


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


def _get_rate_limit_from_env() -> dict[str, Any]:
    """Read RateLimitConfig values from environment variables."""
    result: dict[str, Any] = {}

    # Handle boolean 'enabled' field specially
    if enabled_str := os.environ.get("STKAI_RATE_LIMIT_ENABLED"):
        result["enabled"] = enabled_str.lower() in ("true", "1", "yes")

    # Handle strategy (string, but validated by dataclass)
    if strategy := os.environ.get("STKAI_RATE_LIMIT_STRATEGY"):
        result["strategy"] = strategy

    # Handle max_wait_time specially (can be None for "unlimited")
    if max_wait_str := os.environ.get("STKAI_RATE_LIMIT_MAX_WAIT_TIME"):
        if max_wait_str.lower() in ("none", "null", "unlimited"):
            result["max_wait_time"] = None
        else:
            result["max_wait_time"] = float(max_wait_str)

    # Standard numeric fields
    env_mapping: list[tuple[str, str, type]] = [
        ("max_requests", "STKAI_RATE_LIMIT_MAX_REQUESTS", int),
        ("time_window", "STKAI_RATE_LIMIT_TIME_WINDOW", float),
        ("min_rate_floor", "STKAI_RATE_LIMIT_MIN_RATE_FLOOR", float),
        ("max_retries_on_429", "STKAI_RATE_LIMIT_MAX_RETRIES_ON_429", int),
        ("penalty_factor", "STKAI_RATE_LIMIT_PENALTY_FACTOR", float),
        ("recovery_factor", "STKAI_RATE_LIMIT_RECOVERY_FACTOR", float),
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
        """Initialize with defaults, environment variables, and CLI values."""
        self._config: STKAIConfig = STKAIConfig().with_env_vars().with_cli_defaults()

    def configure(
        self,
        *,
        auth: dict[str, Any] | None = None,
        rqc: dict[str, Any] | None = None,
        agent: dict[str, Any] | None = None,
        rate_limit: dict[str, Any] | None = None,
        allow_env_override: bool = True,
        allow_cli_override: bool = True,
    ) -> STKAIConfig:
        """
        Configure SDK settings.

        Call at application startup to customize defaults. Updates the
        internal configuration and returns the configured instance.

        Args:
            auth: Authentication config overrides (client_id, client_secret, token_url).
            rqc: RemoteQuickCommand config overrides (timeouts, retries, polling).
            agent: Agent config overrides (timeout, base_url).
            rate_limit: Rate limiting config overrides (enabled, strategy, max_requests, etc.).
            allow_env_override: If True (default), env vars are used as fallback
                for fields NOT provided. If False, ignores env vars entirely.
            allow_cli_override: If True (default), CLI values (oscli) are used as fallback
                for fields NOT provided. If False, ignores CLI values entirely.

        Returns:
            The configured STKAIConfig instance.

        Raises:
            ValueError: If any dict contains unknown field names.

        Precedence (both overrides True):
            STKAI.configure() > CLI values > ENV vars > defaults

        Precedence (allow_cli_override=False):
            STKAI.configure() > ENV vars > defaults

        Precedence (allow_env_override=False):
            STKAI.configure() > CLI values > defaults

        Example:
            >>> from stkai import STKAI
            >>> STKAI.configure(
            ...     auth={"client_id": "x", "client_secret": "y"},
            ...     rqc={"request_timeout": 60},
            ...     rate_limit={"enabled": True, "max_requests": 10},
            ... )
        """
        # Start with defaults, apply env vars and CLI values as base layer
        base = STKAIConfig()
        if allow_env_override:
            base = base.with_env_vars()  # defaults + env vars
        if allow_cli_override:
            base = base.with_cli_defaults()  # CLI values take precedence over env vars

        # Apply user overrides on top - configure() always wins
        self._config = base.with_section_overrides(
            auth=auth,
            rqc=rqc,
            agent=agent,
            rate_limit=rate_limit,
        )

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
        Reset configuration to defaults + env vars + CLI values.

        Useful for testing to ensure clean state between tests.

        Returns:
            The reset STKAIConfig instance.

        Example:
            >>> from stkai import STKAI
            >>> STKAI.reset()
        """
        self._config = STKAIConfig().with_env_vars().with_cli_defaults()
        return self._config

    def explain(
        self,
        output: Callable[[str], None] = print,
    ) -> None:
        """
        Print current configuration with sources.

        Useful for debugging and troubleshooting configuration issues.
        Shows each config value and where it came from:

        - "default": Using hardcoded default value
        - "env:VAR_NAME": Value from environment variable
        - "CLI": Value from StackSpot CLI (oscli)
        - "configure": Value set via STKAI.configure()

        Args:
            output: Callable to output each line. Defaults to print.
                    Can be used with logging: `STKAI.explain(logger.info)`

        Example:
            >>> from stkai import STKAI
            >>> STKAI.explain()
            STKAI Configuration:
            ====================
            [rqc]
              base_url .......... https://example.com (CLI)
              request_timeout ... 60 (configure)
            ...

            >>> # Using with logging
            >>> import logging
            >>> STKAI.explain(logging.info)
        """
        output("STKAI Configuration:")
        output("=" * 80)

        name_width = 25  # field name + dots
        value_width = 50  # max value width (matches truncation)

        for section_name, entries in self._config.explain_data().items():
            output(f"[{section_name}]")
            for entry in entries:
                dots = "." * (name_width - len(entry.name))
                value_padded = entry.formatted_value.ljust(value_width)
                output(f"  {entry.name} {dots} {value_padded} ({entry.source})")

        output("=" * 80)

    def __repr__(self) -> str:
        return f"STKAI(config={self._config!r})"


# Global singleton instance - always reflects current configuration
STKAI: _STKAI = _STKAI()
