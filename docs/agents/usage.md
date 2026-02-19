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

### What Are Multi-turn Conversations?

By default, each `agent.chat()` call is **isolated** — the agent has no memory of previous messages. A **multi-turn conversation** is a sequence of messages where the agent **remembers prior context**. Each message builds on previous ones, allowing natural follow-up questions like "What are its main features?" without repeating what "it" refers to.

The API manages this through a `conversation_id`: the first message creates a new conversation, and subsequent messages include that ID to continue it. The SDK provides two ways to handle this — automatic (`UseConversation`) and manual.

### UseConversation (Recommended)

`UseConversation` is a context manager that **automatically tracks and propagates** `conversation_id` across all `Agent.chat()` calls within the block. No need to manually extract IDs or set flags:

```python
from stkai import Agent, ChatRequest, UseConversation

agent = Agent(agent_id="my-assistant")

with UseConversation() as conv:
    r1 = agent.chat(ChatRequest(user_prompt="What is Python?"))
    # conv.conversation_id is auto-captured from r1's response

    r2 = agent.chat(ChatRequest(user_prompt="What are its main features?"))
    # Automatically uses conv.conversation_id — agent remembers r1

    r3 = agent.chat(ChatRequest(user_prompt="Show me an example"))
    # Still in the same conversation
```

You can also use it across **multiple agents** — they share the same conversation context:

```python
with UseConversation() as conv:
    agent_a.chat(ChatRequest(user_prompt="Analyze this code"))
    agent_b.chat(ChatRequest(user_prompt="Now review the analysis above"))
```

#### Pre-generated Conversation ID

Use `with_generated_id()` when you want the conversation ID available **before** the first request. This is especially important with `chat_many()`, where concurrent requests would otherwise race to capture the server-assigned ID:

```python
with UseConversation.with_generated_id() as conv:
    print(conv.conversation_id)  # ULID already available

    r1 = agent.chat(ChatRequest(user_prompt="Hello"))
    r2 = agent.chat(ChatRequest(user_prompt="Follow up"))
```

The generated ID uses [ULID](https://github.com/ulid/spec) format, which is the format expected by the StackSpot AI API.

!!! tip "chat_many() + UseConversation"
    When using `chat_many()` inside a `UseConversation` block **without** a pre-set `conversation_id`, concurrent requests will race to capture the server-assigned ID — likely starting independent conversations. The SDK logs a warning in this case. Use `with_generated_id()` to avoid this:

    ```python
    # ⚠️ Race condition: concurrent requests start independent conversations
    with UseConversation():
        agent.chat_many([ChatRequest(user_prompt="Q1"), ChatRequest(user_prompt="Q2")])

    # ✅ All requests share the same conversation
    with UseConversation.with_generated_id():
        agent.chat_many([ChatRequest(user_prompt="Q1"), ChatRequest(user_prompt="Q2")])
    ```

#### Resuming a Known Conversation

If you already have a `conversation_id` (e.g., from a database or previous session), pass it directly:

```python
with UseConversation(conversation_id="01HGW2N7...") as conv:
    r1 = agent.chat(ChatRequest(user_prompt="Continue where we left off"))
```

!!! note "ULID Validation"
    The StackSpot AI API expects `conversation_id` in ULID format. If you pass a non-ULID string, the SDK logs a warning — the API may ignore the ID or start a new conversation scope.

#### Explicit Enrichment with `enrich()`

If you prefer more control, use `conv.enrich()` to explicitly set conversation fields on a request **before** sending it. This returns a new `ChatRequest` with `use_conversation=True` and the current `conversation_id` applied:

```python
with UseConversation() as conv:
    req = ChatRequest(user_prompt="Hello")
    enriched_req = conv.enrich(req)
    # enriched_req.use_conversation == True
    # enriched_req.conversation_id == conv.conversation_id (if captured)

    response = agent.chat(enriched_req)
```

This is useful when you want the `ChatRequest` object to reflect the conversation state explicitly (e.g., for logging or debugging).

#### Precedence Rules

| Scenario | Behavior |
|----------|----------|
| `ChatRequest` has explicit `conversation_id` | Request's ID wins (overrides `UseConversation`) |
| `UseConversation` has captured a `conversation_id` | Auto-applied to requests without one |
| Neither has a `conversation_id` | First successful response auto-captures it |

### Manual Tracking

For simple cases or when you need full control, you can manage `conversation_id` manually:

```python
from stkai import Agent, ChatRequest

agent = Agent(agent_id="my-assistant")

# First message — start a new conversation
response1 = agent.chat(
    request=ChatRequest(
        user_prompt="What is Python?",
        use_conversation=True,
    )
)

# Second message — continue the conversation
response2 = agent.chat(
    request=ChatRequest(
        user_prompt="What are its main features?",
        conversation_id=response1.conversation_id,
        use_conversation=True,
    )
)
```

#### Multi-turn Loop Example

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
        conversation_id = response.conversation_id
        print(f"You: {prompt}")
        print(f"Agent: {response.result}\n")
```

!!! tip "Conversation Best Practices"
    - Prefer `UseConversation` for multi-turn flows — it handles ID tracking automatically
    - Use `with_generated_id()` when combining `UseConversation` with `chat_many()`
    - Use manual tracking only when you need explicit control over each request
    - Always set `use_conversation=True` when managing IDs manually

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
