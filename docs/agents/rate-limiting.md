# Rate Limiting

When making many requests to AI Agents, you may need to limit the request rate to avoid overwhelming the StackSpot AI API or hitting rate limits.

## Global Configuration (Recommended)

The easiest way to enable rate limiting is via `STKAI.configure()`:

```python
from stkai import STKAI, Agent, ChatRequest

# Enable rate limiting globally
STKAI.configure(
    rate_limit={
        "enabled": True,
        "strategy": "token_bucket",
        "max_requests": 60,
        "time_window": 60.0,
    }
)

# Rate limiting is automatically applied
agent = Agent(agent_id="my-assistant")
response = agent.chat(ChatRequest(user_prompt="Hello"))
```

Or via environment variables:

```bash
export STKAI_RATE_LIMIT_ENABLED=true
export STKAI_RATE_LIMIT_STRATEGY=token_bucket
export STKAI_RATE_LIMIT_MAX_REQUESTS=60
export STKAI_RATE_LIMIT_TIME_WINDOW=60.0
```

!!! tip "Full Configuration Reference"
    See [HTTP Client > Rate Limiting](../http-client.md#rate-limiting) for all configuration options, strategies comparison, algorithms explanation, and environment variables.

## Manual Configuration

For more control, you can manually create rate-limited HTTP clients:

```python
from stkai import Agent, ChatRequest
from stkai import RateLimitedHttpClient, StkCLIHttpClient

# Limit to 60 requests per minute
http_client = RateLimitedHttpClient(
    delegate=StkCLIHttpClient(),
    max_requests=60,
    time_window=60.0,
)

agent = Agent(
    agent_id="my-assistant",
    http_client=http_client,
)

response = agent.chat(ChatRequest(user_prompt="Hello"))
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

agent = Agent(
    agent_id="my-assistant",
    http_client=http_client,
)
```

## Next Steps

- [HTTP Client > Rate Limiting](../http-client.md#rate-limiting) - Detailed guide with algorithms, strategies, and configuration
- [Configuration](../configuration.md) - Global SDK configuration
- [API Reference](../api/agents.md) - Complete API documentation
