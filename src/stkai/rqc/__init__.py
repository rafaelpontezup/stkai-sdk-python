"""
Remote Quick Commands (RQC) module for StackSpot AI.

This module provides a client abstraction for executing Remote Quick Commands
against the StackSpot AI API.
"""

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
