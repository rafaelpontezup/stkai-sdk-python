# Configuration

The SDK provides a flexible configuration system with sensible defaults that can be customized via code or environment variables.

## Configuration Hierarchy

Settings are resolved in this order (highest precedence first):

1. **Options passed to client constructors** (e.g., `RqcOptions`, `AgentOptions`)
2. **Values set via `STKAI.configure()`**
3. **StackSpot CLI values** (`oscli`) - if CLI is available
4. **Environment variables** (`STKAI_*`)
5. **Hardcoded defaults**

!!! info "CLI Mode"
    When running with StackSpot CLI (`stk`), the SDK automatically detects CLI mode and uses CLI-provided configuration values. Both RQC and Agent `base_url` are automatically obtained from the CLI. This ensures the SDK uses the correct endpoints for your environment.

    **Important:** For CLI mode to work, your code must be executed through StackSpot CLI commands after authentication (e.g., `stk run action` or `stk run workflow`). See [CLI Detection](#cli-detection) for details.

!!! note "Single Source of Truth"
    Options with `None` values automatically use defaults from `STKAI.config`. This follows the "Single Source of Truth" principle - all defaults come from the global config.

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
        "retry_max_retries": 5,
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
export STKAI_RQC_RETRY_MAX_RETRIES=5

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

## CLI Detection

The SDK automatically detects when running with [StackSpot CLI](https://docs.stackspot.com/en/home/stk-cli/install) (`stk`) and uses CLI-provided configuration values.

### How CLI Mode Works

For CLI mode to be active, your code **must be executed through StackSpot CLI commands** after authentication. The CLI injects environment variables and context that the SDK uses for authentication and API endpoints.

**Common CLI execution methods:**

```bash
# Run a StackSpot Action that uses the SDK
stk run action my-action

# Run a StackSpot Workflow that uses the SDK
stk run workflow my-workflow
```

When your code runs through these commands, the SDK automatically:

1. Detects the CLI environment via injected variables
2. Uses CLI-managed authentication (no credentials needed in code)
3. Obtains the correct API endpoints for your environment

!!! warning "Direct Python Execution"
    Running your script directly with `python my_script.py` **will not** enable CLI mode, even if the CLI is installed and you're logged in. The script must be executed through `stk run action` or `stk run workflow` for CLI mode to work.

For more details on StackSpot CLI, see the [official CLI documentation](https://docs.stackspot.com/en/home/stk-cli/install).

### Checking CLI Availability

You can check CLI availability programmatically:

```python
from stkai._cli import StkCLI

if StkCLI.is_available():
    print("Running in CLI mode")

    # RQC base URL (from oscli.__codebuddy_base_url__)
    rqc_base_url = StkCLI.get_codebuddy_base_url()
    print(f"RQC base_url: {rqc_base_url}")

    # Agent base URL (derived from codebuddy URL)
    agent_base_url = StkCLI.get_inference_app_base_url()
    print(f"Agent base_url: {agent_base_url}")
else:
    print("Running in standalone mode")
```

!!! note "Automatic Detection"
    You don't need to manually check for CLI mode. The SDK handles this automatically:

    - **HTTP Client**: Uses `StkCLIHttpClient` when CLI is available
    - **Configuration**: Uses CLI values with higher precedence than env vars

!!! warning "Credentials Ignored in CLI Mode"
    If you have both StackSpot CLI installed **and** credentials configured (via environment variables or `STKAI.configure()`), the SDK will use CLI mode and **ignore the credentials**. A warning will be logged:

    ```
    ⚠️ Auth credentials detected (via env vars or configure) but running in CLI mode.
    Authentication will be handled by oscli. Credentials will be ignored.
    ```

    This is expected behavior - CLI takes precedence over standalone credentials.

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

## Debugging Configuration

Use `STKAI.explain()` to troubleshoot configuration issues. It prints the current configuration with the exact source of each value:

```python
from stkai import STKAI

STKAI.explain()

# Or use with logging
import logging
logging.basicConfig(level=logging.INFO)
STKAI.explain(output=logging.info)
```

Example output:

```
STKAI Configuration:
==========================================================================================
  Field                     │ Value                                              │ Source
----------------------------+----------------------------------------------------+--------
[sdk]
  version .................. 0.2.8                                                -
  cli_mode ................. True                                                 -
[auth]
  client_id ................ None                                                 default
  client_secret ............ supe********-key                                   ✎ env:STKAI_AUTH_CLIENT_SECRET
  token_url ................ https://idm.stackspot.com/stackspot-dev...           default
[rqc]
  request_timeout .......... 60                                                 ✎ user
  retry_max_retries ........ 5                                                  ✎ env:STKAI_RQC_RETRY_MAX_RETRIES
  retry_initial_delay ...... 0.5                                                  default
  poll_interval ............ 10.0                                                 default
  poll_max_duration ........ 600.0                                                default
  overload_timeout ......... 60.0                                                 default
  max_workers .............. 8                                                    default
  base_url ................. https://cli.example.com                            ✎ CLI
[agent]
  request_timeout .......... 60                                                   default
  base_url ................. https://genai-inference-app.stackspot.com          ✎ CLI
[rate_limit]
  enabled .................. False                                                default
  strategy ................. token_bucket                                         default
  ...
==========================================================================================
```

As you have noticed, the changed fields are rendered with an edit mark (✎). 

**Source values:**

- `-`: SDK metadata (read-only, not configurable)
- `default`: Using hardcoded default value
- `env:VAR_NAME`: Value from environment variable
- `CLI`: Value from StackSpot CLI (oscli)
- `user`: Value set via `STKAI.configure()`

The `✎` marker indicates values that were explicitly set (not using defaults).

!!! tip "Sensitive Values"
    The `client_secret` field is automatically masked in the output for security.

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
| `retry_max_retries` | `STKAI_RQC_RETRY_MAX_RETRIES` | 3 | Max retry attempts (0 = disabled) |
| `retry_initial_delay` | `STKAI_RQC_RETRY_INITIAL_DELAY` | 0.5 | Initial delay for first retry (seconds) |
| `poll_interval` | `STKAI_RQC_POLL_INTERVAL` | 10.0 | Seconds between polls |
| `poll_max_duration` | `STKAI_RQC_POLL_MAX_DURATION` | 600.0 | Max polling duration |
| `overload_timeout` | `STKAI_RQC_OVERLOAD_TIMEOUT` | 60.0 | Max CREATED state duration |
| `max_workers` | `STKAI_RQC_MAX_WORKERS` | 8 | Concurrent workers |
| `base_url` | `STKAI_RQC_BASE_URL` | StackSpot API URL | API base URL |

!!! tip "CLI Base URL"
    In CLI mode, the `base_url` is automatically obtained from `oscli.__codebuddy_base_url__`. Since CLI has higher precedence than environment variables, you can override it via `STKAI.configure()`, constructor parameter (`base_url=`), or by disabling CLI override with `allow_cli_override=False`.

### AgentConfig

Settings for `Agent` clients:

| Field | Env Var | Default | Description |
|-------|---------|---------|-------------|
| `request_timeout` | `STKAI_AGENT_REQUEST_TIMEOUT` | 60 | HTTP timeout (seconds) |
| `base_url` | `STKAI_AGENT_BASE_URL` | StackSpot API URL | API base URL |
| `retry_max_retries` | `STKAI_AGENT_RETRY_MAX_RETRIES` | 3 | Max retry attempts (0 = disabled) |
| `retry_initial_delay` | `STKAI_AGENT_RETRY_INITIAL_DELAY` | 0.5 | Initial delay for first retry (seconds) |

!!! tip "Retry Behavior"
    Retry is enabled by default. Use `retry_max_retries=3` for 4 total attempts (1 original + 3 retries). The delay doubles each retry: with `retry_initial_delay=0.5`, delays are 0.5s, 1s, 2s, 4s.

!!! tip "CLI Base URL"
    In CLI mode, the Agent `base_url` is automatically derived from the CLI's codebuddy URL (replacing `genai-code-buddy-api` with `genai-inference-app`). Since CLI has higher precedence than environment variables, you can override it via `STKAI.configure()`, constructor parameter (`base_url=`), or by disabling CLI override with `allow_cli_override=False`.

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
    allow_cli_override=False,      # Ignore CLI values in tests
)
```

### Disabling CLI Override

Use `allow_cli_override=False` to ignore CLI-provided configuration:

```python
from stkai import STKAI

# Use only env vars and defaults (ignore CLI)
STKAI.configure(allow_cli_override=False)

# Use only configure() values and defaults (ignore both CLI and env vars)
STKAI.configure(
    rqc={"base_url": "https://custom.api.com"},
    allow_env_override=False,
    allow_cli_override=False,
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

You can override global settings per-client using `RqcOptions` and `AgentOptions`. Fields set to `None` use defaults from `STKAI.config` (Single Source of Truth):

```python
from stkai import RemoteQuickCommand, RqcOptions, Agent
from stkai.rqc import CreateExecutionOptions, GetResultOptions
from stkai.agents import AgentOptions

# Override RQC settings (only what you need - rest from STKAI.config)
rqc = RemoteQuickCommand(
    slug_name="my-command",
    base_url="https://custom.api.com",  # Override API URL
    options=RqcOptions(
        create_execution=CreateExecutionOptions(
            retry_max_retries=10,      # Override global
        ),
        get_result=GetResultOptions(
            poll_interval=5.0,   # Override global
        ),
        max_workers=16,          # Override global
    ),
)

# Override Agent settings
agent = Agent(
    agent_id="my-agent",
    base_url="https://custom.api.com",  # Override API URL
    options=AgentOptions(
        request_timeout=180,  # Override global
    ),
)
```

### Partial Overrides

You only need to specify the settings you want to override:

```python
# Only override retry_max_retries - everything else from STKAI.config
rqc = RemoteQuickCommand(
    slug_name="my-command",
    options=RqcOptions(
        create_execution=CreateExecutionOptions(retry_max_retries=10),
    ),
)

# Only override request_timeout
agent = Agent(
    agent_id="my-agent",
    options=AgentOptions(request_timeout=180),
)
```

## Reset Configuration

For testing, reset to defaults:

```python
from stkai import STKAI

# Reset to defaults + env vars + CLI values
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
