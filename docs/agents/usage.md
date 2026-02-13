# Agent Usage Guide

This guide covers the main usage patterns for AI Agents.

## Basic Chat

Send a single message to an agent:

```python
from stkai import Agent, ChatRequest, ChatResponse

# Create an Agent client
agent = Agent(agent_id="my-assistant")

# Send a message
response: ChatResponse = agent.chat(
    request=ChatRequest(user_prompt="Explain what SOLID principles are")
)

if response.is_success():
    print(f"Agent says: {response.result}")
else:
    print(response.error_with_details())
```

The `chat()` method is **synchronous** and blocks until the response is received.

## Batch Execution

You can send multiple chat requests concurrently and wait for all responses using the `chat_many()` method. This method is also **blocking**, so it waits for all responses to finish before resuming execution:

```python
from stkai import Agent, ChatRequest

agent = Agent(agent_id="code-assistant")

prompts = [
    "What is dependency injection?",
    "Explain the Strategy pattern",
    "What is CQRS?",
]

responses = agent.chat_many(
    request_list=[
        ChatRequest(user_prompt=prompt)
        for prompt in prompts
    ],
)

# Process results after all complete
for resp in responses:
    if resp.is_success():
        print(f"✅ {resp.result[:80]}...")
    else:
        print(f"❌ {resp.error}")
```

### Filtering Responses

After receiving all responses, you can filter by status:

```python
responses = agent.chat_many(request_list=requests)

# Filter by status
successful = [r for r in responses if r.is_success()]
errors = [r for r in responses if r.is_error()]
timeouts = [r for r in responses if r.is_timeout()]

# Process successful responses
for resp in successful:
    print(f"Result: {resp.result}")
```

### Batch with Result Handler

Pass a result handler to process all responses consistently:

```python
from stkai.agents import JSON_RESULT_HANDLER

responses = agent.chat_many(
    request_list=requests,
    result_handler=JSON_RESULT_HANDLER,
)

for resp in responses:
    if resp.is_success():
        data = resp.result  # Already parsed as dict
```

### Controlling Concurrency

By default, `chat_many()` uses 8 concurrent threads. You can customize this via `AgentOptions`:

```python
from stkai.agents import AgentOptions

# Use 4 concurrent threads
agent = Agent(
    agent_id="my-assistant",
    options=AgentOptions(max_workers=4),
)
```

Or globally via `STKAI.configure()`:

```python
from stkai import STKAI

STKAI.configure(agent={"max_workers": 16})
```

Or via environment variable:

```bash
STKAI_AGENT_MAX_WORKERS=16
```

## Automatic Retry

The Agent client automatically retries failed requests with exponential backoff. This handles transient failures like network errors and server overload.

### What Gets Retried

| Error Type | Retried? |
|------------|----------|
| HTTP 5xx (500, 502, 503, 504) | ✅ Yes |
| HTTP 408 (Request Timeout) | ✅ Yes |
| HTTP 429 (Rate Limited) | ✅ Yes |
| Network errors (Timeout, ConnectionError) | ✅ Yes |
| HTTP 4xx (except 408, 429) | ❌ No |

### Configuration

Retry is **enabled by default** with sensible defaults. You can customize it via `AgentOptions`:

```python
from stkai import Agent, ChatRequest
from stkai.agents import AgentOptions

agent = Agent(
    agent_id="my-assistant",
    options=AgentOptions(
        retry_max_retries=5,        # 6 total attempts (1 + 5 retries)
        retry_initial_delay=1.0,    # Delays: 1s, 2s, 4s, 8s, 16s
    ),
)

response = agent.chat(ChatRequest(user_prompt="Hello"))
```

### Disabling Retry

To disable retry (single attempt only):

```python
agent = Agent(
    agent_id="my-assistant",
    options=AgentOptions(retry_max_retries=0),  # No retries
)
```

### Global Configuration

Configure retry defaults globally via `STKAI.configure()`:

```python
from stkai import STKAI

STKAI.configure(
    agent={
        "retry_max_retries": 5,
        "retry_initial_delay": 1.0,
    }
)
```

Or via environment variables:

```bash
STKAI_AGENT_RETRY_MAX_RETRIES=5
STKAI_AGENT_RETRY_INITIAL_DELAY=1.0
```

!!! tip "Retry-After Header"
    When the server returns HTTP 429 with a `Retry-After` header, the SDK respects it (up to 60 seconds) to avoid overwhelming the server.

!!! info "result vs raw_result"
    - **`result`**: The processed response (by the result handler). Use this by default.
    - **`raw_result`**: The raw message from the API before any processing.

    By default (with `RawResultHandler`), both return the same value. When using `JsonResultHandler`, `result` contains the parsed dict while `raw_result` contains the original JSON string.

## Conversation Context

Maintain context across multiple messages using `conversation_id`:

```python
from stkai import Agent, ChatRequest

agent = Agent(agent_id="my-assistant")

# First message - start a new conversation
response1 = agent.chat(
    request=ChatRequest(
        user_prompt="What is Python?",
        use_conversation=True,  # Enable conversation context
    )
)

print(f"Agent: {response1.result}")
print(f"Conversation ID: {response1.conversation_id}")

# Second message - continue the conversation
response2 = agent.chat(
    request=ChatRequest(
        user_prompt="What are its main features?",  # Agent remembers context
        conversation_id=response1.conversation_id,  # Continue same conversation
        use_conversation=True,
    )
)

print(f"Agent: {response2.result}")
```

!!! tip "Conversation Best Practices"
    - Always set `use_conversation=True` when using `conversation_id`
    - Store the `conversation_id` from the first response
    - Pass it in subsequent requests to maintain context

### Multi-turn Conversation Example

```python
from stkai import Agent, ChatRequest

agent = Agent(agent_id="code-reviewer")
conversation_id = None

prompts = [
    "I'm building a REST API in Python. What framework should I use?",
    "I chose FastAPI. What are the best practices for structuring the project?",
    "How should I handle authentication?",
    "Can you show me an example of JWT authentication?",
]

for prompt in prompts:
    response = agent.chat(
        request=ChatRequest(
            user_prompt=prompt,
            conversation_id=conversation_id,
            use_conversation=True,
        )
    )

    if response.is_success():
        conversation_id = response.conversation_id  # Update for next turn
        print(f"You: {prompt}")
        print(f"Agent: {response.result}\n")
```

## Knowledge Sources

Agents can use StackSpot Knowledge Sources to enrich their responses:

```python
from stkai import Agent, ChatRequest

agent = Agent(agent_id="my-assistant")

# With knowledge sources (default)
response = agent.chat(
    request=ChatRequest(
        user_prompt="What is our company's coding standard?",
        use_knowledge_sources=True,   # Use KS (default)
        return_knowledge_sources=True, # Include which KS were used
    )
)

if response.is_success():
    print(f"Agent: {response.result}")

    if response.knowledge_sources:
        print(f"Knowledge sources used: {response.knowledge_sources}")
```

### Disabling Knowledge Sources

For general questions that don't need organizational context:

```python
response = agent.chat(
    request=ChatRequest(
        user_prompt="What is 2 + 2?",
        use_knowledge_sources=False,  # Don't use KS
    )
)
```

## Token Usage

Track token consumption for monitoring and cost management:

```python
from stkai import Agent, ChatRequest

agent = Agent(agent_id="my-assistant")
response = agent.chat(ChatRequest(user_prompt="Explain microservices"))

if response.is_success() and response.tokens:
    print(f"User tokens: {response.tokens.user}")
    print(f"Enrichment tokens: {response.tokens.enrichment}")
    print(f"Output tokens: {response.tokens.output}")
    print(f"Total tokens: {response.tokens.total}")
```

### Token Tracking Example

For longer sessions or batch processing, you can create a tracker to accumulate token usage across multiple requests:

```python
class TokenTracker:
    def __init__(self):
        self.total_user = 0
        self.total_enrichment = 0
        self.total_output = 0

    def track(self, response):
        if response.tokens:
            self.total_user += response.tokens.user
            self.total_enrichment += response.tokens.enrichment
            self.total_output += response.tokens.output

    @property
    def total(self):
        return self.total_user + self.total_enrichment + self.total_output

# Usage
tracker = TokenTracker()

for prompt in prompts:
    response = agent.chat(ChatRequest(user_prompt=prompt))
    tracker.track(response)

print(f"Session total: {tracker.total} tokens")
```

!!! tip "Alternative: Result Handlers"
    You can also implement token tracking using a [Result Handler](handlers.md). This approach is useful when you want to automatically track tokens for every request without manually calling `tracker.track()`.

## Configuration

Customize agent behavior with `AgentOptions`. Fields set to `None` use defaults from global config (`STKAI.config.agent`):

```python
from stkai import Agent, ChatRequest
from stkai.agents import AgentOptions

agent = Agent(
    agent_id="my-assistant",
    base_url="https://custom.api.com",  # Optional: override API URL
    options=AgentOptions(
        request_timeout=120,  # Custom timeout (default from config)
        max_workers=16,       # More concurrent workers for chat_many()
    ),
)

response = agent.chat(ChatRequest(user_prompt="Complex question..."))
```

### Custom HTTP Client

Inject a custom HTTP client for testing or rate limiting:

```python
from stkai import Agent, StkCLIHttpClient, TokenBucketRateLimitedHttpClient

# Rate-limited HTTP client
http_client = TokenBucketRateLimitedHttpClient(
    delegate=StkCLIHttpClient(),
    max_requests=60,
    time_window=60.0,
)

agent = Agent(
    agent_id="my-assistant",
    http_client=http_client,
)
```

## Error Handling

The SDK never throws exceptions for API errors. Check the response status:

```python
response = agent.chat(request)

if response.is_success():
    # Process successful response
    process_message(response.result)
else:
    # Handle error or timeout
    print(response.error_with_details())
```

For more granular error handling:

```python
response = agent.chat(request)

if response.is_success():
    process_message(response.result)

elif response.is_error():
    # Handle client-side error (HTTP, network, parsing)
    log_error(response.error)

elif response.is_timeout():
    # Handle timeout
    handle_timeout()
```

### Response Properties

| Property | Type | Description |
|----------|------|-------------|
| `raw_result` | `str \| None` | Agent's raw response message (from API) |
| `result` | `Any \| None` | Processed result (by handler) |
| `status` | `ChatStatus` | Response status |
| `tokens` | `ChatTokenUsage \| None` | Token usage info |
| `conversation_id` | `str \| None` | ID for continuing conversation |
| `knowledge_sources` | `list[str]` | KS IDs used (if requested) |
| `stop_reason` | `str \| None` | Why generation stopped |
| `error` | `str \| None` | Error message if failed |
| `raw_response` | `dict \| None` | Raw API response (source of truth) |

### Response Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `is_success()` | `bool` | True if status is SUCCESS |
| `is_error()` | `bool` | True if status is ERROR |
| `is_timeout()` | `bool` | True if status is TIMEOUT |
| `error_with_details()` | `dict` | Error details dict (empty if success) |

## Next Steps

- [Result Handlers](handlers.md) - Customize response processing
- [Configuration](../configuration.md) - Global SDK configuration
- [Rate Limiting](rate-limiting.md) - Rate limiting for Agents
- [API Reference](../api/agents.md) - Complete API documentation
