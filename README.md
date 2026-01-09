# stkai

Python SDK for StackSpot AI - Remote Quick Commands and more.

## Installation

```bash
pip install stkai
```

For development:

```bash
pip install stkai[dev]
```

## Requirements

- Python 3.12+
- StackSpot CLI (`oscli`) installed and authenticated

## Quick Start

```python
from stkai import RemoteQuickCommand, RqcRequest

# Create a client for your Quick Command
rqc = RemoteQuickCommand(slug_name="my-quick-command")

# Execute a request
response = rqc.execute(
    request=RqcRequest(payload={"code": "def hello(): pass"})
)

if response.is_completed():
    print(f"Result: {response.result}")
else:
    print(f"Error: {response.error}")
```

## Usage Guide

The `RemoteQuickCommand` (RQC) is a client abstraction that allows sending requests and handling their response results from LLM (StackSpot AI). Its idea is to simplify the developer's life as much as possible.

Here you can see what it's possible to do with it:

1. [Sending a single RQC request](#1-sending-a-single-rqc-request)
2. [Sending a single RQC request with a result handler](#2-sending-a-single-rqc-request-with-a-result-handler)
   - 2.1. [Chaining multiple result handlers](#21-chaining-multiple-result-handlers)
3. [Sending multiple RQC requests at once](#3-sending-multiple-rqc-requests-at-once)
4. [Filtering only completed responses](#4-filtering-only-completed-responses)
5. [Configuration](#configuration)
6. [Event Listeners](#event-listeners)
   - 6.1. [Custom Event Listener](#custom-event-listener)
7. [Rate Limiting](#rate-limiting)
   - 7.1. [Fixed Rate Limiting](#71-fixed-rate-limiting)
   - 7.2. [Adaptive Rate Limiting](#72-adaptive-rate-limiting)

### 1. Sending a single RQC request

Here is an example of using the `RemoteQuickCommand.execute()` method to send a request. It's a synchronous (blocking) call:

```python
from pathlib import Path
from stkai import RemoteQuickCommand, RqcRequest, RqcResponse

# Preparing the payload
file_path = Path("product_service.py")
code = {
    "file_name": file_path.name,
    "source_code": file_path.read_text(encoding="utf-8")
}

# Sending a RQC request
rqc = RemoteQuickCommand(slug_name="explain-code-to-me")
response: RqcResponse = rqc.execute(
    request=RqcRequest(payload=code, id=file_path.name),
)

print(f"Response result: {response.result}")
```

The `RemoteQuickCommand.execute()` method **always** returns an instance of `RqcResponse` regardless it succeeded or failed. If the request's `id` attribute is not informed, it generates an UUIDv4 by default.

### 2. Sending a single RQC request with a result handler

By default, the `RemoteQuickCommand.execute()` method uses the `JsonResultHandler` to deserialize the RQC response result (what the LLM answered to you) for each **successful request**, which means the `RqcResponse.result` attribute will be a Python object, such as `dict` or `list`. However, you can inform a custom result handler to make any transformation, logging or logic you wish, as you can see below:

```python
from stkai import RemoteQuickCommand, RqcRequest
from stkai.rqc import RqcResultHandler, RqcResultContext

# Instantiate your handler
result_handler = MyCustomXMLResultHandler()

rqc = RemoteQuickCommand(slug_name="identify-and-list-all-security-issues")
response = rqc.execute(
    request=RqcRequest(payload=code),
    result_handler=result_handler  # Pass your handler instance as argument
)

print(f"Response result as XML: {response.result}")
```

Here is an example of a custom result handler:

```python
from typing import Any
from stkai.rqc import RqcResultHandler, RqcResultContext

class MyCustomXMLResultHandler(RqcResultHandler):
    def handle_result(self, context: RqcResultContext) -> Any:
        raw_result = context.raw_result
        return XmlParser.parse(raw_result)
```

#### 2.1. Chaining multiple result handlers

Sometimes you just want to log, persist, validate or enrich a response result; and sometimes you just want to reuse an existing and battle-tested result handler (such as `JsonResultHandler`). So, instead of creating a new result handler with too many responsibilities, we can **chain multiple ones**:

```python
from stkai.rqc import ChainedResultHandler, JsonResultHandler

custom_handler = ChainedResultHandler.of([
    LogRawResultHandler(),           # Just logs the raw result from response
    SaveAiTokenUsageResultHandler(), # Counts and saves AI token usage
    JsonResultHandler(),             # Converts the JSON result to Python object
    SaveResultInDiskResultHandler(), # Persists the Python object in disk
])

response = rqc.execute(
    request=RqcRequest(payload=code),
    result_handler=custom_handler
)
```

The `ChainedResultHandler` works like a pipeline: it executes one handler after another, passing the previous output as input to the next handler.

Also, if you want just map the JSON result from LLM to a domain model, you can leverage the `chain_with` method from `JsonResultHandler`:

```python
from stkai.rqc import JsonResultHandler

domain_model_handler = JsonResultHandler.chain_with(
    RefactoredCodeResultHandler()  # Chain your domain model handler
)
```

### 3. Sending multiple RQC requests at once

You can also send multiple RQC requests concurrently and wait for all pending responses using the `RemoteQuickCommand.execute_many()` method. This method is also blocking, so it waits for all responses to finish before resuming the execution:

```python
from stkai import RemoteQuickCommand, RqcRequest

source_files = [
    {"file_name": "order.py", "source_code": "..."},
    {"file_name": "submit_order_controller.py", "source_code": "..."},
    {"file_name": "list_pending_orders_controller.py", "source_code": "..."},
    # ...
]

rqc = RemoteQuickCommand(slug_name="refactor-code-with-SOLID-principles")
all_responses = rqc.execute_many(
    request_list=[
        RqcRequest(payload=f, id=f["file_name"]) for f in source_files
    ],
    result_handler=result_handler  # Optional: custom handler
)

# This will be executed only after all RQC-responses are received
for seq, resp in enumerate(all_responses, start=1):
    print(f"{seq} | Response result: {resp.result}")
```

As you can see, it also supports a custom `RqcResultHandler` via `result_handler` parameter. By default, it uses the `JsonResultHandler`.

### 4. Filtering only completed responses

Typically, after receiving all responses, you will want to process only the successful ones. To do that, you can check the `RqcResponse.status` attribute or simply invoke one of its methods, such as `is_completed()`, `is_failure()`, `is_error()` etc:

```python
from stkai import RemoteQuickCommand, RqcRequest

rqc = RemoteQuickCommand(slug_name="refactor-code-with-SOLID-principles")
all_responses = rqc.execute_many(
    request_list=[
        RqcRequest(payload=f, id=f["file_name"]) for f in source_files
    ]
)

# Filter only successful responses
completed_responses = [r for r in all_responses if r.is_completed()]
for resp in completed_responses:
    print(f"Response result: {resp.result}")

# You can also filter by other statuses
failed = [r for r in all_responses if r.is_failure()]
errors = [r for r in all_responses if r.is_error()]
timeouts = [r for r in all_responses if r.is_timeout()]
```

## Configuration

`RemoteQuickCommand` accepts several configuration options organized into two option classes:

```python
from stkai import RemoteQuickCommand
from stkai.rqc import CreateExecutionOptions, GetResultOptions

rqc = RemoteQuickCommand(
    slug_name="my-quick-command",
    create_execution_options=CreateExecutionOptions(
        max_retries=3,          # Retries for failed create-execution calls (default: 3)
        backoff_factor=0.5,     # Exponential backoff factor (default: 0.5)
        request_timeout=30,     # HTTP request timeout in seconds (default: 30)
    ),
    get_result_options=GetResultOptions(
        poll_interval=10.0,     # Seconds between status checks (default: 10)
        poll_max_duration=600.0,# Max wait time in seconds (default: 600 = 10min)
        overload_timeout=60.0,  # Max seconds in CREATED status before timeout (default: 60)
        request_timeout=30,     # HTTP request timeout in seconds (default: 30)
    ),
    max_workers=8,              # Concurrent requests for execute_many (default: 8)
)
```

## Event Listeners

You can observe the RQC execution lifecycle by registering event listeners. Listeners are useful for logging, metrics collection, or custom processing:

```python
from pathlib import Path
from stkai import RemoteQuickCommand
from stkai.rqc import RqcEventListener, FileLoggingListener

# Use the built-in FileLoggingListener to persist request/response to JSON files
listener = FileLoggingListener(output_dir=Path("./output/rqc"))

rqc = RemoteQuickCommand(
    slug_name="my-quick-command",
    listeners=[listener]
)
```

By default, if no listeners are provided, a `FileLoggingListener` is automatically registered to save request/response logs to `output/rqc/{slug_name}/`.

### Custom Event Listener

You can create custom listeners by extending the `RqcEventListener` class:

```python
import time
from typing import Any
from stkai.rqc import RqcEventListener, RqcRequest, RqcResponse

class MetricsListener(RqcEventListener):
    def on_before_execute(self, request: RqcRequest, context: dict[str, Any]) -> None:
        context['start_time'] = time.time()

    def on_status_change(
        self,
        request: RqcRequest,
        old_status: str,
        new_status: str,
        context: dict[str, Any],
    ) -> None:
        print(f"Status changed: {old_status} -> {new_status}")

    def on_after_execute(
        self,
        request: RqcRequest,
        response: RqcResponse,
        context: dict[str, Any],
    ) -> None:
        duration = time.time() - context['start_time']
        print(f"Execution took {duration:.2f}s with status: {response.status}")

# Use your custom listener
rqc = RemoteQuickCommand(
    slug_name="my-quick-command",
    listeners=[MetricsListener()]
)
```

### 7. Rate Limiting

When processing many requests with `execute_many()`, you may need to limit the request rate to avoid overwhelming the StackSpot AI API or hitting rate limits. The SDK provides two HTTP client wrappers for this purpose:

| Client | Strategy | Best For |
|--------|----------|----------|
| `RateLimitedHttpClient` | Fixed Token Bucket | Known, stable rate limits |
| `AdaptiveRateLimitedHttpClient` | Adaptive + 429 handling | Shared quotas, unpredictable limits |

#### 7.1. Fixed Rate Limiting

Use `RateLimitedHttpClient` when you know the exact rate limit and it's stable. It uses the **Token Bucket algorithm** to enforce a maximum number of requests per time window:

```python
from stkai import RemoteQuickCommand, RqcRequest
from stkai.rqc import RateLimitedHttpClient, StkCLIRqcHttpClient

# Limit to 30 requests per minute
http_client = RateLimitedHttpClient(
    delegate=StkCLIRqcHttpClient(),
    max_requests=30,
    time_window=60.0,  # seconds
)

rqc = RemoteQuickCommand(
    slug_name="my-quick-command",
    http_client=http_client,
)

# Now execute_many() will automatically throttle requests
responses = rqc.execute_many(
    request_list=[RqcRequest(payload=data) for data in large_dataset]
)
```

**How it works:**
- Only POST requests (create-execution) are rate-limited
- GET requests (polling) pass through without limiting
- When the limit is reached, requests block until tokens are available
- Thread-safe: works correctly with `execute_many()` concurrency

#### 7.2. Adaptive Rate Limiting

Use `AdaptiveRateLimitedHttpClient` when multiple clients share the same rate limit quota, or when the effective rate is unpredictable. It extends fixed rate limiting with:

- **Automatic retry on HTTP 429** (Too Many Requests)
- **Respects `Retry-After` header** from server
- **AIMD algorithm** (Additive Increase, Multiplicative Decrease) to adapt rate based on server responses
- **Floor protection** to prevent deadlock

```python
from stkai import RemoteQuickCommand, RqcRequest
from stkai.rqc import AdaptiveRateLimitedHttpClient, StkCLIRqcHttpClient

# Start with 100 req/min, adapt based on 429 responses
http_client = AdaptiveRateLimitedHttpClient(
    delegate=StkCLIRqcHttpClient(),
    max_requests=100,
    time_window=60.0,
    min_rate_floor=0.1,       # Never go below 10% (10 req/min)
    max_retries_on_429=3,     # Retry up to 3 times on 429
    penalty_factor=0.2,       # Reduce rate by 20% after 429
    recovery_factor=0.01,     # Increase rate by 1% after success
)

rqc = RemoteQuickCommand(
    slug_name="my-quick-command",
    http_client=http_client,
)

responses = rqc.execute_many(
    request_list=[RqcRequest(payload=data) for data in large_dataset]
)
```

**How the AIMD algorithm works:**
- **On success:** `effective_rate += max_requests * recovery_factor` (additive increase)
- **On 429:** `effective_rate *= (1 - penalty_factor)` (multiplicative decrease)
- **Floor protection:** `effective_rate >= max_requests * min_rate_floor`
- **Ceiling:** `effective_rate <= max_requests`

**When to use which:**

| Scenario | Recommended Client |
|----------|-------------------|
| Single client, known API limit | `RateLimitedHttpClient` |
| Multiple clients sharing quota | `AdaptiveRateLimitedHttpClient` |
| API returns 429 frequently | `AdaptiveRateLimitedHttpClient` |
| Predictable, stable workload | `RateLimitedHttpClient` |

## Response Status

| Status | Description |
|--------|-------------|
| `COMPLETED` | Request executed successfully |
| `FAILURE` | Server-side execution failure |
| `ERROR` | Client-side error (network, parsing, etc.) |
| `TIMEOUT` | Polling exceeded max duration |

## Development

```bash
# Clone the repository
git clone https://github.com/rafaelpontezup/stkai-sdk.git
cd stkai-sdk

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check src tests

# Run type checker
mypy src
```

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.
