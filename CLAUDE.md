# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/claude-code) when working with code in this repository.

## Project Overview

**stkai** is a Python SDK for StackSpot AI that provides client abstractions for:

- **Remote Quick Commands (RQC)**: Execute LLM-powered quick commands with polling, retries, and batch execution
- **Agents**: Interact with StackSpot AI Agents for conversational AI capabilities

## Tech Stack

- **Language**: Python 3.12+
- **Dependencies**: `requests` (HTTP client)
- **Dev Tools**: pytest, mypy, ruff
- **Authentication**: StackSpot CLI (`oscli`) OR client credentials (environment variables)

## Project Structure

```
src/stkai/
├── __init__.py                    # Public API exports (root module)
├── _auth.py                       # Authentication: AuthProvider, ClientCredentialsAuthProvider
├── _cli.py                        # CLI abstraction: StkCLI (is_available, get_codebuddy_base_url, get_inference_app_base_url)
├── _config.py                     # Global config: STKAI singleton (configure, config, reset, explain)
├── _http.py                       # HTTP clients: HttpClient (ABC), EnvironmentAwareHttpClient, StkCLIHttpClient, StandaloneHttpClient
├── _rate_limit.py                 # Rate limiting: TokenBucketRateLimitedHttpClient, AdaptiveRateLimitedHttpClient, exceptions
├── _utils.py                      # Internal utilities
├── agents/                        # AI Agents module
│   ├── __init__.py                # Agents public API exports
│   ├── _agent.py                  # Agent client
│   └── _models.py                 # ChatRequest, ChatResponse, ChatStatus
└── rqc/                           # Remote Quick Commands module
    ├── __init__.py                # RQC public API exports
    ├── _remote_quick_command.py   # RemoteQuickCommand client
    ├── _models.py                 # RqcRequest, RqcResponse, RqcExecutionStatus
    ├── _handlers.py               # Result handlers: JsonResultHandler, RawResultHandler, ChainedResultHandler
    └── _event_listeners.py        # Event listeners: FileLoggingListener, RqcEventListener

tests/
├── test_auth.py
├── test_cli.py
├── test_config.py
├── test_http.py
├── agents/
│   └── test_agent.py
└── rqc/
    ├── test_remote_quick_command.py
    ├── test_handlers.py
    └── test_event_listeners.py
```

## Development Environment

This project uses **Python virtual environment (venv)**. Always activate it before running commands:

```bash
# Activate virtual environment (required before any command)
source .venv/bin/activate
```

## Common Commands

```bash
# Install dependencies (dev mode)
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=src

# Run linter
ruff check src tests

# Run type checker
mypy src
```

## Architecture Notes

### Remote Quick Commands

**Key Classes:**

1. **RemoteQuickCommand**: Main client class for executing quick commands
   - `execute()`: Single request execution (blocking)
   - `execute_many()`: Batch execution with thread pool (blocking)

2. **RqcRequest**: Request data model with `payload`, `id`, `metadata`
   - Auto-generates UUID if `id` not provided
   - Tracks `execution_id` and `submitted_at` after submission

3. **RqcResponse**: Response data model with `status`, `result`, `error`
   - Status: `COMPLETED`, `FAILURE`, `ERROR`, `TIMEOUT`
   - Helper methods: `is_completed()`, `is_failure()`, `is_error()`, `is_timeout()`

4. **RqcResultHandler**: Interface for processing raw LLM responses
   - `JsonResultHandler` (default): Parses JSON, handles markdown code blocks
   - `RawResultHandler`: Returns raw response
   - `ChainedResultHandler`: Pipeline of handlers

5. **RqcEventListener**: Interface for lifecycle events
   - `on_before_execute()`: Before request starts
   - `on_status_change()`: During polling
   - `on_after_execute()`: After completion (success or failure)
   - `FileLoggingListener`: Built-in implementation that saves request/response to JSON files

6. **RqcOptions**: Consolidated configuration with `with_defaults_from(cfg)` pattern
   - `create_execution`: Options for the create-execution phase (`CreateExecutionOptions`)
   - `get_result`: Options for the polling phase (`GetResultOptions`)
   - `max_workers`: Max threads for batch execution
   - Fields set to `None` use defaults from `STKAI.config.rqc` (Single Source of Truth)

**Rate Limiting:** RQC uses `EnvironmentAwareHttpClient` which supports automatic rate limiting. See [HTTP Client > Rate Limiting](#rate-limiting) for details.

**Execution Flow:**
1. Create execution via POST to StackSpot AI API
2. Poll for status via GET until terminal state
3. Process result through handler pipeline
4. Notify event listeners throughout lifecycle

### Agents

**Key Classes:**

1. **Agent**: Main client class for chatting with AI agents
   - `chat()`: Send a chat request (blocking)

2. **ChatRequest**: Request data model with `user_prompt`, `conversation_id`, etc.

3. **ChatResponse**: Response data model with `status`, `result`, `error`, `raw_response`
   - Status: `SUCCESS`, `ERROR`, `TIMEOUT`
   - Helper methods: `is_success()`, `is_error()`, `is_timeout()`, `error_with_details()`
   - Properties (from `raw_response`): `raw_result`, `stop_reason`, `tokens`, `conversation_id`, `knowledge_sources`

4. **AgentOptions**: Configuration with `with_defaults_from(cfg)` pattern
   - `request_timeout`: HTTP timeout in seconds
   - `retry_max_retries`: Max retry attempts (0 = disabled, 3 = 4 total attempts)
   - `retry_initial_delay`: Initial delay for first retry (subsequent retries double)
   - Fields set to `None` use defaults from `STKAI.config.agent` (Single Source of Truth)

**Retry:** Agent automatically retries on HTTP 5xx, 408, 429, and network errors with exponential backoff. HTTP 429 respects `Retry-After` header. Retry is handled by `Retrying` class.

**Rate Limiting:** Agent uses `EnvironmentAwareHttpClient` which supports automatic rate limiting. See [HTTP Client > Rate Limiting](#rate-limiting) for details.

### HTTP Client

**Available implementations:**
- `EnvironmentAwareHttpClient`: Auto-detects environment (CLI or standalone). **Default.**
- `StkCLIHttpClient`: Uses StackSpot CLI (oscli) for authentication.
- `StandaloneHttpClient`: Uses `AuthProvider` for standalone authentication.
- `TokenBucketRateLimitedHttpClient`: Decorator with Token Bucket rate limiting.
- `AdaptiveRateLimitedHttpClient`: Decorator with adaptive AIMD rate limiting.
- `CongestionAwareHttpClient`: (EXPERIMENTAL) Latency-based concurrency control using Little's Law.

#### Rate Limiting

**Terminology note:** The SDK uses "rate limiting" terminology, but the implementations are technically **throttling** (proactive client-side control that delays requests) rather than rate limiting (reactive server-side rejection). The SDK uses "rate limiting" because it's the industry-standard term developers search for. The behavior is hybrid: **throttling** (delays requests waiting for tokens) + **rejection** (exceptions when `max_wait_time` exceeded or server returns 429).

The SDK supports automatic rate limiting via `STKAI.configure()`. When enabled, `EnvironmentAwareHttpClient` automatically wraps HTTP requests with rate limiting.

**Available strategies:**
| Strategy | Algorithm | Use Case |
|----------|-----------|----------|
| `token_bucket` | Token Bucket | Simple, predictable rate limiting |
| `adaptive` | AIMD + Jitter (±20% on penalty/recovery/sleep) | Dynamic environments with shared quotas |

**Note on `adaptive` jitter:** The adaptive strategy applies ±20% jitter to penalty_factor, recovery_factor, and token wait sleep times. This desynchronizes processes sharing a quota, preventing thundering herd effects and synchronized oscillations. Each process has a deterministic RNG seeded with hostname+pid.

**Note:** HTTP 429 retry logic is handled by the `Retrying` class (in `_retry.py`), not the rate limiter. The adaptive strategy applies AIMD penalty on 429 responses (reduces rate) and raises `ServerSideRateLimitError` for `Retrying` to handle with backoff and `Retry-After` header support.

**Note on `CongestionAwareHttpClient` (EXPERIMENTAL):** This is an experimental decorator that adds latency-based concurrency control using Little's Law (`pressure = throughput × latency`). It is designed to be composed with rate limiters:

```python
# Composition: RateLimiter wraps CongestionAware wraps HttpClient
base = StkCLIHttpClient()
congestion = CongestionAwareHttpClient(delegate=base, pressure_threshold=2.0)
client = AdaptiveRateLimitedHttpClient(delegate=congestion, max_requests=100)
```

**When to consider:** This decorator MAY be useful when:
1. The server degrades gracefully (latency increases before returning 429s)
2. You want standalone concurrency control without rate limiting
3. Long-running requests where concurrency matters more than rate

**Caveat:** In most scenarios with API quotas, the AIMD rate limiter (`adaptive`) reacts to 429 responses faster than latency-based detection can detect congestion. Simulations showed that combining `CongestionAwareHttpClient` with `AdaptiveRateLimitedHttpClient` provides minimal additional benefit over using `adaptive` alone.

**Exception Hierarchy:**
```
RetryableError (base - automatically retried)
├── ClientSideRateLimitError      # Base for client-side rate limit errors
│   └── TokenAcquisitionTimeoutError     # Timeout waiting for token (max_wait_time exceeded)
└── ServerSideRateLimitError      # HTTP 429 from server (contains response for Retry-After)
```

| Scenario | Exception | Raised By |
|----------|-----------|-----------|
| Token wait timeout | `TokenAcquisitionTimeoutError` | `TokenBucketRateLimitedHttpClient`, `AdaptiveRateLimitedHttpClient` |
| Server HTTP 429 (with Adaptive) | `ServerSideRateLimitError` | `AdaptiveRateLimitedHttpClient` |
| Server HTTP 429 (without Adaptive) | `requests.HTTPError` | Direct from `requests` |

**Configuration via code:**
```python
from stkai import STKAI

# Token Bucket (simple)
STKAI.configure(
    rate_limit={
        "enabled": True,
        "strategy": "token_bucket",
        "max_requests": 10,
        "time_window": 60.0,
    }
)

# Adaptive (AIMD + 429 handling)
STKAI.configure(
    rate_limit={
        "enabled": True,
        "strategy": "adaptive",
        "max_requests": 100,
        "min_rate_floor": 0.1,
    }
)

# Unlimited wait time
STKAI.configure(rate_limit={"max_wait_time": None})  # or "unlimited"
```

**Configuration via environment variables:**
```bash
STKAI_RATE_LIMIT_ENABLED=true
STKAI_RATE_LIMIT_STRATEGY=adaptive
STKAI_RATE_LIMIT_MAX_REQUESTS=50
STKAI_RATE_LIMIT_TIME_WINDOW=60.0
STKAI_RATE_LIMIT_MAX_WAIT_TIME=unlimited  # or "none", "null"
STKAI_RATE_LIMIT_MIN_RATE_FLOOR=0.1
STKAI_RATE_LIMIT_PENALTY_FACTOR=0.2
STKAI_RATE_LIMIT_RECOVERY_FACTOR=0.05
```

**RateLimitConfig fields:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `False` | Enable rate limiting |
| `strategy` | `"token_bucket"` \| `"adaptive"` | `"token_bucket"` | Rate limiting algorithm |
| `max_requests` | `int` | `100` | Max requests per time window |
| `time_window` | `float` | `60.0` | Time window in seconds |
| `max_wait_time` | `float \| None` | `45.0` | Max wait for token (None = unlimited) |
| `min_rate_floor` | `float` | `0.1` | (adaptive) Min rate as fraction of max |
| `penalty_factor` | `float` | `0.3` | (adaptive) Rate reduction on 429 |
| `recovery_factor` | `float` | `0.05` | (adaptive) Rate increase on success |

**Presets:** For common scenarios, use presets instead of manual configuration:
```python
from dataclasses import asdict
from stkai import STKAI, RateLimitConfig

# Conservative: stability over throughput (critical jobs, many processes)
STKAI.configure(rate_limit=asdict(RateLimitConfig.conservative_preset(max_requests=20)))

# Balanced: sensible defaults (general use, 2-5 processes)
STKAI.configure(rate_limit=asdict(RateLimitConfig.balanced_preset(max_requests=50)))

# Optimistic: throughput over stability (interactive/CLI, single process)
STKAI.configure(rate_limit=asdict(RateLimitConfig.optimistic_preset(max_requests=80)))
```

### Configuration

**Global configuration singleton:** `STKAI`

```python
from stkai import STKAI

STKAI.configure(
    auth={"client_id": "...", "client_secret": "..."},
    rqc={"request_timeout": 60},
    agent={"request_timeout": 120},
    rate_limit={"enabled": True, "strategy": "token_bucket"},
)
```

**Configuration classes:**
- `SdkConfig`: `version`, `cli_mode` (read-only, auto-detected)
- `AuthConfig`: `client_id`, `client_secret`, `token_url`
- `RqcConfig`: `request_timeout`, `retry_max_retries`, `retry_initial_delay`, `poll_interval`, `poll_max_duration`, etc.
- `AgentConfig`: `request_timeout`, `base_url`, `retry_max_retries`, `retry_initial_delay`
- `RateLimitConfig`: `enabled`, `strategy`, `max_requests`, etc. (see [HTTP Client > Rate Limiting](#rate-limiting))
- `ConfigEntry`: Represents a config field with its value and source (used by `explain()`)

**Precedence (highest to lowest):**
1. Values set via `STKAI.configure()`
2. StackSpot CLI values (`oscli`) - if CLI is available
3. Environment variables (`STKAI_*`)
4. Hardcoded defaults

**Debugging Configuration:**
Use `STKAI.explain()` to print current config with sources:
```python
STKAI.explain()  # or STKAI.explain(output=logging.info)
```
This shows each config field's value and where it came from (`default`, `env:VAR_NAME`, `CLI`, or `user`).

**CLI vs Credentials:**
When both CLI (`oscli`) and credentials are available, CLI takes precedence. A warning is logged:
```
⚠️ Auth credentials detected (via env vars or configure) but running in CLI mode.
Authentication will be handled by oscli. Credentials will be ignored.
```

### Code Conventions

- Private modules prefixed with `_` (e.g., `_remote_quick_command.py`)
- Type hints required (strict mypy)
- Assertions for internal sanity checks with `"🌀 Sanity check |"` prefix
- Logging format: `{id} | RQC | {message}`
- Dataclasses with `frozen=True` for immutable config objects

### Module Export Conventions

The SDK uses a **hybrid namespace** approach to balance simplicity and avoid naming conflicts:

| Location | What to Export | Example |
|----------|----------------|---------|
| `stkai` (root) | Main clients, requests, responses, configs, HTTP clients, CLI | `RemoteQuickCommand`, `Agent`, `RqcRequest`, `RqcOptions`, `ChatRequest`, `STKAI`, `StkCLI`, `RateLimitConfig`, `RateLimitStrategy`, `ConfigEntry`, `EnvironmentAwareHttpClient` |
| `stkai.rqc` | RQC-specific handlers, listeners, options | `JsonResultHandler`, `FileLoggingListener`, `RqcEventListener`, `CreateExecutionOptions`, `GetResultOptions` |
| `stkai.agents` | Agent-specific handlers, listeners, options | `AgentOptions` (future: `AgentEventListener`, etc.) |

**Rationale:**
- 80% of users only need root imports (simple usage)
- Advanced users import from submodules for customization
- Prevents naming conflicts (e.g., `rqc.JsonResultHandler` vs `agents.JsonResultHandler`)

**Import examples:**
```python
# Common usage - root imports
from stkai import RemoteQuickCommand, Agent, RqcRequest, RqcOptions, ChatRequest, STKAI, StkCLI, ConfigEntry

# Configuration (with rate limiting)
STKAI.configure(
    auth={"client_id": "...", "client_secret": "..."},
    rate_limit={"enabled": True, "strategy": "token_bucket", "max_requests": 10},
)
print(STKAI.config.rqc.request_timeout)
print(STKAI.config.rate_limit.enabled)  # True

# Debug configuration
STKAI.explain()  # prints all config values with their sources

# RQC with custom options (partial override - rest from STKAI.config)
from stkai.rqc import CreateExecutionOptions
rqc = RemoteQuickCommand(
    slug_name="my-rqc",
    base_url="https://custom.api.com",  # optional
    options=RqcOptions(
        create_execution=CreateExecutionOptions(retry_max_retries=10),
    ),
)

# Agent with custom options
from stkai.agents import AgentOptions
agent = Agent(
    agent_id="my-agent",
    base_url="https://custom.api.com",  # optional
    options=AgentOptions(request_timeout=120),
)

# Advanced usage - submodule imports for handlers/listeners
from stkai.rqc import JsonResultHandler, ChainedResultHandler, FileLoggingListener
```
