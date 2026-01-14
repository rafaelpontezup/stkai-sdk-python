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
├── _http.py                       # HTTP clients: EnvironmentAwareHttpClient, StkCLIHttpClient, StandaloneHttpClient, RateLimitedHttpClient
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

### Key Classes

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

### Configuration Classes

- **CreateExecutionOptions**: `max_retries`, `backoff_factor`, `request_timeout`
- **GetResultOptions**: `poll_interval`, `poll_max_duration`, `overload_timeout`, `request_timeout`

### Execution Flow

1. Create execution via POST to StackSpot AI API
2. Poll for status via GET until terminal state
3. Process result through handler pipeline
4. Notify event listeners throughout lifecycle

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
| `stkai` (root) | Main clients, requests, responses, configs, HTTP clients | `RemoteQuickCommand`, `Agent`, `RqcRequest`, `ChatRequest`, `STKAI`, `EnvironmentAwareHttpClient` |
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

# Configuration
STKAI.configure(auth={"client_id": "...", "client_secret": "..."})
print(STKAI.config.rqc.request_timeout)

# Advanced usage - submodule imports
from stkai.rqc import JsonResultHandler, ChainedResultHandler, FileLoggingListener
```
