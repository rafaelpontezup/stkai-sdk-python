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

from stkai._retry import MaxRetriesExceededError
from stkai.rqc._event_listeners import (
    FileLoggingListener,
    # Event listener interface
    RqcEventListener,
    # Event listener implementations
    RqcPhasedEventListener,
)
from stkai.rqc._handlers import (
    DEFAULT_RESULT_HANDLER,
    RAW_RESULT_HANDLER,
    # Result handler implementations
    ChainedResultHandler,
    JsonResultHandler,
    RawResultHandler,
    # Result handler interface and context
    RqcResultContext,
    RqcResultHandler,
)
from stkai.rqc._models import (
    # Data models
    RqcExecutionStatus,
    RqcRequest,
    RqcResponse,
)
from stkai.rqc._remote_quick_command import (
    # Options
    CreateExecutionOptions,
    # Errors
    ExecutionIdIsMissingError,
    GetResultOptions,
    # Main client
    RemoteQuickCommand,
    RqcOptions,
    RqcResultHandlerError,
)

__all__ = [
    # Options
    "CreateExecutionOptions",
    "GetResultOptions",
    "RqcOptions",
    # Data models
    "RqcRequest",
    "RqcResponse",
    "RqcExecutionStatus",
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
    "RqcPhasedEventListener",
    # Errors
    "MaxRetriesExceededError",
    "RqcResultHandlerError",
    "ExecutionIdIsMissingError",
    # Main client
    "RemoteQuickCommand",
]
