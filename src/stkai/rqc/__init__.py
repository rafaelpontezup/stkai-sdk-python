"""
Remote Quick Commands (RQC) module for StackSpot AI.

This module provides a client abstraction for executing Remote Quick Commands
against the StackSpot AI API.
"""

from stkai.rqc._remote_quick_command import (
    # Data models
    RqcRequest,
    RqcResponse,
    RqcResponseStatus,
    RqcResultContext,
    # Result handlers
    RqcResultHandler,
    ChainedResultHandler,
    JsonResultHandler,
    RawResultHandler,
    DEFAULT_RESULT_HANDLER,
    RAW_RESULT_RESULT_HANDLER,
    # HTTP client
    RqcHttpClient,
    StkCLIRqcHttpClient,
    # Errors
    MaxRetriesExceededError,
    RqcResultHandlerError,
    ExecutionIdIsMissingError,
    # Main client
    RemoteQuickCommand,
)

__all__ = [
    # Data models
    "RqcRequest",
    "RqcResponse",
    "RqcResponseStatus",
    "RqcResultContext",
    # Result handlers
    "RqcResultHandler",
    "ChainedResultHandler",
    "JsonResultHandler",
    "RawResultHandler",
    "DEFAULT_RESULT_HANDLER",
    "RAW_RESULT_RESULT_HANDLER",
    # HTTP client
    "RqcHttpClient",
    "StkCLIRqcHttpClient",
    # Errors
    "MaxRetriesExceededError",
    "RqcResultHandlerError",
    "ExecutionIdIsMissingError",
    # Main client
    "RemoteQuickCommand",
]
