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
├── _config.py                     # Global config: STKAI singleton (configure, config, reset)
├── _http.py                       # HTTP clients: EnvironmentAwareHttpClient, StkCLIHttpClient, StandaloneHttpClient, RateLimitedHttpClient, AdaptiveRateLimitedHttpClient
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

**Configuration options:** `CreateExecutionOptions`, `GetResultOptions`

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

3. **ChatResponse**: Response data model with `status`, `message`, `token_usage`
   - Status: `SUCCESS`, `ERROR`, `TIMEOUT`
   - Helper methods: `is_success()`, `is_error()`, `is_timeout()`

**Configuration options:** `AgentOptions`

**Rate Limiting:** Agent uses `EnvironmentAwareHttpClient` which supports automatic rate limiting. See [HTTP Client > Rate Limiting](#rate-limiting) for details.

### HTTP Client

**Available implementations:**
- `EnvironmentAwareHttpClient`: Auto-detects environment (CLI or standalone). **Default.**
- `StkCLIHttpClient`: Uses StackSpot CLI (oscli) for authentication.
- `StandaloneHttpClient`: Uses `AuthProvider` for standalone authentication.
- `RateLimitedHttpClient`: Decorator with Token Bucket rate limiting.
- `AdaptiveRateLimitedHttpClient`: Decorator with adaptive AIMD rate limiting.

#### Rate Limiting

The SDK supports automatic rate limiting via `STKAI.configure()`. When enabled, `EnvironmentAwareHttpClient` automatically wraps HTTP requests with rate limiting.

**Available strategies:**
| Strategy | Algorithm | Use Case |
|----------|-----------|----------|
| `token_bucket` | Token Bucket | Simple, predictable rate limiting |
| `adaptive` | AIMD (Additive Increase, Multiplicative Decrease) | Dynamic environments with shared quotas, handles HTTP 429 |

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
STKAI_RATE_LIMIT_MAX_RETRIES_ON_429=3
STKAI_RATE_LIMIT_PENALTY_FACTOR=0.2
STKAI_RATE_LIMIT_RECOVERY_FACTOR=0.01
```

**RateLimitConfig fields:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `False` | Enable rate limiting |
| `strategy` | `"token_bucket"` \| `"adaptive"` | `"token_bucket"` | Rate limiting algorithm |
| `max_requests` | `int` | `100` | Max requests per time window |
| `time_window` | `float` | `60.0` | Time window in seconds |
| `max_wait_time` | `float \| None` | `60.0` | Max wait for token (None = unlimited) |
| `min_rate_floor` | `float` | `0.1` | (adaptive) Min rate as fraction of max |
| `max_retries_on_429` | `int` | `3` | (adaptive) Retries on HTTP 429 |
| `penalty_factor` | `float` | `0.2` | (adaptive) Rate reduction on 429 |
| `recovery_factor` | `float` | `0.01` | (adaptive) Rate increase on success |

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
- `AuthConfig`: `client_id`, `client_secret`, `token_url`
- `RqcConfig`: `request_timeout`, `max_retries`, `poll_interval`, `poll_max_duration`, etc.
- `AgentConfig`: `request_timeout`, `base_url`
- `RateLimitConfig`: `enabled`, `strategy`, `max_requests`, etc. (see [HTTP Client > Rate Limiting](#rate-limiting))

**Precedence (highest to lowest):**
1. Environment variables (`STKAI_*`)
2. Values set via `STKAI.configure()`
3. Hardcoded defaults

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
| `stkai` (root) | Main clients, requests, responses, configs, HTTP clients | `RemoteQuickCommand`, `Agent`, `RqcRequest`, `ChatRequest`, `STKAI`, `RateLimitConfig`, `RateLimitStrategy`, `EnvironmentAwareHttpClient` |
| `stkai.rqc` | RQC-specific handlers, listeners, options | `JsonResultHandler`, `FileLoggingListener`, `RqcEventListener` |
| `stkai.agents` | Agent-specific handlers, listeners, options | (future: `AgentEventListener`, etc.) |

**Rationale:**
- 80% of users only need root imports (simple usage)
- Advanced users import from submodules for customization
- Prevents naming conflicts (e.g., `rqc.JsonResultHandler` vs `agents.JsonResultHandler`)

**Import examples:**
```python
# Common usage - root imports
from stkai import RemoteQuickCommand, Agent, RqcRequest, ChatRequest, STKAI

# Configuration (with rate limiting)
STKAI.configure(
    auth={"client_id": "...", "client_secret": "..."},
    rate_limit={"enabled": True, "strategy": "token_bucket", "max_requests": 10},
)
print(STKAI.config.rqc.request_timeout)
print(STKAI.config.rate_limit.enabled)  # True

# Advanced usage - submodule imports
from stkai.rqc import JsonResultHandler, ChainedResultHandler, FileLoggingListener
```
