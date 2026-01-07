# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/claude-code) when working with code in this repository.

## Project Overview

**stkai** is a Python SDK for StackSpot AI that provides a client abstraction for executing Remote Quick Commands (RQC). It simplifies sending requests to StackSpot AI's LLM-powered quick commands and handling their responses.

## Tech Stack

- **Language**: Python 3.12+
- **Dependencies**: `requests` (HTTP client)
- **Dev Tools**: pytest, mypy, ruff
- **External Dependency**: StackSpot CLI (`oscli`) for authentication

## Project Structure

```
src/stkai/
├── __init__.py                    # Public API exports (RemoteQuickCommand, RqcRequest, RqcResponse)
├── agents/                        # Future: AI agents module (placeholder)
└── rqc/                           # Remote Quick Commands module
    ├── __init__.py                # RQC public API exports
    ├── _remote_quick_command.py   # Core: RemoteQuickCommand client, RqcRequest, RqcResponse, RqcEventListener
    ├── _handlers.py               # Result handlers: JsonResultHandler, RawResultHandler, ChainedResultHandler
    ├── _event_listeners.py        # Event listeners: FileLoggingListener
    ├── _http.py                   # HTTP client: StkCLIRqcHttpClient (uses oscli for auth)
    └── _utils.py                  # Internal utilities: sleep_with_jitter, save_json_file

tests/
└── rqc/
    ├── test_remote_quick_command.py
    ├── test_handlers.py
    └── test_event_listeners.py
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
