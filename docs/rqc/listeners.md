# Event Listeners

Event listeners allow you to observe the RQC execution lifecycle for logging, metrics, or custom processing.

## Built-in Listeners

### FileLoggingListener

Automatically saves request/response to JSON files for debugging:

```python
from pathlib import Path
from stkai import RemoteQuickCommand
from stkai.rqc import FileLoggingListener

listener = FileLoggingListener(output_dir=Path("./output/rqc"))

rqc = RemoteQuickCommand(
    slug_name="my-command",
    listeners=[listener],
)
```

!!! note "Default Behavior"
    If no listeners are provided, a `FileLoggingListener` is automatically registered to save logs to `output/rqc/{slug_name}/`.

**Output files:**

```
output/rqc/my-command/
├── {execution_id}-request.json
└── {execution_id}-response-COMPLETED.json
```

## Custom Event Listeners

### RqcEventListener

Implement `RqcEventListener` for basic lifecycle hooks:

```python
import time
from typing import Any
from stkai.rqc import RqcEventListener, RqcRequest, RqcResponse

class MetricsListener(RqcEventListener):
    def on_before_execute(
        self,
        request: RqcRequest,
        context: dict[str, Any],
    ) -> None:
        context['start_time'] = time.time()
        print(f"Starting: {request.id}")

    def on_status_change(
        self,
        request: RqcRequest,
        old_status: str,
        new_status: str,
        context: dict[str, Any],
    ) -> None:
        print(f"Status: {old_status} -> {new_status}")

    def on_after_execute(
        self,
        request: RqcRequest,
        response: RqcResponse,
        context: dict[str, Any],
    ) -> None:
        duration = time.time() - context['start_time']
        print(f"Completed in {duration:.2f}s: {response.status}")

# Use the listener
rqc = RemoteQuickCommand(
    slug_name="my-command",
    listeners=[MetricsListener()],
)
```

### Lifecycle Hooks

| Hook | When Called |
|------|-------------|
| `on_before_execute()` | Before the request is submitted |
| `on_status_change()` | When execution status changes |
| `on_after_execute()` | After completion (success or failure) |

### Context Dictionary

The `context` dictionary is shared across all hooks for a single execution. Use it to store state:

```python
def on_before_execute(self, request, context):
    context['start_time'] = time.time()
    context['retries'] = 0

def on_status_change(self, request, old_status, new_status, context):
    context['retries'] += 1

def on_after_execute(self, request, response, context):
    duration = time.time() - context['start_time']
    retries = context['retries']
```

## Phased Event Listener

The base `RqcEventListener` provides general lifecycle hooks, but sometimes you need more granular control over the **two distinct phases** of RQC execution:

1. **Create-execution phase**: POST request to create the execution
2. **Get-result phase**: Polling until the result is ready

For these cases, use `RqcPhasedEventListener` which provides separate hooks for each phase:

```python
import time
from typing import Any
from requests import Response
from stkai import RemoteQuickCommand
from stkai.rqc import RqcPhasedEventListener, RqcRequest, RqcResponse

class DetailedMetricsListener(RqcPhasedEventListener):
    """Track metrics for each phase separately."""

    def on_create_execution_start(
        self,
        request: RqcRequest,
        context: dict[str, Any],
    ) -> None:
        context['create_start'] = time.time()
        print(f"[{request.id}] Starting create-execution...")

    def on_create_execution_end(
        self,
        request: RqcRequest,
        success: bool,
        response: Response | None,
        context: dict[str, Any],
    ) -> None:
        duration = time.time() - context['create_start']
        status = "OK" if success else "FAILED"
        print(f"[{request.id}] Create-execution {status} in {duration:.2f}s")

    def on_get_result_start(
        self,
        request: RqcRequest,
        context: dict[str, Any],
    ) -> None:
        context['poll_start'] = time.time()
        print(f"[{request.id}] Starting polling...")

    def on_get_result_end(
        self,
        request: RqcRequest,
        response: RqcResponse,
        context: dict[str, Any],
    ) -> None:
        duration = time.time() - context['poll_start']
        print(f"[{request.id}] Polling completed in {duration:.2f}s: {response.status}")

# Use the phased listener
rqc = RemoteQuickCommand(
    slug_name="my-command",
    listeners=[DetailedMetricsListener()],
)
```

### Phased Hooks

| Hook | When Called |
|------|-------------|
| `on_create_execution_start()` | Before POST to create execution |
| `on_create_execution_end()` | After POST completes (success or failure) |
| `on_get_result_start()` | Before polling begins |
| `on_get_result_end()` | After polling completes |

### Base vs Phased Listeners

| Scenario | Recommended |
|----------|-------------|
| Simple logging or metrics | `RqcEventListener` |
| Different handling per phase | `RqcPhasedEventListener` |
| Track create-execution failures | `RqcPhasedEventListener` |
| Measure polling duration | `RqcPhasedEventListener` |

## Multiple Listeners

Register multiple listeners - they all receive events:

```python
rqc = RemoteQuickCommand(
    slug_name="my-command",
    listeners=[
        FileLoggingListener(output_dir=Path("./logs")),
        MetricsListener(),
        AlertingListener(),
    ],
)
```

## Example: Prometheus Metrics

```python
from prometheus_client import Counter, Histogram
from stkai.rqc import RqcEventListener, RqcRequest, RqcResponse

rqc_requests = Counter('rqc_requests_total', 'Total RQC requests', ['slug', 'status'])
rqc_duration = Histogram('rqc_duration_seconds', 'RQC execution duration', ['slug'])

class PrometheusListener(RqcEventListener):
    def __init__(self, slug_name: str):
        self.slug_name = slug_name

    def on_before_execute(self, request, context):
        context['start'] = time.time()

    def on_after_execute(self, request, response, context):
        duration = time.time() - context['start']
        rqc_requests.labels(slug=self.slug_name, status=response.status.value).inc()
        rqc_duration.labels(slug=self.slug_name).observe(duration)
```

## Next Steps

- [Rate Limiting](rate-limiting.md) - Handle API rate limits
- [API Reference](../api/rqc.md) - Complete API documentation
