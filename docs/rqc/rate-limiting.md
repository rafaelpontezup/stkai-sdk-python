# Rate Limiting

When processing many requests with `execute_many()`, you may need to limit the request rate to avoid overwhelming the StackSpot AI API or hitting rate limits.

The SDK provides two HTTP client wrappers for rate limiting:

| Client | Strategy | Best For |
|--------|----------|----------|
| `RateLimitedHttpClient` | Fixed Token Bucket | Known, stable rate limits |
| `AdaptiveRateLimitedHttpClient` | Adaptive + 429 handling | Shared quotas, unpredictable limits |

Both clients include a **timeout mechanism** (`max_wait_time`) to prevent threads from blocking indefinitely when waiting for rate limit tokens.

## Fixed Rate Limiting

Use `RateLimitedHttpClient` when you know the exact rate limit and it's stable:

```python
from stkai import RemoteQuickCommand, RqcRequest
from stkai import RateLimitedHttpClient, StkCLIHttpClient

# Limit to 30 requests per minute, timeout after 60s waiting
http_client = RateLimitedHttpClient(
    delegate=StkCLIHttpClient(),
    max_requests=30,
    time_window=60.0,      # seconds
    max_wait_time=60.0,    # timeout in seconds (default)
)

rqc = RemoteQuickCommand(
    slug_name="my-quick-command",
    http_client=http_client,
)

# Requests are automatically throttled
responses = rqc.execute_many(
    request_list=[RqcRequest(payload=data) for data in large_dataset]
)
```

### How Token Bucket Works

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
│   • If waiting exceeds max_wait_time → RateLimitTimeoutError     │
│   • GET requests (polling) pass through without consuming tokens │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `delegate` | Required | The underlying HTTP client |
| `max_requests` | Required | Maximum requests per time window |
| `time_window` | Required | Time window in seconds |
| `max_wait_time` | 60.0 | Max seconds to wait for token (`None` = infinite) |

## Adaptive Rate Limiting

Use `AdaptiveRateLimitedHttpClient` when multiple clients share the same rate limit quota, or when the effective rate is unpredictable:

```python
from stkai import RemoteQuickCommand, RqcRequest
from stkai import AdaptiveRateLimitedHttpClient, StkCLIHttpClient

# Start with 100 req/min, adapt based on 429 responses
http_client = AdaptiveRateLimitedHttpClient(
    delegate=StkCLIHttpClient(),
    max_requests=100,
    time_window=60.0,
    min_rate_floor=0.1,       # Never go below 10% (10 req/min)
    max_retries_on_429=3,     # Retry up to 3 times on 429
    penalty_factor=0.2,       # Reduce rate by 20% after 429
    recovery_factor=0.01,     # Increase rate by 1% after success
    max_wait_time=60.0,       # Timeout after 60s waiting (default)
)

rqc = RemoteQuickCommand(
    slug_name="my-quick-command",
    http_client=http_client,
)

responses = rqc.execute_many(
    request_list=[RqcRequest(payload=data) for data in large_dataset]
)
```

### AIMD Algorithm

The adaptive client uses **Additive Increase, Multiplicative Decrease** (AIMD):

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
│                                                                   │
│   Constraints:                                                    │
│     • Floor: effective_rate ≥ max_requests × min_rate_floor      │
│     • Ceiling: effective_rate ≤ max_requests                     │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `delegate` | Required | The underlying HTTP client |
| `max_requests` | Required | Initial/maximum requests per window |
| `time_window` | Required | Time window in seconds |
| `min_rate_floor` | 0.1 | Minimum rate as fraction of max (10%) |
| `max_retries_on_429` | 3 | Retries before giving up on 429 |
| `penalty_factor` | 0.2 | Rate reduction on 429 (20%) |
| `recovery_factor` | 0.01 | Rate increase on success (1%) |
| `max_wait_time` | 60.0 | Max seconds to wait for token (`None` = infinite) |

### 429 Handling

When the server returns HTTP 429 (Too Many Requests):

1. **Check `Retry-After` header** - If present, wait the specified time
2. **Apply penalty** - Reduce effective rate by `penalty_factor`
3. **Retry the request** - Up to `max_retries_on_429` times
4. **Fail if exhausted** - Return error after max retries

## Timeout Handling

Both rate-limiting clients raise `RateLimitTimeoutError` when a thread waits too long for a token:

```python
from stkai import RateLimitedHttpClient, RateLimitTimeoutError, StkCLIHttpClient

http_client = RateLimitedHttpClient(
    delegate=StkCLIHttpClient(),
    max_requests=10,
    time_window=60.0,
    max_wait_time=30.0,  # Give up after 30 seconds
)

try:
    response = http_client.post(url, data=payload)
except RateLimitTimeoutError as e:
    print(f"Timeout after {e.waited:.1f}s (max: {e.max_wait_time}s)")
    # Handle timeout: retry later, skip request, or fail gracefully
```

### Timeout Configuration

| Value | Behavior |
|-------|----------|
| `60.0` (default) | Wait up to 60 seconds for a token |
| `None` | Wait indefinitely (no timeout) |
| `0.1` | Fail-fast mode (almost immediate timeout) |

!!! tip "Choosing max_wait_time"
    A good rule of thumb is to set `max_wait_time` equal to `time_window`. This ensures at least one full rate limit cycle can complete before timing out.

## When to Use Which

| Scenario | Recommended Client |
|----------|-------------------|
| Single client, known API limit | `RateLimitedHttpClient` |
| Multiple clients sharing quota | `AdaptiveRateLimitedHttpClient` |
| API returns 429 frequently | `AdaptiveRateLimitedHttpClient` |
| Predictable, stable workload | `RateLimitedHttpClient` |
| CI/CD with variable load | `AdaptiveRateLimitedHttpClient` |

## Rate Limiting for Agents

Rate limiting also works with the Agent client:

```python
from stkai import Agent, ChatRequest
from stkai import RateLimitedHttpClient, StkCLIHttpClient

http_client = RateLimitedHttpClient(
    delegate=StkCLIHttpClient(),
    max_requests=60,
    time_window=60.0,
)

agent = Agent(
    agent_id="my-agent",
    http_client=http_client,
)

# Requests are rate-limited
for prompt in prompts:
    response = agent.chat(ChatRequest(user_prompt=prompt))
```

## Thread Safety

Both rate-limiting clients are **thread-safe** and work correctly with:

- `execute_many()` concurrent workers
- Multi-threaded applications
- Shared client instances

```python
# Safe to share across threads
http_client = RateLimitedHttpClient(...)

rqc = RemoteQuickCommand(
    slug_name="my-command",
    http_client=http_client,
    max_workers=16,  # 16 concurrent workers, still rate-limited
)
```

## Next Steps

- [HTTP Client](../http-client.md) - Custom HTTP client configuration
- [Configuration](../configuration.md) - Global SDK configuration
- [API Reference](../api/rqc.md) - Complete API documentation
