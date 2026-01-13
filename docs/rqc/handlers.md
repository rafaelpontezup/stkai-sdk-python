# Result Handlers

Result handlers allow you to customize how RQC responses are processed.

By default, the `RemoteQuickCommand.execute()` method uses the `JsonResultHandler` to deserialize the RQC response result (what the LLM answered to you) for each **successful request**, which means the `RqcResponse.result` attribute will be a Python object, such as `dict` or `list`.

However, you can provide a custom result handler to make any transformation, logging, or custom logic you wish.

## Built-in Handlers

### JsonResultHandler (Default)

Parses JSON responses, handling markdown code blocks automatically:

```python
from stkai import RemoteQuickCommand, RqcRequest

rqc = RemoteQuickCommand(slug_name="my-command")
response = rqc.execute(RqcRequest(payload=data))

# response.result is already parsed as dict/list
print(type(response.result))  # <class 'dict'>
```

### RawResultHandler

Returns the raw response without parsing:

```python
from stkai import RemoteQuickCommand, RqcRequest
from stkai.rqc import RAW_RESULT_HANDLER

response = rqc.execute(
    RqcRequest(payload=data),
    result_handler=RAW_RESULT_HANDLER,
)

# response.result is the raw string
print(type(response.result))  # <class 'str'>
```

## Custom Result Handlers

Create custom handlers by implementing `RqcResultHandler`:

```python
from typing import Any
from stkai.rqc import RqcResultHandler, RqcResultContext

class MyXMLResultHandler(RqcResultHandler):
    def handle_result(self, context: RqcResultContext) -> Any:
        raw_result = context.raw_result
        return XmlParser.parse(raw_result)

# Use the custom handler
response = rqc.execute(
    RqcRequest(payload=data),
    result_handler=MyXMLResultHandler(),
)
```

### RqcResultContext

The context object provides access to:

| Property | Type | Description |
|----------|------|-------------|
| `raw_result` | `str` | Raw result from the API |
| `raw_response` | `dict` | Full API response |
| `request` | `RqcRequest` | Original request |

## Chaining Handlers

Sometimes you just want to log, persist, validate, or enrich a response result; and sometimes you just want to reuse an existing and battle-tested result handler (such as `JsonResultHandler`). So, instead of creating a new result handler with too many responsibilities, you can **chain multiple ones**:

```python
from stkai.rqc import ChainedResultHandler, JsonResultHandler

# Create a pipeline
custom_handler = ChainedResultHandler.of([
    LogRawResultHandler(),           # Log the raw result
    SaveTokenUsageHandler(),         # Track token usage
    JsonResultHandler(),             # Parse JSON
    SaveResultToDiskHandler(),       # Persist result
])

response = rqc.execute(
    RqcRequest(payload=data),
    result_handler=custom_handler,
)
```

The `ChainedResultHandler` works like a pipeline: it executes one handler after another, passing the previous output as input to the next handler. The final handler's output becomes `response.result`.

### Convenience Method

For common patterns, use `chain_with`:

```python
from stkai.rqc import JsonResultHandler

# Parse JSON, then map to domain model
handler = JsonResultHandler.chain_with(
    DomainModelMapper()
)

response = rqc.execute(request, result_handler=handler)
```

## Example: Logging Handler

```python
import logging
from typing import Any
from stkai.rqc import RqcResultHandler, RqcResultContext

logger = logging.getLogger(__name__)

class LoggingResultHandler(RqcResultHandler):
    def handle_result(self, context: RqcResultContext) -> Any:
        logger.info(
            f"Request {context.request.id} completed. "
            f"Result length: {len(context.raw_result)} chars"
        )
        # Pass through unchanged
        return context.raw_result
```

## Example: Token Counter

```python
from typing import Any
from stkai.rqc import RqcResultHandler, RqcResultContext

class TokenCounterHandler(RqcResultHandler):
    def __init__(self):
        self.total_tokens = 0

    def handle_result(self, context: RqcResultContext) -> Any:
        tokens = context.raw_response.get("tokens", {})
        self.total_tokens += tokens.get("total", 0)
        return context.raw_result  # Pass through

# Usage
counter = TokenCounterHandler()
handler = ChainedResultHandler.of([counter, JsonResultHandler()])

for request in requests:
    rqc.execute(request, result_handler=handler)

print(f"Total tokens used: {counter.total_tokens}")
```

## Error Handling

If a handler raises an exception, the response status becomes `ERROR`:

```python
class FailingHandler(RqcResultHandler):
    def handle_result(self, context: RqcResultContext) -> Any:
        raise ValueError("Processing failed")

response = rqc.execute(request, result_handler=FailingHandler())
assert response.is_error()
assert "Processing failed" in response.error
```

## Next Steps

- [Event Listeners](listeners.md) - Monitor execution lifecycle
- [Rate Limiting](rate-limiting.md) - Handle API rate limits
- [API Reference](../api/rqc.md) - Complete API documentation
