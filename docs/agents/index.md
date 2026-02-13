# AI Agents

StackSpot AI Agents are interactive AI assistants that can chat with users, maintain conversation context, and leverage knowledge sources to provide enriched responses.

## Simple API

The Agent client provides a simple interface for chatting with AI agents:

```python
from stkai import Agent, ChatRequest

agent = Agent(agent_id="my-assistant")
response = agent.chat(ChatRequest(user_prompt="What is SOLID?"))

if response.is_success():
    print(response.result)
```

## Key Concepts

### ChatRequest

Represents a message to send to the agent:

```python
from stkai import ChatRequest

request = ChatRequest(
    user_prompt="Explain dependency injection",  # Required
    id="my-request-id",                          # Optional: auto-generated
    conversation_id="conv-123",                  # Optional: for multi-turn
    use_conversation=True,                       # Enable conversation context
    use_knowledge_sources=True,                  # Use StackSpot knowledge
    return_knowledge_sources=True,               # Include KS IDs in response
    metadata={"source": "cli"},                  # Custom metadata
)
```

### ChatResponse

Contains the agent's response:

```python
response = agent.chat(request)

if response.is_success():
    result = response.result             # Processed response (use this by default)
    raw = response.raw_result            # Raw message from API (if needed)
    tokens = response.tokens             # Token usage info
    conv_id = response.conversation_id   # For continuing conversation
    ks_ids = response.knowledge_sources  # Knowledge sources used
```

### Response Status

| Status | Description |
|--------|-------------|
| `SUCCESS` | Response received successfully |
| `ERROR` | Client-side error (HTTP, network, parsing) |
| `TIMEOUT` | Request timed out |

## Features

| Feature | Description |
|---------|-------------|
| **[Synchronous Chat](usage.md)** | Simple, blocking chat interface with automatic error handling |
| **[Batch Execution](usage.md#batch-execution)** | Process multiple chat requests concurrently with `chat_many()` |
| **[Automatic Retry](usage.md#automatic-retry)** | Automatic retry with exponential backoff for transient failures |
| **[Conversation Context](usage.md#conversation-context)** | Maintain context across multiple messages using conversation IDs |
| **[Knowledge Sources](usage.md#knowledge-sources)** | Enrich responses with your organization's knowledge bases |
| **[Token Tracking](usage.md#token-usage)** | Track token usage for monitoring and cost management |
| **[Result Handlers](handlers.md)** | Customize response processing (JSON parsing, transformations) |

## Quick Example

```python
from stkai import Agent, ChatRequest

# Create an Agent client
agent = Agent(agent_id="code-assistant")

# Send a message
response = agent.chat(
    request=ChatRequest(
        user_prompt="What are the SOLID principles?",
        use_knowledge_sources=True,
    )
)

if response.is_success():
    print(f"Agent: {response.result}")

    if response.tokens:
        print(f"Tokens used: {response.tokens.total}")
else:
    print(response.error_with_details())
```

## Next Steps

- [Usage Guide](usage.md) - Detailed usage examples
- [Result Handlers](handlers.md) - Customize response processing
- [Rate Limiting](rate-limiting.md) - Rate limiting for Agents
- [Configuration](../configuration.md) - Configure Agent options
- [API Reference](../api/agents.md) - Complete API documentation
