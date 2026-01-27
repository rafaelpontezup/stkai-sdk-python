# HTTP Client

The SDK uses a unified `HttpClient` abstraction for all HTTP communication. This allows you to customize authentication, rate limiting, and testing.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Your Application                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   RemoteQuickCommand ─────┐                                         │
│                           ├──► HttpClient ──► StackSpot AI API     │
│   Agent ──────────────────┘                                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Built-in Implementations

### EnvironmentAwareHttpClient (Default)

Automatically detects the runtime environment and uses the appropriate client:

1. **CLI available** → Uses `StkCLIHttpClient`
2. **Credentials configured** → Uses `StandaloneHttpClient`
3. **Neither** → Raises `ValueError` with clear instructions

```python
from stkai import RemoteQuickCommand

# Works automatically in any environment
rqc = RemoteQuickCommand(slug_name="my-command")
```

The detection happens lazily on the first request, allowing you to call `STKAI.configure()` after import.

!!! tip "Zero Configuration"
    With `EnvironmentAwareHttpClient`, you don't need to worry about which client to use:

    - **Development**: Install CLI and run `stk login`
    - **Production/CI**: Set `STKAI_AUTH_CLIENT_ID` and `STKAI_AUTH_CLIENT_SECRET`

### StkCLIHttpClient

Explicitly delegates authentication to the StackSpot CLI (`oscli`):

```python
from stkai import RemoteQuickCommand, StkCLIHttpClient

# Explicit CLI usage
rqc = RemoteQuickCommand(
    slug_name="my-command",
    http_client=StkCLIHttpClient(),
)
```

!!! note "Requirements"
    StackSpot CLI must be installed and authenticated:
    ```bash
    stk login
    ```

### StandaloneHttpClient

Explicitly uses client credentials for environments without StackSpot CLI:

```python
from stkai import (
    RemoteQuickCommand,
    StandaloneHttpClient,
    ClientCredentialsAuthProvider,
)

# Create auth provider
auth_provider = ClientCredentialsAuthProvider(
    client_id="your-client-id",
    client_secret="your-client-secret",
)

# Create HTTP client
http_client = StandaloneHttpClient(auth_provider=auth_provider)

# Use with RQC
rqc = RemoteQuickCommand(
    slug_name="my-command",
    http_client=http_client,
)
```

Or use the global configuration:

```python
from stkai import STKAI, create_standalone_auth, StandaloneHttpClient

# Configure credentials globally
STKAI.configure(
    auth={
        "client_id": "your-client-id",
        "client_secret": "your-client-secret",
    }
)

# Create client using global config
auth_provider = create_standalone_auth()
http_client = StandaloneHttpClient(auth_provider=auth_provider)
```

### TokenBucketRateLimitedHttpClient

Wraps another client with Token Bucket rate limiting:

```python
from stkai import TokenBucketRateLimitedHttpClient, EnvironmentAwareHttpClient

http_client = TokenBucketRateLimitedHttpClient(
    delegate=EnvironmentAwareHttpClient(),
    max_requests=30,      # Requests per window
    time_window=60.0,     # Window in seconds
)
```

### AdaptiveRateLimitedHttpClient

Adds adaptive rate control with AIMD algorithm:

```python
from stkai import AdaptiveRateLimitedHttpClient, EnvironmentAwareHttpClient

http_client = AdaptiveRateLimitedHttpClient(
    delegate=EnvironmentAwareHttpClient(),
    max_requests=100,
    time_window=60.0,
    min_rate_floor=0.1,      # Never below 10%
    penalty_factor=0.2,      # Reduce by 20% on 429
    recovery_factor=0.05,    # Increase by 5% on success
)
```

!!! note "429 Handling"
    When the server returns HTTP 429, `AdaptiveRateLimitedHttpClient` applies the AIMD penalty (reduces rate) and raises `ServerSideRateLimitError`. The actual retry logic is handled by the `Retrying` class, which respects the `Retry-After` header.

## Rate Limiting

The SDK supports automatic rate limiting that applies to all HTTP requests (both RQC and Agents).

### Global Configuration (Recommended)

The easiest way to enable rate limiting is via `STKAI.configure()`. When enabled, `EnvironmentAwareHttpClient` automatically wraps requests with rate limiting:

```python
from stkai import STKAI, RemoteQuickCommand, Agent

# Enable rate limiting globally
STKAI.configure(
    rate_limit={
        "enabled": True,
        "strategy": "token_bucket",
        "max_requests": 30,
        "time_window": 60.0,
    }
)

# All clients now use rate limiting automatically
rqc = RemoteQuickCommand(slug_name="my-command")
agent = Agent(agent_id="my-agent")
```

### Using Presets (Recommended)

For most scenarios, use a preset instead of configuring each parameter manually:

```python
from dataclasses import asdict
from stkai import STKAI, RateLimitConfig

# Conservative: stability over throughput
# Best for: critical batch jobs, CI/CD, many concurrent processes
STKAI.configure(rate_limit=asdict(RateLimitConfig.conservative_preset(max_requests=20)))

# Balanced: sensible middle-ground (recommended default)
# Best for: general batch processing, 2-3 concurrent processes
STKAI.configure(rate_limit=asdict(RateLimitConfig.balanced_preset(max_requests=50)))

# Optimistic: throughput over stability
# Best for: interactive/CLI usage, single process, external retry logic
STKAI.configure(rate_limit=asdict(RateLimitConfig.optimistic_preset(max_requests=80)))
```

| Preset | `max_wait_time` | `min_rate_floor` | `penalty_factor` | `recovery_factor` |
|--------|-----------------|------------------|------------------|-------------------|
| `conservative_preset()` | 120s (patient) | 0.05 (5%) | 0.5 (aggressive) | 0.02 (slow) |
| `balanced_preset()` | 30s | 0.1 (10%) | 0.3 (moderate) | 0.05 (medium) |
| `optimistic_preset()` | 5s (fail-fast) | 0.3 (30%) | 0.15 (light) | 0.1 (fast) |

!!! tip "Calculating max_requests"
    Presets accept `max_requests` and `time_window` as parameters. Calculate based on:

    - **Your API quota** (e.g., 100 req/min)
    - **Expected concurrent processes** (e.g., ~3 processes)
    - **Allocation per process**: `quota / processes` (e.g., 100/3 ≈ 33 req/min)

### Available Strategies

| Strategy | Algorithm | Best For |
|----------|-----------|----------|
| `token_bucket` | Fixed Token Bucket | Known, stable rate limits |
| `adaptive` | AIMD + 429 handling | Shared quotas, unpredictable limits |

### Configuration via Code

```python
from stkai import STKAI

# Token Bucket (simple, predictable)
STKAI.configure(
    rate_limit={
        "enabled": True,
        "strategy": "token_bucket",
        "max_requests": 30,
        "time_window": 60.0,
        "max_wait_time": 60.0,  # Timeout after 60s waiting
    }
)

# Adaptive (dynamic, handles 429)
STKAI.configure(
    rate_limit={
        "enabled": True,
        "strategy": "adaptive",
        "max_requests": 100,
        "time_window": 60.0,
        "min_rate_floor": 0.1,       # Never below 10%
        "penalty_factor": 0.2,       # Reduce by 20% on 429
        "recovery_factor": 0.05,     # Increase by 5% on success
    }
)

# Unlimited wait time (wait indefinitely for token)
STKAI.configure(rate_limit={"max_wait_time": None})  # or "unlimited"
```

### Configuration via Environment Variables

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

### RateLimitConfig Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `False` | Enable rate limiting |
| `strategy` | `"token_bucket"` \| `"adaptive"` | `"token_bucket"` | Rate limiting algorithm |
| `max_requests` | `int` | `100` | Max requests per time window |
| `time_window` | `float` | `60.0` | Time window in seconds |
| `max_wait_time` | `float \| None` | `30.0` | Max wait for token (None = unlimited) |
| `min_rate_floor` | `float` | `0.1` | (adaptive) Min rate as fraction of max |
| `penalty_factor` | `float` | `0.3` | (adaptive) Rate reduction on 429 |
| `recovery_factor` | `float` | `0.05` | (adaptive) Rate increase on success |

### Manual Configuration

For more control, you can manually create rate-limited clients:

```python
from stkai import TokenBucketRateLimitedHttpClient, EnvironmentAwareHttpClient, RemoteQuickCommand

# Create rate-limited client manually
http_client = TokenBucketRateLimitedHttpClient(
    delegate=EnvironmentAwareHttpClient(),
    max_requests=30,
    time_window=60.0,
)

# Use with specific client
rqc = RemoteQuickCommand(
    slug_name="my-command",
    http_client=http_client,
)
```

### How Token Bucket Works

The `token_bucket` strategy uses a simple Token Bucket algorithm:

```
┌──────────────────────────────────────────────────────────────────┐
│                      Token Bucket Algorithm                       │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   Bucket: [●●●●●○○○○○]  (5 tokens available, 5 used)             │
│                                                                   │
│   • Tokens refill over time at: max_requests / time_window       │
│   • Each POST request consumes 1 token                           │
│   • When empty, requests wait until tokens available             │
│   • If waiting exceeds max_wait_time → TokenAcquisitionTimeoutError     │
│   • GET requests (polling) pass through without consuming tokens │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### How Adaptive (AIMD) Works

The `adaptive` strategy uses **Additive Increase, Multiplicative Decrease** (AIMD):

```
┌──────────────────────────────────────────────────────────────────┐
│                         AIMD Algorithm                            │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   On SUCCESS:                                                     │
│     effective_rate += max_requests × recovery_factor              │
│     (gradual increase)                                            │
│                                                                   │
│   On HTTP 429:                                                    │
│     effective_rate *= (1 - penalty_factor)                        │
│     (aggressive decrease)                                         │
│     raise ServerSideRateLimitError → Retrying handles retry       │
│                                                                   │
│   Constraints:                                                    │
│     • Floor: effective_rate ≥ max_requests × min_rate_floor      │
│     • Ceiling: effective_rate ≤ max_requests                     │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

**429 Handling:** When the server returns HTTP 429 (Too Many Requests), the `AdaptiveRateLimitedHttpClient`:

1. **Applies AIMD penalty** - Reduces effective rate by `penalty_factor`
2. **Raises `ServerSideRateLimitError`** - Contains the response for `Retry-After` parsing

The `Retrying` class then handles the retry:

1. **Parses `Retry-After` header** - If present and ≤ 60s, uses it as wait time
2. **Calculates wait time** - Uses max(Retry-After, exponential backoff)
3. **Adds jitter (0-30%)** - Prevents thundering herd
4. **Retries the request** - Up to `max_retries` times

!!! note "Protection against abusive Retry-After"
    The `Retrying` class ignores `Retry-After` values greater than 60 seconds to protect against buggy or malicious servers. In such cases, it falls back to exponential backoff.

### Exception Hierarchy

The SDK provides a clear exception hierarchy for rate limiting errors:

```
RetryableError (base - automatically retried)
├── ClientSideRateLimitError      # Base for client-side rate limit errors
│   └── TokenAcquisitionTimeoutError     # Timeout waiting for token (max_wait_time exceeded)
└── ServerSideRateLimitError      # HTTP 429 from server (contains response for Retry-After)
```

| Exception | Raised By | When |
|-----------|-----------|------|
| `TokenAcquisitionTimeoutError` | `TokenBucketRateLimitedHttpClient`, `AdaptiveRateLimitedHttpClient` | Token wait exceeds `max_wait_time` |
| `ServerSideRateLimitError` | `AdaptiveRateLimitedHttpClient` | Server returns HTTP 429 |
| `requests.HTTPError` | Direct from `requests` | HTTP 429 without Adaptive strategy |

All exceptions inherit from `RetryableError`, which the `Retrying` class automatically retries with exponential backoff.

### Timeout Handling

Both strategies raise `TokenAcquisitionTimeoutError` when a thread waits too long for a token:

```python
from stkai import TokenBucketRateLimitedHttpClient, TokenAcquisitionTimeoutError, StkCLIHttpClient

http_client = TokenBucketRateLimitedHttpClient(
    delegate=StkCLIHttpClient(),
    max_requests=10,
    time_window=60.0,
    max_wait_time=30.0,  # Give up after 30 seconds
)

try:
    response = http_client.post(url, data=payload)
except TokenAcquisitionTimeoutError as e:
    print(f"Timeout after {e.waited:.1f}s (max: {e.max_wait_time}s)")
    # Handle timeout: retry later, skip request, or fail gracefully
```

| Value | Behavior |
|-------|----------|
| `60.0` (default) | Wait up to 60 seconds for a token |
| `None` or `"unlimited"` | Wait indefinitely (no timeout) |
| `0.1` | Fail-fast mode (almost immediate timeout) |

!!! tip "Choosing max_wait_time"
    A good rule of thumb is to set `max_wait_time` equal to `time_window`. This ensures at least one full rate limit cycle can complete before timing out.

### When to Use Which Strategy

| Scenario | Recommended Strategy |
|----------|---------------------|
| Single client, known API limit | `token_bucket` |
| Multiple clients sharing quota | `adaptive` |
| API returns 429 frequently | `adaptive` |
| Predictable, stable workload | `token_bucket` |
| CI/CD with variable load | `adaptive` |

### Thread Safety

Both rate-limiting strategies are **thread-safe** and work correctly with:

- `execute_many()` concurrent workers
- Multi-threaded applications
- Shared client instances

```python
from stkai import STKAI, RemoteQuickCommand

STKAI.configure(
    rate_limit={"enabled": True, "max_requests": 30}
)

rqc = RemoteQuickCommand(
    slug_name="my-command",
    max_workers=16,  # 16 concurrent workers, still rate-limited
)
```

## Custom HTTP Client

Implement the `HttpClient` interface for custom behavior:

```python
from typing import Any
import requests
from stkai import HttpClient

class MyCustomHttpClient(HttpClient):
    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        # Custom GET logic
        return requests.get(url, headers=headers, timeout=timeout)

    def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        # Custom POST logic
        return requests.post(url, json=data, headers=headers, timeout=timeout)

# Use custom client
rqc = RemoteQuickCommand(
    slug_name="my-command",
    http_client=MyCustomHttpClient(),
)
```

## Decorator Pattern

Rate limiting clients use the decorator pattern - they wrap another client:

```python
from stkai import (
    AdaptiveRateLimitedHttpClient,
    TokenBucketRateLimitedHttpClient,
    StandaloneHttpClient,
    ClientCredentialsAuthProvider,
)

# Build a decorated chain
auth_provider = ClientCredentialsAuthProvider(
    client_id="id",
    client_secret="secret",
)

# Base client with authentication
base_client = StandaloneHttpClient(auth_provider=auth_provider)

# Add fixed rate limiting
rate_limited = TokenBucketRateLimitedHttpClient(
    delegate=base_client,
    max_requests=50,
    time_window=60.0,
)

# Add adaptive rate limiting on top
adaptive_client = AdaptiveRateLimitedHttpClient(
    delegate=rate_limited,  # Wrap the rate-limited client
    max_requests=100,
    time_window=60.0,
)
```

## Testing with Mock Client

Create a mock client for testing:

```python
from unittest.mock import Mock, MagicMock
import requests
from stkai import HttpClient, RemoteQuickCommand

# Create mock
mock_client = Mock(spec=HttpClient)

# Configure POST response
mock_response = MagicMock(spec=requests.Response)
mock_response.status_code = 200
mock_response.json.return_value = {"execution_id": "exec-123"}
mock_response.raise_for_status.return_value = None
mock_client.post.return_value = mock_response

# Configure GET response
get_response = MagicMock(spec=requests.Response)
get_response.status_code = 200
get_response.json.return_value = {
    "progress": {"status": "COMPLETED"},
    "result": {"data": "test"},
}
get_response.raise_for_status.return_value = None
mock_client.get.return_value = get_response

# Use in tests
rqc = RemoteQuickCommand(
    slug_name="test-command",
    http_client=mock_client,
)
```

## Thread Safety

All built-in HTTP clients are thread-safe:

- `EnvironmentAwareHttpClient` - Delegates to thread-safe clients
- `StkCLIHttpClient` - Stateless, safe
- `StandaloneHttpClient` - Auth provider handles token caching
- `TokenBucketRateLimitedHttpClient` - Uses `threading.Lock()`
- `AdaptiveRateLimitedHttpClient` - Uses `threading.Lock()`

Safe to share across threads and with `execute_many()`:

```python
# Thread-safe: shared client with concurrent workers
http_client = TokenBucketRateLimitedHttpClient(...)

rqc = RemoteQuickCommand(
    slug_name="my-command",
    http_client=http_client,
    max_workers=16,  # 16 concurrent threads
)

responses = rqc.execute_many(requests)
```

## Next Steps

- [RQC Rate Limiting](rqc/rate-limiting.md) - Detailed rate limiting examples for RQC
- [Configuration](configuration.md) - Global SDK configuration
- [Getting Started](getting-started.md) - Quick setup guide
