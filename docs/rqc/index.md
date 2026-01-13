# Remote Quick Commands (RQC)

Remote Quick Commands (RQC) are AI-powered commands that run on StackSpot AI's infrastructure. They can analyze, transform, and generate code based on your inputs.

## Overview

The RQC system works in two phases:

1. **Create Execution**: Submit a request to the API, which returns an execution ID
2. **Poll for Result**: Periodically check the execution status until it completes

The SDK handles all of this automatically, providing a simple synchronous interface.

```python
from stkai import RemoteQuickCommand, RqcRequest

rqc = RemoteQuickCommand(slug_name="my-quick-command")
response = rqc.execute(RqcRequest(payload={"input": "data"}))
```

## Key Concepts

### RqcRequest

Represents a request to be executed:

```python
from stkai import RqcRequest

request = RqcRequest(
    payload={"code": "def foo(): pass"},  # Data to send to the Quick Command
    id="my-unique-id",                     # Optional: auto-generated UUID if not provided
    metadata={"source": "main.py"},        # Optional: custom metadata for tracking
)
```

### RqcResponse

Contains the execution result:

```python
response = rqc.execute(request)

# Check status
if response.is_completed():
    result = response.result        # Processed result (dict or list)
    raw = response.raw_response     # Raw API response
elif response.is_failure():
    error = response.error          # Error message
elif response.is_timeout():
    # Execution took too long
    pass
```

### Execution Status

| Status | Description |
|--------|-------------|
| `PENDING` | Request not yet submitted |
| `CREATED` | Server acknowledged the request |
| `RUNNING` | Execution is being processed |
| `COMPLETED` | Finished successfully |
| `FAILURE` | Server-side error |
| `ERROR` | Client-side error (network, parsing) |
| `TIMEOUT` | Exceeded `poll_max_duration` |

## Features

| Feature | Description |
|---------|-------------|
| **[Batch Execution](usage.md#batch-execution)** | Process multiple requests concurrently with `execute_many()` |
| **[Result Handlers](handlers.md)** | Customize how responses are processed with pluggable handlers |
| **[Event Listeners](listeners.md)** | Monitor execution lifecycle with custom event handlers |
| **[Rate Limiting](rate-limiting.md)** | Control request rate to avoid API throttling |

## Quick Example

```python
from stkai import RemoteQuickCommand, RqcRequest

# Create client
rqc = RemoteQuickCommand(slug_name="code-review")

# Execute single request
response = rqc.execute(
    request=RqcRequest(payload={"code": "print('hello')"})
)

if response.is_completed():
    print(response.result)
else:
    print(response.error_with_details())
```

## Next Steps

- [Usage Guide](usage.md) - Detailed usage examples
- [Result Handlers](handlers.md) - Customize result processing
- [Event Listeners](listeners.md) - Monitor execution lifecycle
- [Rate Limiting](rate-limiting.md) - Handle rate limits
- [API Reference](../api/rqc.md) - Complete API documentation
