"""
StackSpot AI SDK for Python.

A Python SDK for integrating with StackSpot AI services,
including Remote Quick Commands (RQC) and more.

Quick Start:
    >>> from stkai import RemoteQuickCommand, RqcRequest
    >>> rqc = RemoteQuickCommand(slug_name="my-quick-command")
    >>> request = RqcRequest(payload={"prompt": "Hello, AI!"})
    >>> response = rqc.execute(request)
    >>> print(response.result)

Main Classes:
    - RemoteQuickCommand: Client for executing Remote Quick Commands.
    - RqcRequest: Represents a request to be sent to the RQC API.
    - RqcResponse: Represents the response received from the RQC API.
    - RqcResponseStatus: Enum with possible response statuses (COMPLETED, FAILURE, ERROR, TIMEOUT).
"""

__version__ = "0.1.0"

from stkai.rqc import (
    RemoteQuickCommand,
    RqcRequest,
    RqcResponse,
    RqcResponseStatus,
)

__all__ = [
    "__version__",
    "RemoteQuickCommand",
    "RqcRequest",
    "RqcResponse",
    "RqcResponseStatus",
]
