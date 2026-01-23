# Rate Limiting

When processing many requests with `execute_many()`, you may need to limit the request rate to avoid overwhelming the StackSpot AI API or hitting rate limits.

## Global Configuration (Recommended)

The easiest way to enable rate limiting is via `STKAI.configure()`:

```python
from stkai import STKAI, RemoteQuickCommand, RqcRequest

# Enable rate limiting globally
STKAI.configure(
    rate_limit={
        "enabled": True,
        "strategy": "token_bucket",
        "max_requests": 30,
        "time_window": 60.0,
    }
)

# Rate limiting is automatically applied
rqc = RemoteQuickCommand(slug_name="my-quick-command")
responses = rqc.execute_many(
    request_list=[RqcRequest(payload=data) for data in large_dataset]
)
```

Or via environment variables:

```bash
export STKAI_RATE_LIMIT_ENABLED=true
export STKAI_RATE_LIMIT_STRATEGY=token_bucket
export STKAI_RATE_LIMIT_MAX_REQUESTS=30
export STKAI_RATE_LIMIT_TIME_WINDOW=60.0
```

!!! tip "Full Configuration Reference"
    See [HTTP Client > Rate Limiting](../http-client.md#rate-limiting) for all configuration options, strategies comparison, algorithms explanation, and environment variables.

## Manual Configuration

For more control, you can manually create rate-limited HTTP clients:

```python
from stkai import RemoteQuickCommand, RqcRequest
from stkai import TokenBucketRateLimitedHttpClient, StkCLIHttpClient

# Limit to 30 requests per minute
http_client = TokenBucketRateLimitedHttpClient(
    delegate=StkCLIHttpClient(),
    max_requests=30,
    time_window=60.0,
)

rqc = RemoteQuickCommand(
    slug_name="my-quick-command",
    http_client=http_client,
)

responses = rqc.execute_many(
    request_list=[RqcRequest(payload=data) for data in large_dataset]
)
```

For adaptive rate limiting (handles HTTP 429 automatically):

```python
from stkai import AdaptiveRateLimitedHttpClient, StkCLIHttpClient

http_client = AdaptiveRateLimitedHttpClient(
    delegate=StkCLIHttpClient(),
    max_requests=100,
    time_window=60.0,
    min_rate_floor=0.1,       # Never below 10%
    max_retries_on_429=3,     # Retry on 429
)

rqc = RemoteQuickCommand(
    slug_name="my-quick-command",
    http_client=http_client,
)
```

## Batch Processing with Rate Limiting

Rate limiting is especially useful with `execute_many()` for batch processing:

```python
from stkai import STKAI, RemoteQuickCommand, RqcRequest

# Configure rate limiting
STKAI.configure(
    rate_limit={
        "enabled": True,
        "strategy": "adaptive",
        "max_requests": 50,
    }
)

rqc = RemoteQuickCommand(
    slug_name="code-review",
    max_workers=16,  # 16 concurrent workers, still rate-limited
)

# Process large dataset
files = load_files_to_review()
responses = rqc.execute_many(
    request_list=[RqcRequest(payload={"code": f}) for f in files]
)

# Check results
completed = [r for r in responses if r.is_completed()]
failed = [r for r in responses if r.is_failure()]
```

## Next Steps

- [HTTP Client > Rate Limiting](../http-client.md#rate-limiting) - Detailed guide with algorithms, strategies, and configuration
- [Configuration](../configuration.md) - Global SDK configuration
- [API Reference](../api/rqc.md) - Complete API documentation
