"""
Data models for Remote Quick Command.

This module contains the core data structures used across the RQC module:
- RqcRequest: Represents a request to be executed
- RqcResponse: Represents the response from an execution
- RqcExecutionStatus: Enum of execution lifecycle states
"""

import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from stkai._utils import save_json_file


class RqcExecutionStatus(str, Enum):
    """
    Status of an RQC execution lifecycle.

    Attributes:
        PENDING: Client-side status before request is submitted to server.
        CREATED: Server acknowledged the request and created an execution.
        RUNNING: Execution is currently being processed by the server.
        COMPLETED: Execution finished successfully with a result.
        FAILURE: Execution failed on the server-side (StackSpot AI returned an error).
        ERROR: Client-side error occurred (network issues, invalid response, handler errors).
        TIMEOUT: Execution did not complete within the configured poll_max_duration.
    """
    PENDING = "PENDING"
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILURE = "FAILURE"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_exception(cls, exc: Exception) -> "RqcExecutionStatus":
        """
        Determine the appropriate status for an exception.

        Args:
            exc: The exception that occurred during RQC execution.

        Returns:
            TIMEOUT for timeout exceptions, ERROR for all others.

        Example:
            >>> try:
            ...     execution_id = rqc._create_execution(request)
            ... except Exception as e:
            ...     status = RqcExecutionStatus.from_exception(e)
            ...     # status is TIMEOUT if e is a timeout, ERROR otherwise
        """
        from stkai._utils import is_timeout_exception
        return cls.TIMEOUT if is_timeout_exception(exc) else cls.ERROR


@dataclass
class RqcRequest:
    """
    Represents a Remote QuickCommand request.

    This class encapsulates all data needed to execute a Remote Quick Command,
    including the payload to send and optional metadata for tracking purposes.

    Attributes:
        payload: The input data to send to the Quick Command. Can be any JSON-serializable object.
        id: Unique identifier for this request. Auto-generated as UUID if not provided.
        metadata: Optional dictionary for storing custom metadata (e.g., source file, context).

    Example:
        >>> request = RqcRequest(
        ...     payload={"prompt": "Analyze this code", "code": "def foo(): pass"},
        ...     id="my-custom-id",
        ...     metadata={"source": "main.py", "line": 42}
        ... )
    """
    payload: Any
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict[str, Any] = field(default_factory=dict)
    _execution_id: str | None = None
    _submitted_at: float | None = None

    def __post_init__(self) -> None:
        assert self.id, "Request ID can not be empty."
        assert self.payload, "Request payload can not be empty."

    @property
    def execution_id(self) -> str | None:
        """Returns the execution ID assigned by the server after creation, or None if not yet executed."""
        return self._execution_id

    @property
    def submitted_at(self) -> datetime | None:
        """Returns the submission timestamp as datetime (UTC), or None if not yet submitted."""
        if self._submitted_at is None:
            return None
        return datetime.fromtimestamp(self._submitted_at, tz=UTC)

    def mark_as_submitted(self, execution_id: str) -> None:
        """
        Marks the request as submitted by storing the server-assigned execution ID and timestamp.

        This method is called internally after a successful create-execution API call.

        Args:
            execution_id: The execution ID returned by the StackSpot AI API.
        """
        assert execution_id, "Execution ID received from StackSpot AI server can not be empty."
        self._execution_id = execution_id
        self._submitted_at = time.time()

    def to_input_data(self) -> dict[str, Any]:
        """Converts the request payload to the format expected by the RQC API."""
        return {
            "input_data": self.payload,
        }

    def write_to_file(self, output_dir: Path) -> Path:
        """
        Persists the request payload to a JSON file for debugging purposes.

        Args:
            output_dir: Directory where the JSON file will be saved.

        Returns:
            Path to the created JSON file.

        The file is named `{tracking_id}-request.json` where tracking_id is either
        the execution_id (if available) or the request id.
        """
        assert output_dir, "Output directory is required."
        assert output_dir.is_dir(), f"Output directory is not a directory ({output_dir})."

        _tracking_id = self.execution_id or self.id
        _tracking_id = re.sub(r'[^\w.$-]', '_', _tracking_id)

        target_file = output_dir / f"{_tracking_id}-request.json"
        save_json_file(
            data=self.to_input_data(),
            file_path=target_file
        )
        return target_file


@dataclass(frozen=True)
class RqcResponse:
    """
    Represents the full Remote QuickCommand response.

    This immutable class contains the execution result, status, and any error
    information from a Remote Quick Command execution.

    Attributes:
        request: The original RqcRequest that generated this response.
        status: The final status of the execution (COMPLETED, FAILURE, ERROR, or TIMEOUT).
        result: The processed result from the result handler (only set when COMPLETED).
        error: Error message describing what went wrong (only set on non-COMPLETED status).
        raw_response: The raw JSON response from the StackSpot AI API (for debugging).

    Example:
        >>> response = rqc.execute(request)
        >>> if response.is_completed():
        ...     print(response.result)
        ... else:
        ...     print(f"Error: {response.error}")
    """
    request: RqcRequest
    status: RqcExecutionStatus
    result: Any | None = None
    error: str | None = None
    raw_response: Any | None = None

    def __post_init__(self) -> None:
        assert self.request, "RQC-Request can not be empty."
        assert self.status, "Status can not be empty."

    @property
    def execution_id(self) -> str | None:
        """Returns the execution ID from the associated request."""
        return self.request.execution_id

    @property
    def raw_result(self) -> Any:
        """Extracts the 'result' field from the raw API response, if available."""
        if not self.raw_response:
            return None

        _raw_result = None
        if isinstance(self.raw_response, dict):
            _raw_result = self.raw_response.get("result")

        return _raw_result

    def is_pending(self) -> bool:
        """Returns True if the request has not been submitted yet."""
        return self.status == RqcExecutionStatus.PENDING

    def is_created(self) -> bool:
        """Returns True if the execution was created but not yet running."""
        return self.status == RqcExecutionStatus.CREATED

    def is_running(self) -> bool:
        """Returns True if the execution is currently being processed."""
        return self.status == RqcExecutionStatus.RUNNING

    def is_completed(self) -> bool:
        """Returns True if the execution completed successfully."""
        return self.status == RqcExecutionStatus.COMPLETED

    def is_failure(self) -> bool:
        """Returns True if the execution failed on the server-side."""
        return self.status == RqcExecutionStatus.FAILURE

    def is_error(self) -> bool:
        """Returns True if a client-side error occurred during execution."""
        return self.status == RqcExecutionStatus.ERROR

    def is_timeout(self) -> bool:
        """Returns True if the execution timed out waiting for completion."""
        return self.status == RqcExecutionStatus.TIMEOUT

    def error_with_details(self) -> dict[str, Any]:
        """Returns a dictionary with error details for non-completed responses."""
        if self.is_completed():
            return {}

        return {
            "status": self.status,
            "error_message": self.error,
            "response_body": self.raw_response or {},
        }

    def write_to_file(self, output_dir: Path) -> Path:
        """
        Persists the response to a JSON file for debugging purposes.

        Args:
            output_dir: Directory where the JSON file will be saved.

        Returns:
            Path to the created JSON file.

        The file is named `{tracking_id}-response-{status}.json` where tracking_id
        is either the execution_id (if available) or the request id.
        """
        assert output_dir, "Output directory is required."
        assert output_dir.is_dir(), f"Output directory is not a directory ({output_dir})."

        response_result = self.raw_response or {}
        if not self.is_completed():
            response_result = self.error_with_details()

        _tracking_id = self.request.execution_id or self.request.id
        _tracking_id = re.sub(r'[^\w.$-]', '_', _tracking_id)

        target_file = output_dir / f"{_tracking_id}-response-{self.status}.json"
        save_json_file(
            data=response_result,
            file_path=target_file
        )
        return target_file
