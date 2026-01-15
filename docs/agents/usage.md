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
    print(f"Agent says: {response.message}")
else:
    print(f"Error: {response.error}")
```

The `chat()` method is **synchronous** and blocks until the response is received.

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

print(f"Agent: {response1.message}")
print(f"Conversation ID: {response1.conversation_id}")

# Second message - continue the conversation
response2 = agent.chat(
    request=ChatRequest(
        user_prompt="What are its main features?",  # Agent remembers context
        conversation_id=response1.conversation_id,  # Continue same conversation
        use_conversation=True,
    )
)

print(f"Agent: {response2.message}")
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
        print(f"Agent: {response.message}\n")
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
    print(f"Agent: {response.message}")

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
    ),
)

response = agent.chat(ChatRequest(user_prompt="Complex question..."))
```

### Custom HTTP Client

Inject a custom HTTP client for testing or rate limiting:

```python
from stkai import Agent, StkCLIHttpClient, RateLimitedHttpClient

# Rate-limited HTTP client
http_client = RateLimitedHttpClient(
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
    process_message(response.message)

elif response.is_error():
    # Handle client-side error
    log_error(response.error)

elif response.is_timeout():
    # Handle timeout
    handle_timeout()
```

### Response Properties

| Property | Type | Description |
|----------|------|-------------|
| `message` | `str \| None` | Agent's response message |
| `status` | `ChatStatus` | Response status |
| `tokens` | `ChatTokenUsage \| None` | Token usage info |
| `conversation_id` | `str \| None` | ID for continuing conversation |
| `knowledge_sources` | `list[str]` | KS IDs used (if requested) |
| `stop_reason` | `str \| None` | Why generation stopped |
| `error` | `str \| None` | Error message if failed |
| `raw_response` | `dict \| None` | Raw API response |

## Next Steps

- [Configuration](../configuration.md) - Global SDK configuration
- [Rate Limiting](../rqc/rate-limiting.md) - Rate limiting for Agents
- [API Reference](../api/agents.md) - Complete API documentation
