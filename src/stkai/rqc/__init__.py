"""
Remote Quick Commands (RQC) module for StackSpot AI.

This module provides a client abstraction for executing Remote Quick Commands
against the StackSpot AI API with built-in support for:

- Synchronous execution with automatic polling
- Batch execution with thread-based concurrency
- Automatic retries with exponential backoff
- Customizable result handlers for response processing
- Request/response logging to disk for debugging

Example:
    >>> from stkai.rqc import RemoteQuickCommand, RqcRequest
    >>> rqc = RemoteQuickCommand(slug_name="my-quick-command")
    >>> request = RqcRequest(payload={"input": "data"})
    >>> response = rqc.execute(request)
    >>> if response.is_completed():
    ...     print(response.result)

For batch execution:
    >>> requests = [RqcRequest(payload={"id": i}) for i in range(10)]
    >>> responses = rqc.execute_many(requests)
"""

from stkai.rqc._event_listeners import (
    # Event listener implementations
    FileLoggingListener,
)
from stkai.rqc._handlers import (
    DEFAULT_RESULT_HANDLER,
    RAW_RESULT_HANDLER,
    # Result handler implementations
    ChainedResultHandler,
    JsonResultHandler,
    RawResultHandler,
)
from stkai.rqc._http import (
    # HTTP client implementations
    StkCLIRqcHttpClient,
)
from stkai.rqc._remote_quick_command import (
    ExecutionIdIsMissingError,
    # Errors
    MaxRetriesExceededError,
    # Main client
    RemoteQuickCommand,
    # Event listener interface
    RqcEventListener,
    # HTTP client interface
    RqcHttpClient,
    # Data models
    RqcRequest,
    RqcResponse,
    RqcResponseStatus,
    RqcResultContext,
    # Result handler interface
    RqcResultHandler,
    RqcResultHandlerError,
)

__all__ = [
    # Data models
    "RqcRequest",
    "RqcResponse",
    "RqcResponseStatus",
    "RqcResultContext",
    # Result handler interface
    "RqcResultHandler",
    # Result handler implementations
    "ChainedResultHandler",
    "JsonResultHandler",
    "RawResultHandler",
    "DEFAULT_RESULT_HANDLER",
    "RAW_RESULT_HANDLER",
    # Event listener interface
    "RqcEventListener",
    # Event listener implementations
    "FileLoggingListener",
    # HTTP client interface
    "RqcHttpClient",
    # HTTP client implementations
    "StkCLIRqcHttpClient",
    # Errors
    "MaxRetriesExceededError",
    "RqcResultHandlerError",
    "ExecutionIdIsMissingError",
    # Main client
    "RemoteQuickCommand",
]
