# Configuration

The SDK provides a flexible configuration system with sensible defaults that can be customized via code or environment variables.

## Configuration Hierarchy

Settings are resolved in this order (highest precedence first):

1. **Options passed to client constructors** (e.g., `AgentOptions`)
2. **Values set via `STKAI.configure()`**
3. **Environment variables** (`STKAI_*`)
4. **Hardcoded defaults**

## Quick Configuration

### Via Code

```python
from stkai import STKAI

STKAI.configure(
    auth={
        "client_id": "your-client-id",
        "client_secret": "your-client-secret",
    },
    rqc={
        "request_timeout": 60,
        "max_retries": 5,
    },
    agent={
        "request_timeout": 120,
    },
)
```

### Via Environment Variables

```bash
# Authentication
export STKAI_AUTH_CLIENT_ID="your-client-id"
export STKAI_AUTH_CLIENT_SECRET="your-client-secret"

# RQC settings
export STKAI_RQC_REQUEST_TIMEOUT=60
export STKAI_RQC_MAX_RETRIES=5

# Agent settings
export STKAI_AGENT_REQUEST_TIMEOUT=120
```

### Using with python-dotenv

!!! warning "Import Order Matters"
    The SDK reads environment variables **at import time**. If you use `python-dotenv`, you must load the `.env` file **before** importing from `stkai`.

```python
# Correct: load dotenv BEFORE importing stkai
from dotenv import load_dotenv
load_dotenv()

from stkai import RemoteQuickCommand, create_standalone_auth

auth = create_standalone_auth()  # Works!
```

```python
# Wrong: importing stkai BEFORE loading dotenv
from stkai import RemoteQuickCommand, create_standalone_auth
from dotenv import load_dotenv

load_dotenv()  # Too late! stkai already loaded with empty env vars

auth = create_standalone_auth()  # Fails: credentials not found
```

**Alternative:** If you cannot control import order, call `STKAI.configure()` after loading the `.env`:

```python
from stkai import RemoteQuickCommand, STKAI
from dotenv import load_dotenv

load_dotenv()
STKAI.configure()  # Reloads configuration with env vars

# Now it works
```

## Accessing Configuration

Use `STKAI.config` to access current settings:

```python
from stkai import STKAI

# Check current values
print(STKAI.config.rqc.request_timeout)  # 30
print(STKAI.config.agent.base_url)       # https://genai-inference-app.stackspot.com

# Check if credentials are configured
if STKAI.config.auth.has_credentials():
    print("Standalone auth available")
```

## Configuration Sections

### AuthConfig

Authentication settings for standalone mode (without StackSpot CLI):

| Field | Env Var | Default | Description |
|-------|---------|---------|-------------|
| `client_id` | `STKAI_AUTH_CLIENT_ID` | `None` | StackSpot client ID |
| `client_secret` | `STKAI_AUTH_CLIENT_SECRET` | `None` | StackSpot client secret |
| `token_url` | `STKAI_AUTH_TOKEN_URL` | StackSpot IdM URL | OAuth2 token endpoint |

```python
from stkai import STKAI

if STKAI.config.auth.has_credentials():
    # Standalone auth is configured
    pass
```

### RqcConfig

Settings for `RemoteQuickCommand` clients:

| Field | Env Var | Default | Description |
|-------|---------|---------|-------------|
| `request_timeout` | `STKAI_RQC_REQUEST_TIMEOUT` | 30 | HTTP timeout (seconds) |
| `max_retries` | `STKAI_RQC_MAX_RETRIES` | 3 | Retry attempts for POST |
| `backoff_factor` | `STKAI_RQC_BACKOFF_FACTOR` | 0.5 | Exponential backoff factor |
| `poll_interval` | `STKAI_RQC_POLL_INTERVAL` | 10.0 | Seconds between polls |
| `poll_max_duration` | `STKAI_RQC_POLL_MAX_DURATION` | 600.0 | Max polling duration |
| `overload_timeout` | `STKAI_RQC_OVERLOAD_TIMEOUT` | 60.0 | Max CREATED state duration |
| `max_workers` | `STKAI_RQC_MAX_WORKERS` | 8 | Concurrent workers |
| `base_url` | `STKAI_RQC_BASE_URL` | StackSpot API URL | API base URL |

### AgentConfig

Settings for `Agent` clients:

| Field | Env Var | Default | Description |
|-------|---------|---------|-------------|
| `request_timeout` | `STKAI_AGENT_REQUEST_TIMEOUT` | 60 | HTTP timeout (seconds) |
| `base_url` | `STKAI_AGENT_BASE_URL` | StackSpot API URL | API base URL |

### RateLimitConfig

Settings for automatic rate limiting of HTTP requests. When enabled, `EnvironmentAwareHttpClient` automatically wraps requests with rate limiting.

| Field | Env Var | Default | Description |
|-------|---------|---------|-------------|
| `enabled` | `STKAI_RATE_LIMIT_ENABLED` | `False` | Enable rate limiting |
| `strategy` | `STKAI_RATE_LIMIT_STRATEGY` | `"token_bucket"` | Algorithm: `"token_bucket"` or `"adaptive"` |
| `max_requests` | `STKAI_RATE_LIMIT_MAX_REQUESTS` | 100 | Max requests per time window |
| `time_window` | `STKAI_RATE_LIMIT_TIME_WINDOW` | 60.0 | Time window in seconds |
| `max_wait_time` | `STKAI_RATE_LIMIT_MAX_WAIT_TIME` | 60.0 | Max wait for token (None = unlimited) |
| `min_rate_floor` | `STKAI_RATE_LIMIT_MIN_RATE_FLOOR` | 0.1 | (adaptive) Min rate as fraction |
| `max_retries_on_429` | `STKAI_RATE_LIMIT_MAX_RETRIES_ON_429` | 3 | (adaptive) Retries on HTTP 429 |
| `penalty_factor` | `STKAI_RATE_LIMIT_PENALTY_FACTOR` | 0.2 | (adaptive) Rate reduction on 429 |
| `recovery_factor` | `STKAI_RATE_LIMIT_RECOVERY_FACTOR` | 0.01 | (adaptive) Rate increase on success |

```python
from stkai import STKAI

STKAI.configure(
    rate_limit={
        "enabled": True,
        "strategy": "token_bucket",
        "max_requests": 30,
        "time_window": 60.0,
    }
)
```

!!! tip "Detailed Guide"
    See [HTTP Client > Rate Limiting](http-client.md#rate-limiting) for strategies comparison, use cases, and advanced configuration.

## Example Configurations

### Production with Environment Variables

```bash
# .env or shell profile
export STKAI_AUTH_CLIENT_ID="prod-client-id"
export STKAI_AUTH_CLIENT_SECRET="prod-secret"
export STKAI_RQC_POLL_MAX_DURATION=1200  # 20 minutes
export STKAI_AGENT_REQUEST_TIMEOUT=180    # 3 minutes
```

```python
# No configuration needed in code - env vars are loaded automatically
from stkai import RemoteQuickCommand, Agent

rqc = RemoteQuickCommand(slug_name="my-command")
agent = Agent(agent_id="my-agent")
```

### Testing with Mock Settings

```python
from stkai import STKAI

# Configure for testing
STKAI.configure(
    rqc={
        "request_timeout": 5,      # Fast timeout for tests
        "poll_interval": 0.1,      # Fast polling
        "poll_max_duration": 10,   # Short max wait
    },
    allow_env_override=False,      # Ignore env vars in tests
)
```

### CI/CD Pipeline

```yaml
# GitHub Actions example
env:
  STKAI_AUTH_CLIENT_ID: ${{ secrets.STKAI_CLIENT_ID }}
  STKAI_AUTH_CLIENT_SECRET: ${{ secrets.STKAI_CLIENT_SECRET }}
  STKAI_RQC_MAX_WORKERS: 4
```

## Overriding at Client Level

You can override global settings per-client:

```python
from stkai import RemoteQuickCommand, Agent
from stkai.rqc import CreateExecutionOptions, GetResultOptions
from stkai.agents import AgentOptions

# Override RQC settings
rqc = RemoteQuickCommand(
    slug_name="my-command",
    create_execution_options=CreateExecutionOptions(
        request_timeout=60,  # Override global
    ),
    get_result_options=GetResultOptions(
        poll_interval=5.0,   # Override global
    ),
)

# Override Agent settings
agent = Agent(
    agent_id="my-agent",
    options=AgentOptions(
        request_timeout=180,  # Override global
    ),
)
```

## Reset Configuration

For testing, reset to defaults:

```python
from stkai import STKAI

# Reset to defaults + env vars
STKAI.reset()
```

## Logging

The SDK uses Python's standard `logging` module. By default, logs are not displayed unless you configure a handler.

### Enable Logging

```python
import logging

# Enable all logs (DEBUG and above)
logging.basicConfig(level=logging.DEBUG)

# Or enable only INFO and above
logging.basicConfig(level=logging.INFO)
```

### Log Levels Used

| Level | What's Logged |
|-------|---------------|
| `DEBUG` | HTTP client detection, internal decisions |
| `INFO` | Request start/end, polling status, execution results |
| `WARNING` | Retries, rate limiting, transient errors |
| `ERROR` | Failed requests, timeouts, exceptions |

### Filter Only SDK Logs

To see only `stkai` logs (excluding other libraries):

```python
import logging

# Create handler with formatting
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s"
))

# Configure only stkai logger
stkai_logger = logging.getLogger("stkai")
stkai_logger.setLevel(logging.DEBUG)
stkai_logger.addHandler(handler)
```

The SDK uses namespaced loggers (`stkai._http`, `stkai.rqc._remote_quick_command`, etc.), which all propagate to the `stkai` parent logger by default.

### Disable Logging

To suppress all SDK logs:

```python
import logging

# Option 1: Set level to suppress
logging.getLogger().setLevel(logging.CRITICAL)

# Option 2: Add a NullHandler (library best practice)
logging.getLogger().addHandler(logging.NullHandler())
```

### Example Output

With `INFO` level enabled:

```
a1b2c3d4-e5f6-7890-abcd | RQC | 🛜 Starting execution of a single request.
a1b2c3d4-e5f6-7890-abcd | RQC |    └ slug_name='my-quick-command'
a1b2c3d4-e5f6-7890-abcd | RQC | Sending request to create execution (attempt 1/4)...
a1b2c3d4-e5f6-7890-abcd | RQC | ✅ Execution created successfully.
exec-123456             | RQC | Starting polling loop...
exec-123456             | RQC | Current status: EXECUTING
exec-123456             | RQC | ✅ Execution finished with status: COMPLETED
```

With `DEBUG` level enabled (shows HTTP client detection):

```
EnvironmentAwareHttpClient: StackSpot CLI (oscli) detected. Using StkCLIHttpClient.
a1b2c3d4-e5f6-7890-abcd | RQC | Starting execution of a single request.
...
```

## Next Steps

- [HTTP Client](http-client.md) - Custom HTTP client configuration
- [Getting Started](getting-started.md) - Quick setup guide
- [API Reference](api/config.md) - Complete configuration API
