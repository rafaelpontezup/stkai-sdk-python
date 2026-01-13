# RQC Usage Guide

The `RemoteQuickCommand` (RQC) is a client abstraction that allows sending requests and handling their response results from the LLM (StackSpot AI). Its idea is to simplify the developer's life as much as possible.

This guide covers the main usage patterns for Remote Quick Commands.

## Single Request Execution

The `execute()` method sends a single request and waits for the result. It's a **synchronous (blocking)** call:

```python
from pathlib import Path
from stkai import RemoteQuickCommand, RqcRequest, RqcResponse

# Prepare the payload
file_path = Path("product_service.py")
code = {
    "file_name": file_path.name,
    "source_code": file_path.read_text(encoding="utf-8")
}

# Send the request
rqc = RemoteQuickCommand(slug_name="explain-code-to-me")
response: RqcResponse = rqc.execute(
    request=RqcRequest(payload=code, id=file_path.name),
)

print(f"Response result: {response.result}")
```

The `execute()` method **always** returns an instance of `RqcResponse` regardless of whether it succeeded or failed.

!!! note
    If the request's `id` is not provided, a UUID is auto-generated.

## Batch Execution

You can send multiple RQC requests concurrently and wait for all pending responses using the `execute_many()` method. This method is also **blocking**, so it waits for all responses to finish before resuming the execution:

```python
from stkai import RemoteQuickCommand, RqcRequest

source_files = [
    {"file_name": "order.py", "source_code": "..."},
    {"file_name": "controller.py", "source_code": "..."},
    {"file_name": "service.py", "source_code": "..."},
]

rqc = RemoteQuickCommand(slug_name="refactor-code")
all_responses = rqc.execute_many(
    request_list=[
        RqcRequest(payload=f, id=f["file_name"])
        for f in source_files
    ],
    max_workers=8,  # Optional: concurrent workers (default: 8)
)

# Process results after all complete
for resp in all_responses:
    print(f"{resp.request.id}: {resp.status}")
```

## Filtering Responses

Typically, after receiving all responses, you will want to process only the successful ones. To do that, you can check the `RqcResponse.status` attribute or simply invoke one of its helper methods:

```python
all_responses = rqc.execute_many(request_list=requests)

# Filter by status
completed = [r for r in all_responses if r.is_completed()]
failed = [r for r in all_responses if r.is_failure()]
errors = [r for r in all_responses if r.is_error()]
timeouts = [r for r in all_responses if r.is_timeout()]

# Process successful responses
for resp in completed:
    print(f"Result: {resp.result}")

# Handle failures
for resp in failed:
    print(f"Failed: {resp.error_with_details()}")
```

## Configuration Options

Customize execution behavior with options:

```python
from stkai import RemoteQuickCommand
from stkai.rqc import CreateExecutionOptions, GetResultOptions

rqc = RemoteQuickCommand(
    slug_name="my-quick-command",
    create_execution_options=CreateExecutionOptions(
        max_retries=3,          # Retries for failed POST requests
        backoff_factor=0.5,     # Exponential backoff factor
        request_timeout=30,     # HTTP timeout in seconds
    ),
    get_result_options=GetResultOptions(
        poll_interval=10.0,     # Seconds between status checks
        poll_max_duration=600.0,# Max wait time (10 min)
        overload_timeout=60.0,  # Max time in CREATED status
        request_timeout=30,     # HTTP timeout for polling
    ),
    max_workers=8,              # Concurrent workers for execute_many
)
```

### Option Reference

#### CreateExecutionOptions

| Option | Default | Description |
|--------|---------|-------------|
| `max_retries` | 3 | Number of retries for failed create-execution calls |
| `backoff_factor` | 0.5 | Exponential backoff multiplier |
| `request_timeout` | 30 | HTTP request timeout in seconds |

#### GetResultOptions

| Option | Default | Description |
|--------|---------|-------------|
| `poll_interval` | 10.0 | Seconds between status checks |
| `poll_max_duration` | 600.0 | Maximum polling duration (10 min) |
| `overload_timeout` | 60.0 | Max seconds in CREATED status |
| `request_timeout` | 30 | HTTP timeout for GET requests |

## Error Handling

The SDK never throws exceptions for API errors. Instead, check the response status:

```python
response = rqc.execute(request)

if response.is_completed():
    # Success - process result
    process_result(response.result)

elif response.is_failure():
    # Server-side failure
    details = response.error_with_details()
    log_failure(details)

elif response.is_error():
    # Client-side error (network, parsing, handler error)
    handle_error(response.error)

elif response.is_timeout():
    # Polling timed out
    handle_timeout(response.request.id)
```

### Error Details

Get detailed error information:

```python
if not response.is_completed():
    details = response.error_with_details()
    # Returns:
    # {
    #     "status": "FAILURE",
    #     "error_message": "...",
    #     "response_body": {...}
    # }
```

## Accessing Raw Response

For debugging or custom processing:

```python
response = rqc.execute(request)

# Raw API response
raw = response.raw_response  # Full JSON response

# Raw result field only
raw_result = response.raw_result  # response["result"] field
```

## Next Steps

- [Result Handlers](handlers.md) - Customize result processing
- [Event Listeners](listeners.md) - Monitor execution lifecycle
- [Rate Limiting](rate-limiting.md) - Handle API rate limits
