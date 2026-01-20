# Result Handlers

Result handlers allow you to customize how Agent responses are processed.

By default, the `Agent.chat()` method uses the `RawResultHandler`, which means the `ChatResponse.result` attribute will contain the raw message from the Agent (same as `raw_result`).

However, you can provide a custom result handler to parse JSON, transform data, or apply any custom logic.

## Built-in Handlers

### RawResultHandler (Default)

Returns the raw response without any transformation:

```python
from stkai import Agent, ChatRequest

agent = Agent(agent_id="my-assistant")
response = agent.chat(ChatRequest(user_prompt="Hello!"))

# response.result is the raw message (same as raw_result)
print(response.result)      # "Hello! How can I help you?"
print(response.raw_result)  # "Hello! How can I help you?"
```

### JsonResultHandler

Parses JSON responses, handling markdown code blocks automatically:

```python
from stkai import Agent, ChatRequest
from stkai.agents import JSON_RESULT_HANDLER

agent = Agent(agent_id="my-assistant")
response = agent.chat(
    ChatRequest(user_prompt="Return a JSON with name and age"),
    result_handler=JSON_RESULT_HANDLER,
)

# response.result is parsed as dict/list
print(type(response.result))  # <class 'dict'>
print(response.result)        # {'name': 'John', 'age': 30}

# response.raw_result still contains the raw JSON string
print(response.raw_result)    # '{"name": "John", "age": 30}'
```

The `JsonResultHandler` automatically handles:

- Raw JSON strings: `{"key": "value"}`
- Markdown code blocks: ` ```json\n{"key": "value"}\n``` `
- Already-parsed dicts (returns a deep copy)

## Custom Result Handlers

Create custom handlers by implementing `ChatResultHandler`:

```python
from typing import Any
from stkai.agents import ChatResultHandler, ChatResultContext

class UpperCaseHandler(ChatResultHandler):
    def handle_result(self, context: ChatResultContext) -> Any:
        raw_result = context.raw_result
        if isinstance(raw_result, str):
            return raw_result.upper()
        return raw_result

# Use the custom handler
response = agent.chat(
    ChatRequest(user_prompt="Say hello"),
    result_handler=UpperCaseHandler(),
)
print(response.result)  # "HELLO!"
```

### ChatResultContext

The context object provides access to:

| Property | Type | Description |
|----------|------|-------------|
| `raw_result` | `Any` | Raw message from the API |
| `request` | `ChatRequest` | Original request |
| `request_id` | `str` | Shortcut for `request.id` |
| `handled` | `bool` | True if a previous handler processed this |

## Chaining Handlers

You can chain multiple handlers to create a processing pipeline:

```python
from stkai.agents import ChainedResultHandler, JsonResultHandler

# Create a pipeline
custom_handler = ChainedResultHandler.of([
    JsonResultHandler(),             # Parse JSON first
    ValidateSchemaHandler(),         # Validate structure
    MapToDomainModelHandler(),       # Convert to domain object
])

response = agent.chat(
    ChatRequest(user_prompt="Get user data as JSON"),
    result_handler=custom_handler,
)
```

The `ChainedResultHandler` executes handlers in sequence, passing each output as input to the next. The final handler's output becomes `response.result`.

### Convenience Method

For common patterns, use `chain_with`:

```python
from stkai.agents import JsonResultHandler

# Parse JSON, then map to domain model
handler = JsonResultHandler.chain_with(
    DomainModelMapper()
)

response = agent.chat(request, result_handler=handler)
```

## Example: Logging Handler

```python
import logging
from typing import Any
from stkai.agents import ChatResultHandler, ChatResultContext

logger = logging.getLogger(__name__)

class LoggingHandler(ChatResultHandler):
    def handle_result(self, context: ChatResultContext) -> Any:
        logger.info(
            f"Request {context.request_id} completed. "
            f"Result length: {len(str(context.raw_result))} chars"
        )
        # Pass through unchanged
        return context.raw_result
```

## Example: Markdown Stripper

```python
import re
from typing import Any
from stkai.agents import ChatResultHandler, ChatResultContext

class MarkdownStripperHandler(ChatResultHandler):
    """Removes markdown formatting from responses."""

    def handle_result(self, context: ChatResultContext) -> Any:
        result = context.raw_result
        if not isinstance(result, str):
            return result

        # Remove code blocks
        result = re.sub(r'```[\s\S]*?```', '', result)
        # Remove bold/italic
        result = re.sub(r'\*\*?(.*?)\*\*?', r'\1', result)
        # Remove headers
        result = re.sub(r'^#+\s*', '', result, flags=re.MULTILINE)

        return result.strip()
```

## Error Handling

If a handler raises an exception, it's wrapped in `ChatResultHandlerError`:

```python
from stkai.agents import ChatResultHandler, ChatResultContext
from stkai import ChatResultHandlerError

class FailingHandler(ChatResultHandler):
    def handle_result(self, context: ChatResultContext) -> Any:
        raise ValueError("Processing failed")

try:
    response = agent.chat(request, result_handler=FailingHandler())
except ChatResultHandlerError as e:
    print(f"Handler failed: {e}")
    print(f"Original error: {e.cause}")
```

## When to Use Each Handler

| Scenario | Handler |
|----------|---------|
| Plain text responses | `RawResultHandler` (default) |
| Structured JSON responses | `JSON_RESULT_HANDLER` |
| Custom transformations | Implement `ChatResultHandler` |
| Multiple processing steps | `ChainedResultHandler` |

## Next Steps

- [Usage Guide](usage.md) - Main usage patterns
- [Rate Limiting](rate-limiting.md) - Handle API rate limits
- [API Reference](../api/agents.md) - Complete API documentation
