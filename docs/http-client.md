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

The detection happens lazily on the first request, allowing you to call `configure_stkai()` after import.

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
from stkai import configure_stkai, create_standalone_auth, StandaloneHttpClient

# Configure credentials globally
configure_stkai(
    auth={
        "client_id": "your-client-id",
        "client_secret": "your-client-secret",
    }
)

# Create client using global config
auth_provider = create_standalone_auth()
http_client = StandaloneHttpClient(auth_provider=auth_provider)
```

### RateLimitedHttpClient

Wraps another client with Token Bucket rate limiting:

```python
from stkai import RateLimitedHttpClient, EnvironmentAwareHttpClient

http_client = RateLimitedHttpClient(
    delegate=EnvironmentAwareHttpClient(),
    max_requests=30,      # Requests per window
    time_window=60.0,     # Window in seconds
)
```

See [Rate Limiting](rqc/rate-limiting.md) for details.

### AdaptiveRateLimitedHttpClient

Adds adaptive rate control with AIMD algorithm:

```python
from stkai import AdaptiveRateLimitedHttpClient, EnvironmentAwareHttpClient

http_client = AdaptiveRateLimitedHttpClient(
    delegate=EnvironmentAwareHttpClient(),
    max_requests=100,
    time_window=60.0,
    min_rate_floor=0.1,      # Never below 10%
    max_retries_on_429=3,    # Retry on 429
    penalty_factor=0.2,      # Reduce by 20% on 429
    recovery_factor=0.01,    # Increase by 1% on success
)
```

See [Adaptive Rate Limiting](rqc/rate-limiting.md#adaptive-rate-limiting) for details.

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
    RateLimitedHttpClient,
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
rate_limited = RateLimitedHttpClient(
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
- `RateLimitedHttpClient` - Uses `threading.Lock()`
- `AdaptiveRateLimitedHttpClient` - Uses `threading.Lock()`

Safe to share across threads and with `execute_many()`:

```python
# Thread-safe: shared client with concurrent workers
http_client = RateLimitedHttpClient(...)

rqc = RemoteQuickCommand(
    slug_name="my-command",
    http_client=http_client,
    max_workers=16,  # 16 concurrent threads
)

responses = rqc.execute_many(requests)
```

## Next Steps

- [Rate Limiting](rqc/rate-limiting.md) - Detailed rate limiting guide
- [Configuration](configuration.md) - Global SDK configuration
- [Getting Started](getting-started.md) - Quick setup guide
