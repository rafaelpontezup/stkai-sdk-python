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
# Exceptions
# =============================================================================


class ConfigEnvVarError(ValueError):
    """Raised when an environment variable has an invalid value."""

    def __init__(
        self,
        env_var: str,
        value: str,
        expected_type: str,
        cause: Exception | None = None,
    ):
        self.env_var = env_var
        self.value = value
        self.expected_type = expected_type
        super().__init__(f"Invalid value for {env_var}: '{value}' (expected {expected_type})")
        self.__cause__ = cause


class ConfigValidationError(ValueError):
    """Raised when a configuration value fails validation."""

    def __init__(
        self,
        field: str,
        value: Any,
        message: str,
        section: str | None = None,
    ):
        self.field = field
        self.value = value
        self.section = section
        prefix = f"[{section}] " if section else ""
        super().__init__(f"{prefix}Invalid value for '{field}': {value!r}. {message}")


# =============================================================================
# Environment Variables
# =============================================================================


class EnvVars:
    """
    Utility class for reading environment variables with type conversion.

    Example:
        >>> EnvVars.get("STKAI_RQC_TIMEOUT", type_hint=int)
        30
        >>> EnvVars.get("STKAI_AUTH_CLIENT_ID")
        'my-client-id'
        >>> EnvVars.get("UNDEFINED_VAR")
        None
    """

    @staticmethod
    def get(
        var_name: str,
        type_hint: Any = str,
        converter: Callable[[str], Any] | None = None,
    ) -> Any:
        """
        Read an environment variable with optional type conversion.

        Args:
            var_name: The environment variable name.
            type_hint: Type hint used to infer the converter (ignored if converter is provided).
            converter: Custom converter function (takes precedence over type_hint).

        Returns:
            The converted value, or None if env var is not set/empty.

        Raises:
            ConfigEnvVarError: If the value cannot be converted.
        """
        raw_value = os.environ.get(var_name)
        if not raw_value:  # None or empty string
            return None

        actual_converter = converter or EnvVars._infer_converter(type_hint)
        try:
            return actual_converter(raw_value)
        except (ValueError, TypeError) as e:
            raise ConfigEnvVarError(
                env_var=var_name,
                value=raw_value,
                expected_type=type_hint.__name__ if hasattr(type_hint, "__name__") else str(type_hint),
                cause=e,
            ) from e

    @staticmethod
    def _infer_converter(type_hint: Any) -> Callable[[str], Any]:
        """
        Infer converter function from type hint.

        Handles both actual types and string annotations (PEP 563).
        """
        # Handle string annotations (from __future__ import annotations)
        type_str = str(type_hint)

        if type_hint is int or type_str == "int":
            return int
        if type_hint is float or type_str == "float":
            return float
        if type_hint is bool or type_str == "bool":
            return lambda v: v.lower() in ("true", "1", "yes")
        # str and other types: return as string
        return str


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

    def with_env_vars(self) -> Self:
        """
        Return new instance with environment variables applied.

        Reads env vars declared in field metadata and applies them as overrides.
        Fields with metadata={"skip": True} are ignored (for subclass handling).

        Raises:
            ConfigEnvVarError: If an env var has an invalid value.
        """
        overrides: dict[str, Any] = {}
        for f in fields(self):
            env_var = f.metadata.get("env")
            skip = f.metadata.get("skip", False)
            if env_var and not skip:
                value = EnvVars.get(
                    var_name=env_var,
                    type_hint=f.type,
                    converter=f.metadata.get("converter"),
                )
                if value is not None:
                    overrides[f.name] = value
        return self.with_overrides(overrides)


# =============================================================================
# Configuration Dataclasses
# =============================================================================


@dataclass(frozen=True)
class SdkConfig:
    """
    SDK metadata (read-only, not configurable).

    Provides information about the SDK version and runtime environment.
    These values are automatically detected and cannot be overridden.

    Attributes:
        version: The installed SDK version.
        cli_mode: Whether StackSpot CLI (oscli) is available.

    Example:
        >>> from stkai import STKAI
        >>> STKAI.config.sdk.version
        '0.2.8'
        >>> STKAI.config.sdk.cli_mode
        True
    """

    version: str
    cli_mode: bool

    @classmethod
    def detect(cls) -> SdkConfig:
        """
        Detect SDK metadata from the runtime environment.

        Returns:
            SdkConfig with version and cli_mode auto-detected.
        """
        from stkai import __version__
        from stkai._cli import StkCLI

        return cls(
            version=__version__,
            cli_mode=StkCLI.is_available(),
        )


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

    client_id: str | None = field(default=None, metadata={"env": "STKAI_AUTH_CLIENT_ID"})
    client_secret: str | None = field(default=None, metadata={"env": "STKAI_AUTH_CLIENT_SECRET"})
    token_url: str = field(default="https://idm.stackspot.com/stackspot-dev/oidc/oauth/token", metadata={"env": "STKAI_AUTH_TOKEN_URL"})

    def has_credentials(self) -> bool:
        """Check if both client_id and client_secret are set."""
        return bool(self.client_id and self.client_secret)

    def validate(self) -> Self:
        """Validate auth configuration fields."""
        if self.client_id is not None and self.client_id == "":
            raise ConfigValidationError(
                "client_id", self.client_id,
                "Must not be empty string.", section="auth"
            )
        if self.client_secret is not None and self.client_secret == "":
            raise ConfigValidationError(
                "client_secret", self.client_secret,
                "Must not be empty string.", section="auth"
            )
        if self.token_url and not (self.token_url.startswith("http://") or self.token_url.startswith("https://")):
            raise ConfigValidationError(
                "token_url", self.token_url,
                "Must start with 'http://' or 'https://'.", section="auth"
            )
        return self


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

        retry_max_retries: Maximum retry attempts for failed create-execution calls.
            Use 0 to disable retries (single attempt only).
            Use 3 for 4 total attempts (1 original + 3 retries).
            Env var: STKAI_RQC_RETRY_MAX_RETRIES

        retry_initial_delay: Initial delay in seconds for the first retry attempt.
            Subsequent retries use exponential backoff (delay doubles each attempt).
            Example: with 0.5s initial delay, retries wait 0.5s, 1s, 2s, 4s...
            Env var: STKAI_RQC_RETRY_INITIAL_DELAY

        poll_interval: Seconds to wait between polling status checks.
            Env var: STKAI_RQC_POLL_INTERVAL

        poll_max_duration: Maximum seconds to wait for execution completion
            before timing out.
            Env var: STKAI_RQC_POLL_MAX_DURATION

        poll_overload_timeout: Maximum seconds to tolerate CREATED status before
            assuming server overload.
            Env var: STKAI_RQC_POLL_OVERLOAD_TIMEOUT

        max_workers: Maximum number of concurrent threads for execute_many().
            Env var: STKAI_RQC_MAX_WORKERS

        base_url: Base URL for the RQC API. If None, uses StackSpot CLI.
            Env var: STKAI_RQC_BASE_URL

    Example:
        >>> from stkai import STKAI
        >>> STKAI.config.rqc.request_timeout
        30
        >>> STKAI.config.rqc.retry_max_retries
        3
    """

    request_timeout: int = field(default=30, metadata={"env": "STKAI_RQC_REQUEST_TIMEOUT"})
    retry_max_retries: int = field(default=3, metadata={"env": "STKAI_RQC_RETRY_MAX_RETRIES"})
    retry_initial_delay: float = field(default=0.5, metadata={"env": "STKAI_RQC_RETRY_INITIAL_DELAY"})
    poll_interval: float = field(default=10.0, metadata={"env": "STKAI_RQC_POLL_INTERVAL"})
    poll_max_duration: float = field(default=600.0, metadata={"env": "STKAI_RQC_POLL_MAX_DURATION"})
    poll_overload_timeout: float = field(default=60.0, metadata={"env": "STKAI_RQC_POLL_OVERLOAD_TIMEOUT"})
    max_workers: int = field(default=8, metadata={"env": "STKAI_RQC_MAX_WORKERS"})
    base_url: str = field(default="https://genai-code-buddy-api.stackspot.com", metadata={"env": "STKAI_RQC_BASE_URL"})

    def validate(self) -> Self:
        """Validate RQC configuration fields."""
        if self.request_timeout <= 0:
            raise ConfigValidationError(
                "request_timeout", self.request_timeout,
                "Must be greater than 0.", section="rqc"
            )
        if self.retry_max_retries < 0:
            raise ConfigValidationError(
                "retry_max_retries", self.retry_max_retries,
                "Must be >= 0.", section="rqc"
            )
        if self.retry_initial_delay <= 0:
            raise ConfigValidationError(
                "retry_initial_delay", self.retry_initial_delay,
                "Must be greater than 0.", section="rqc"
            )
        if self.poll_interval <= 0:
            raise ConfigValidationError(
                "poll_interval", self.poll_interval,
                "Must be greater than 0.", section="rqc"
            )
        if self.poll_max_duration <= 0:
            raise ConfigValidationError(
                "poll_max_duration", self.poll_max_duration,
                "Must be greater than 0.", section="rqc"
            )
        if self.poll_overload_timeout <= 0:
            raise ConfigValidationError(
                "poll_overload_timeout", self.poll_overload_timeout,
                "Must be greater than 0.", section="rqc"
            )
        if self.max_workers <= 0:
            raise ConfigValidationError(
                "max_workers", self.max_workers,
                "Must be greater than 0.", section="rqc"
            )
        if self.base_url and not (self.base_url.startswith("http://") or self.base_url.startswith("https://")):
            raise ConfigValidationError(
                "base_url", self.base_url,
                "Must start with 'http://' or 'https://'.", section="rqc"
            )
        return self


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

        retry_max_retries: Maximum number of retry attempts for failed chat calls.
            Use 0 to disable retries (single attempt only).
            Use 3 for 4 total attempts (1 original + 3 retries).
            Env var: STKAI_AGENT_RETRY_MAX_RETRIES

        retry_initial_delay: Initial delay in seconds for the first retry attempt.
            Subsequent retries use exponential backoff (delay doubles each attempt).
            Example: with 0.5s initial delay, retries wait 0.5s, 1s, 2s, 4s...
            Env var: STKAI_AGENT_RETRY_INITIAL_DELAY

    Example:
        >>> from stkai import STKAI
        >>> STKAI.config.agent.request_timeout
        60
        >>> STKAI.config.agent.base_url
        'https://genai-inference-app.stackspot.com'
        >>> STKAI.config.agent.retry_max_retries
        0
    """

    request_timeout: int = field(default=60, metadata={"env": "STKAI_AGENT_REQUEST_TIMEOUT"})
    base_url: str = field(default="https://genai-inference-app.stackspot.com", metadata={"env": "STKAI_AGENT_BASE_URL"})
    retry_max_retries: int = field(default=3, metadata={"env": "STKAI_AGENT_RETRY_MAX_RETRIES"})
    retry_initial_delay: float = field(default=0.5, metadata={"env": "STKAI_AGENT_RETRY_INITIAL_DELAY"})

    def validate(self) -> Self:
        """Validate Agent configuration fields."""
        if self.request_timeout <= 0:
            raise ConfigValidationError(
                "request_timeout", self.request_timeout,
                "Must be greater than 0.", section="agent"
            )
        if self.base_url and not (self.base_url.startswith("http://") or self.base_url.startswith("https://")):
            raise ConfigValidationError(
                "base_url", self.base_url,
                "Must start with 'http://' or 'https://'.", section="agent"
            )
        if self.retry_max_retries < 0:
            raise ConfigValidationError(
                "retry_max_retries", self.retry_max_retries,
                "Must be >= 0.", section="agent"
            )
        if self.retry_initial_delay <= 0:
            raise ConfigValidationError(
                "retry_initial_delay", self.retry_initial_delay,
                "Must be greater than 0.", section="agent"
            )
        return self


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

    Note: HTTP 429 retry logic is handled by the Retrying class, not the rate
    limiter. The adaptive strategy only applies AIMD penalty on 429 responses.

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
            TokenAcquisitionTimeoutError. None means wait indefinitely.
            Env var: STKAI_RATE_LIMIT_MAX_WAIT_TIME

        min_rate_floor: (adaptive only) Minimum rate as fraction of max_requests.
            Prevents rate from dropping below this floor.
            Env var: STKAI_RATE_LIMIT_MIN_RATE_FLOOR

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

    # Normal fields (processed automatically by with_env_vars)
    enabled: bool = field(default=False, metadata={"env": "STKAI_RATE_LIMIT_ENABLED"})
    strategy: RateLimitStrategy = field(default="token_bucket", metadata={"env": "STKAI_RATE_LIMIT_STRATEGY"})
    # Common parameters
    max_requests: int = field(default=100, metadata={"env": "STKAI_RATE_LIMIT_MAX_REQUESTS"})
    time_window: float = field(default=60.0, metadata={"env": "STKAI_RATE_LIMIT_TIME_WINDOW"})
    # Special field (processed manually - can be None for "unlimited")
    max_wait_time: float | None = field(
        default=30.0,
        metadata={"env": "STKAI_RATE_LIMIT_MAX_WAIT_TIME", "skip": True},
    )
    # Adaptive strategy parameters (ignored if strategy != "adaptive")
    min_rate_floor: float = field(default=0.1, metadata={"env": "STKAI_RATE_LIMIT_MIN_RATE_FLOOR"})
    penalty_factor: float = field(default=0.3, metadata={"env": "STKAI_RATE_LIMIT_PENALTY_FACTOR"})
    recovery_factor: float = field(default=0.05, metadata={"env": "STKAI_RATE_LIMIT_RECOVERY_FACTOR"})

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

    def with_env_vars(self) -> Self:
        """Override to handle max_wait_time (can be None for 'unlimited')."""
        # Process normal fields via base class
        result = super().with_env_vars()

        # Process max_wait_time manually
        overrides: dict[str, Any] = {}
        if max_wait := os.environ.get("STKAI_RATE_LIMIT_MAX_WAIT_TIME"):
            if max_wait.lower() in ("none", "null", "unlimited"):
                overrides["max_wait_time"] = None
            else:
                overrides["max_wait_time"] = float(max_wait)

        return result.with_overrides(overrides, allow_none_fields={"max_wait_time"})

    def validate(self) -> Self:
        """Validate rate limit configuration fields."""
        valid_strategies = ("token_bucket", "adaptive")
        if self.strategy not in valid_strategies:
            raise ConfigValidationError(
                "strategy", self.strategy,
                f"Must be one of: {valid_strategies}.", section="rate_limit"
            )
        if self.max_requests <= 0:
            raise ConfigValidationError(
                "max_requests", self.max_requests,
                "Must be greater than 0.", section="rate_limit"
            )
        if self.time_window <= 0:
            raise ConfigValidationError(
                "time_window", self.time_window,
                "Must be greater than 0.", section="rate_limit"
            )
        if self.max_wait_time is not None and self.max_wait_time <= 0:
            raise ConfigValidationError(
                "max_wait_time", self.max_wait_time,
                "Must be greater than 0 (or None for unlimited).", section="rate_limit"
            )
        if self.min_rate_floor <= 0 or self.min_rate_floor > 1:
            raise ConfigValidationError(
                "min_rate_floor", self.min_rate_floor,
                "Must be greater than 0 and <= 1.", section="rate_limit"
            )
        if self.penalty_factor <= 0 or self.penalty_factor >= 1:
            raise ConfigValidationError(
                "penalty_factor", self.penalty_factor,
                "Must be greater than 0 and less than 1.", section="rate_limit"
            )
        if self.recovery_factor <= 0 or self.recovery_factor >= 1:
            raise ConfigValidationError(
                "recovery_factor", self.recovery_factor,
                "Must be greater than 0 and less than 1.", section="rate_limit"
            )
        return self

    # -------------------------------------------------------------------------
    # Presets
    # -------------------------------------------------------------------------

    @classmethod
    def conservative_preset(
        cls,
        max_requests: int = 20,
        time_window: float = 60.0,
    ) -> RateLimitConfig:
        """
        Conservative rate limiting preset.

        Prioritizes stability over throughput. Best for:
        - Critical batch jobs
        - CI/CD pipelines
        - Scenarios with many concurrent processes

        Behavior:
        - Waits up to 120s for tokens (patient, but not forever)
        - Aggressive penalty on 429 (halves rate)
        - Slow recovery (2% per success)
        - Can drop to 5% of max_requests under stress

        Args:
            max_requests: Maximum requests allowed in the time window.
                Calculate based on your quota and expected concurrent processes.
                Default assumes ~5 processes sharing a 100 req/min quota.
            time_window: Time window in seconds for the rate limit.

        Returns:
            RateLimitConfig with conservative settings.

        Example:
            >>> # Quota of 100 req/min, expect ~5 processes
            >>> config = RateLimitConfig.conservative_preset(max_requests=20)

            >>> # Quota of 200 req/min, expect ~4 processes
            >>> config = RateLimitConfig.conservative_preset(max_requests=50)
        """
        return cls(
            enabled=True,
            strategy="adaptive",
            max_requests=max_requests,
            time_window=time_window,
            max_wait_time=120.0,
            min_rate_floor=0.05,
            penalty_factor=0.5,
            recovery_factor=0.02,
        )

    @classmethod
    def balanced_preset(
        cls,
        max_requests: int = 40,
        time_window: float = 60.0,
    ) -> RateLimitConfig:
        """
        Balanced rate limiting preset (recommended).

        Sensible defaults for most use cases. Best for:
        - General batch processing
        - 2-3 concurrent processes
        - When unsure which preset to use

        Behavior:
        - Waits up to 30s for tokens
        - Moderate penalty on 429 (30% reduction)
        - Medium recovery (5% per success)
        - Can drop to 10% of max_requests under stress

        Args:
            max_requests: Maximum requests allowed in the time window.
                Calculate based on your quota and expected concurrent processes.
                Default assumes ~2-3 processes sharing a 100 req/min quota.
            time_window: Time window in seconds for the rate limit.

        Returns:
            RateLimitConfig with balanced settings.

        Example:
            >>> # Quota of 100 req/min, expect ~2 processes
            >>> config = RateLimitConfig.balanced_preset(max_requests=50)

            >>> # Use defaults (good for typical scenarios)
            >>> config = RateLimitConfig.balanced_preset()
        """
        return cls(
            enabled=True,
            strategy="adaptive",
            max_requests=max_requests,
            time_window=time_window,
            max_wait_time=30.0,
            min_rate_floor=0.1,
            penalty_factor=0.3,
            recovery_factor=0.05,
        )

    @classmethod
    def optimistic_preset(
        cls,
        max_requests: int = 80,
        time_window: float = 60.0,
    ) -> RateLimitConfig:
        """
        Optimistic rate limiting preset.

        Prioritizes throughput over stability. Best for:
        - Interactive/CLI usage
        - Single-process scenarios
        - When external retry logic exists

        Behavior:
        - Fails fast if can't get token in 5s
        - Light penalty on 429 (15% reduction)
        - Fast recovery (10% per success)
        - Never drops below 30% of max_requests

        Args:
            max_requests: Maximum requests allowed in the time window.
                Calculate based on your quota. Default assumes single process
                using ~80% of a 100 req/min quota.
            time_window: Time window in seconds for the rate limit.

        Returns:
            RateLimitConfig with optimistic settings.

        Example:
            >>> # Quota of 100 req/min, single process
            >>> config = RateLimitConfig.optimistic_preset(max_requests=80)

            >>> # Quota of 200 req/min, want maximum throughput
            >>> config = RateLimitConfig.optimistic_preset(max_requests=180)
        """
        return cls(
            enabled=True,
            strategy="adaptive",
            max_requests=max_requests,
            time_window=time_window,
            max_wait_time=5.0,
            min_rate_floor=0.3,
            penalty_factor=0.15,
            recovery_factor=0.1,
        )


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
                    self, new_config, source_type, overrides=kwargs
                )
                return replace(new_config, _tracker=new_tracker)

            return wrapper

        return decorator

    def with_changes_tracked(
        self,
        old_config: STKAIConfig,
        new_config: STKAIConfig,
        source_type: str,
        overrides: dict[str, Any] | None = None,
    ) -> STKAIConfigTracker:
        """
        Return new tracker with changes between configs tracked.

        Detects fields touched by the source (not just value changes) and returns
        a new tracker with those changes recorded.

        Args:
            old_config: The config before changes.
            new_config: The config after changes.
            source_type: Source label ("env", "CLI", or "user").
            overrides: For "user" source, the dict of overrides per section.

        Returns:
            New STKAIConfigTracker with detected changes tracked.
        """
        changes = self._detect_touched_fields(new_config, source_type, overrides)
        new_sources = self._merge_sources(changes, source_type, new_config)
        return STKAIConfigTracker(sources=new_sources)

    def _detect_touched_fields(
        self,
        new_config: STKAIConfig,
        source_type: str,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, list[str]]:
        """
        Detect which fields were touched by the source.

        Instead of comparing values (which misses same-value overrides),
        this method checks whether the source actually touched each field.

        Args:
            new_config: The config after changes.
            source_type: Source label ("env", "CLI", or "user").
            overrides: For "user" source, the dict of overrides per section.

        Returns:
            Dict mapping section names to lists of touched field names.
            Example: {"rqc": ["request_timeout", "base_url"]}
        """
        touched: dict[str, list[str]] = {}

        for section_name in ("auth", "rqc", "agent", "rate_limit"):
            new_section = getattr(new_config, section_name)
            touched_fields = []

            for f in fields(new_section):
                if source_type == "env":
                    # Field is touched if its env var is set and non-empty
                    # (consistent with EnvVars.get which treats empty as None)
                    env_var = f.metadata.get("env")
                    if env_var and os.environ.get(env_var):
                        touched_fields.append(f.name)

                elif source_type == "CLI":
                    # CLI touches base_url in rqc and agent sections
                    if f.name == "base_url":
                        from stkai._cli import StkCLI
                        if section_name == "rqc" and StkCLI.get_codebuddy_base_url() is not None:
                            touched_fields.append(f.name)
                        elif section_name == "agent" and StkCLI.get_inference_app_base_url() is not None:
                            touched_fields.append(f.name)

                elif source_type == "user" and overrides:
                    # Field is touched if it's in the overrides dict for this section
                    section_overrides = overrides.get(section_name) or {}
                    if f.name in section_overrides:
                        touched_fields.append(f.name)

            if touched_fields:
                touched[section_name] = touched_fields

        return touched

    def _merge_sources(
        self,
        changes: dict[str, list[str]],
        source_type: str,
        config: STKAIConfig | None = None,
    ) -> dict[str, dict[str, str]]:
        """
        Merge detected changes into existing sources.

        Args:
            changes: Dict of section -> list of touched field names.
            source_type: Source label ("env", "CLI", or "user").
            config: The config to read env var names from field metadata.

        Returns:
            New sources dict with changes merged in.
        """
        new_sources = self._copy_sources()

        for section, field_names in changes.items():
            section_sources = new_sources.setdefault(section, {})
            section_config = getattr(config, section) if config else None

            for field_name in field_names:
                if source_type == "env" and section_config:
                    # Read env var name from field metadata
                    env_var = None
                    for f in fields(section_config):
                        if f.name == field_name:
                            env_var = f.metadata.get("env")
                            break
                    if env_var:
                        section_sources[field_name] = f"env:{env_var}"
                    else:
                        # Fallback to convention if no metadata
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

    Aggregates all configuration sections: sdk, auth, rqc, agent, and rate_limit.
    Access via the global `STKAI.config` property.

    Attributes:
        sdk: SDK metadata (version, cli_mode). Read-only.
        auth: Authentication configuration.
        rqc: RemoteQuickCommand configuration.
        agent: Agent configuration.
        rate_limit: Rate limiting configuration for HTTP clients.

    Example:
        >>> from stkai import STKAI
        >>> STKAI.config.sdk.version
        '0.2.8'
        >>> STKAI.config.sdk.cli_mode
        True
        >>> STKAI.config.rqc.request_timeout
        30
        >>> STKAI.config.auth.has_credentials()
        False
        >>> STKAI.config.rate_limit.enabled
        False
    """

    sdk: SdkConfig = field(default_factory=SdkConfig.detect)
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
            sdk=self.sdk,
            auth=self.auth.with_env_vars(),
            rqc=self.rqc.with_env_vars(),
            agent=self.agent.with_env_vars(),
            rate_limit=self.rate_limit.with_env_vars(),
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
        if codebuddy_base_url := StkCLI.get_codebuddy_base_url():
            cli_rqc_overrides["base_url"] = codebuddy_base_url

        cli_agent_overrides: dict[str, Any] = {}
        if inference_app_base_url := StkCLI.get_inference_app_base_url():
            cli_agent_overrides["base_url"] = inference_app_base_url

        return STKAIConfig(
            sdk=self.sdk,
            auth=self.auth,
            rqc=self.rqc.with_overrides(cli_rqc_overrides),
            agent=self.agent.with_overrides(cli_agent_overrides),
            rate_limit=self.rate_limit,
        )

    @STKAIConfigTracker.track_changes("user")
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
            sdk=self.sdk,
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
            >>> for entry in data["rqc"]:
            ...     print(f"{entry.name}: {entry.value} ({entry.source})")
            request_timeout: 30 (default)
            ...
        """
        result: dict[str, list[ConfigEntry]] = {}

        # SDK section (read-only, not tracked)
        result["sdk"] = [
            ConfigEntry(name=f.name, value=getattr(self.sdk, f.name), source="-")
            for f in fields(self.sdk)
        ]

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
            ConfigValidationError: If any config value fails validation.

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

        return self.validate()

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
        Validates the configuration after reset.

        Returns:
            The reset STKAIConfig instance.

        Raises:
            ConfigValidationError: If any config value is invalid.

        Example:
            >>> from stkai import STKAI
            >>> STKAI.reset()
        """
        self._config = STKAIConfig().with_env_vars().with_cli_defaults()
        return self.validate()

    def validate(self) -> STKAIConfig:
        """
        Validate current configuration.

        Checks all config sections for invalid values. Called automatically
        on module load and after configure(). Can also be called manually
        to re-validate after environment changes.

        Returns:
            The validated STKAIConfig instance.

        Raises:
            ConfigValidationError: If any config value is invalid.

        Example:
            >>> from stkai import STKAI
            >>> STKAI.validate()  # Re-validate current config
        """
        self._config.auth.validate()
        self._config.rqc.validate()
        self._config.agent.validate()
        self._config.rate_limit.validate()
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
        name_width = 25  # field name + dots
        value_width = 50  # max value width (matches truncation)
        total_width = 2 + name_width + 2 + (value_width + 2) + 1 + 8  # matches separator

        output("STKAI Configuration:")
        output("=" * total_width)

        # Header
        output(f"  {'Field':<{name_width}} │ {'Value':<{value_width}} │ Source")
        output(f"--{'-' * name_width}-+{'-' * (value_width + 2)}+--------")

        for section_name, entries in self._config.explain_data().items():
            output(f"[{section_name}]")
            for entry in entries:
                dots = "." * (name_width - len(entry.name))
                value_padded = entry.formatted_value.ljust(value_width)
                marker = "✎" if entry.source not in ("default", "-") else " "
                output(f"  {entry.name} {dots} {value_padded} {marker} {entry.source}")

        output("=" * total_width)

    def __repr__(self) -> str:
        return f"STKAI(config={self._config!r})"


# Global singleton instance - always reflects current configuration
STKAI: _STKAI = _STKAI()
STKAI.validate()  # Validate defaults + env vars on module load
