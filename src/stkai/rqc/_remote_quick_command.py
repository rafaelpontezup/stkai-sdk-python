"""
Remote Quick Command (RQC) client for StackSpot AI.

This module provides a synchronous client for executing Remote Quick Commands
with built-in polling, retries, and thread-based concurrency.
"""

import json
import logging
import re
import time
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import requests

from stkai.rqc._utils import save_json_file, sleep_with_jitter

# ======================
# Options
# ======================

@dataclass(frozen=True)
class CreateExecutionOptions:
    """
    Options for the create-execution phase.

    Controls retry behavior and timeouts when creating a new RQC execution.

    Attributes:
        max_retries: Maximum retry attempts for failed create-execution calls.
        backoff_factor: Multiplier for exponential backoff (delay = factor * 2^attempt).
        request_timeout: HTTP request timeout in seconds.
    """
    max_retries: int = 3
    backoff_factor: float = 0.5
    request_timeout: int = 30


@dataclass(frozen=True)
class GetResultOptions:
    """
    Options for the get-result (polling) phase.

    Controls polling behavior and timeouts when waiting for execution completion.

    Attributes:
        poll_interval: Seconds to wait between polling status checks.
        poll_max_duration: Maximum seconds to wait before timing out.
        overload_timeout: Maximum seconds to tolerate CREATED status before assuming server overload.
        request_timeout: HTTP request timeout in seconds.
    """
    poll_interval: float = 10.0
    poll_max_duration: float = 600.0
    overload_timeout: float = 60.0
    request_timeout: int = 30


# ======================
# Data Models
# ======================

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


# ======================
# Result Handler
# ======================

@dataclass(frozen=True)
class RqcResultContext:
    """
    Context passed to result handlers during processing.

    This immutable class provides result handlers with all the information
    needed to process an execution result, including the original request
    and the raw result from the API.

    Attributes:
        request: The original RqcRequest (with execution_id already set).
        raw_result: The unprocessed result from the StackSpot AI API.
        handled: Flag indicating if a previous handler has already processed this result.
    """
    request: RqcRequest
    raw_result: Any
    handled: bool = False

    def __post_init__(self) -> None:
        assert self.request, "RQC-Request can not be empty."
        assert self.request.execution_id, "RQC-Request's execution_id can not be empty."
        assert self.handled is not None, "Context's handled flag can not be None."

    @property
    def execution_id(self) -> str:
        """Returns the execution ID from the associated request."""
        assert self.request.execution_id, "Execution ID is expected to exist at this point."
        return self.request.execution_id


class RqcResultHandler(ABC):
    """
    Abstract base class for result handlers.

    Result handlers are responsible for transforming the raw API response
    into a more useful format. Implement this class to create custom handlers.

    Example:
        >>> class MyHandler(RqcResultHandler):
        ...     def handle_result(self, context: RqcResultContext) -> Any:
        ...         return context.raw_result.upper()
    """

    @abstractmethod
    def handle_result(self, context: RqcResultContext) -> Any:
        """
        Process the result and return the transformed value.

        Args:
            context: The RqcResultContext containing the raw result and request info.

        Returns:
            The transformed result value.

        Raises:
            Any exception raised will be wrapped in RqcResultHandlerError.
        """
        pass


# ======================
# Event Listener
# ======================

class RqcEventListener:
    """
    Base class for observing RQC execution lifecycle events.

    Listeners are read-only observers: they can react to events, log, notify,
    or collect metrics, but should NOT modify the request or response.

    The `context` dict is shared across all listener calls for a single execution,
    allowing listeners to store and retrieve state (e.g., start time for telemetry).

    All methods have default empty implementations, so subclasses only need to
    override the methods they care about.

    Example:
        >>> class MetricsListener(RqcEventListener):
        ...     def on_before_execute(self, request, context):
        ...         context['start_time'] = time.time()
        ...
        ...     def on_after_execute(self, request, response, context):
        ...         duration = time.time() - context['start_time']
        ...         statsd.timing('rqc.duration', duration)
    """

    def on_before_execute(self, request: "RqcRequest", context: dict[str, Any]) -> None:
        """
        Called before starting the execution.

        Args:
            request: The request about to be executed.
            context: Mutable dict for sharing state between listener calls.
        """
        pass

    def on_status_change(
        self,
        request: "RqcRequest",
        old_status: "RqcExecutionStatus",
        new_status: "RqcExecutionStatus",
        context: dict[str, Any],
    ) -> None:
        """
        Called when the execution status changes throughout the lifecycle.

        This method is invoked at key state transitions:
        - PENDING → CREATED: Execution was successfully created on the server.
        - PENDING → ERROR/TIMEOUT: Failed to create execution (network error, timeout, etc.).
        - CREATED → RUNNING: Server started processing the execution.
        - RUNNING → COMPLETED: Execution finished successfully.
        - RUNNING → FAILURE: Execution failed on the server-side.
        - Any → TIMEOUT: Polling timed out waiting for completion.

        Args:
            request: The request being executed.
            old_status: The previous status.
            new_status: The new status.
            context: Mutable dict for sharing state between listener calls.
        """
        pass

    def on_after_execute(
        self,
        request: "RqcRequest",
        response: "RqcResponse",
        context: dict[str, Any],
    ) -> None:
        """
        Called after execution completes (success or failure).

        Check response.status or response.is_completed() to determine the outcome.

        Args:
            request: The executed request.
            response: The final response (always provided, check status for outcome).
            context: Mutable dict for sharing state between listener calls.
        """
        pass


# ======================
# HTTP Client
# ======================

class RqcHttpClient(ABC):
    """
    Abstract base class for RQC HTTP clients.

    Implement this class to provide custom HTTP client implementations
    for different authentication mechanisms or environments.

    See Also:
        StkCLIRqcHttpClient: Default implementation using StackSpot CLI credentials.
    """

    @abstractmethod
    def get_with_authorization(self, execution_id: str, timeout: int = 30) -> requests.Response:
        """
        Execute an authorized GET request to retrieve execution status.

        Args:
            execution_id: The execution ID to query.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response from the StackSpot AI API.
        """
        pass

    @abstractmethod
    def post_with_authorization(self, slug_name: str, data: dict[str, Any] | None = None, timeout: int = 20) -> requests.Response:
        """
        Execute an authorized POST request to create an execution.

        Args:
            slug_name: The Quick Command slug name to execute.
            data: The request payload to send.
            timeout: Request timeout in seconds.

        Returns:
            The HTTP response from the StackSpot AI API.
        """
        pass


# ======================
# Errors and exceptions
# ======================

class MaxRetriesExceededError(RuntimeError):
    """
    Raised when the maximum number of retries is exceeded.

    This exception is raised when all retry attempts to create an execution
    have failed due to transient errors (5xx status codes or network issues).

    Attributes:
        last_exception: The last exception that caused the retry to fail.
    """

    def __init__(self, message: str, last_exception: Exception | None = None):
        super().__init__(message)
        self.last_exception = last_exception


class RqcResultHandlerError(RuntimeError):
    """
    Raised when the result handler fails to process the result.

    This exception wraps any error that occurs during result processing,
    providing access to the original cause and the handler that failed.

    Attributes:
        cause: The original exception that caused the handler to fail.
        result_handler: The handler instance that raised the error.
    """

    def __init__(self, message: str, cause: Exception | None = None, result_handler: "RqcResultHandler | None" = None):
        super().__init__(message)
        self.cause = cause
        self.result_handler = result_handler


class ExecutionIdIsMissingError(RuntimeError):
    """
    Raised when the execution ID is missing or not provided.

    This exception indicates that the StackSpot AI API returned an invalid
    response without an execution ID after a create-execution request.
    """

    def __init__(self, message: str):
        super().__init__(message)


# ======================
# Client
# ======================

class RemoteQuickCommand:
    """
    Synchronous client for executing Remote QuickCommands (RQC).

    This client provides a high-level interface for executing Remote Quick Commands
    against the StackSpot AI API with built-in support for:

    - Automatic polling until execution completes
    - Exponential backoff with retries for transient failures
    - Thread-based concurrency for batch execution
    - Request/response logging to disk for debugging

    Example:
        >>> rqc = RemoteQuickCommand(slug_name="my-quick-command")
        >>> request = RqcRequest(payload={"prompt": "Hello!"})
        >>> response = rqc.execute(request)
        >>> if response.is_completed():
        ...     print(response.result)

    Attributes:
        slug_name: The Quick Command slug name to execute.
        create_execution_options: Options for the create-execution phase.
        get_result_options: Options for the get-result (polling) phase.
        max_workers: Maximum concurrent executions for batch mode (default: 8).
        http_client: HTTP client for API calls (default: StkCLIRqcHttpClient).
        listeners: List of event listeners for observing execution lifecycle.
    """

    def __init__(
        self,
        slug_name: str,
        create_execution_options: CreateExecutionOptions | None = None,
        get_result_options: GetResultOptions | None = None,
        max_workers: int | None = None,
        http_client: RqcHttpClient | None = None,
        listeners: list[RqcEventListener] | None = None,
    ):
        """
        Initialize the RemoteQuickCommand client.

        By default, a FileLoggingListener is registered to persist request/response
        to JSON files in `output/rqc/{slug_name}/`. Pass `listeners=[]` to disable
        this behavior, or provide your own list of listeners.

        Args:
            slug_name: The Quick Command slug name (identifier) to execute.
            create_execution_options: Options for the create-execution phase.
            get_result_options: Options for the get-result (polling) phase.
            max_workers: Maximum number of concurrent threads for execute_many().
                If None, uses global config (default: 8).
            http_client: Custom HTTP client implementation for API calls.
                If None, uses StkCLIRqcHttpClient (requires StackSpot CLI).
            listeners: Event listeners for observing execution lifecycle.
                If None (default), registers a FileLoggingListener.
                If [] (empty list), disables default logging.

        Raises:
            AssertionError: If any required parameter is invalid.
        """
        assert slug_name, "RQC slug_name can not be empty."
        self.slug_name = slug_name

        # Get global config for defaults
        from stkai._config import STKAI_CONFIG
        cfg = STKAI_CONFIG.rqc

        # Use provided options, or create from global config
        if create_execution_options is None:
            create_execution_options = CreateExecutionOptions(
                max_retries=cfg.max_retries,
                backoff_factor=cfg.backoff_factor,
                request_timeout=cfg.request_timeout,
            )
        self.create_execution_options = create_execution_options

        if get_result_options is None:
            get_result_options = GetResultOptions(
                poll_interval=cfg.poll_interval,
                poll_max_duration=cfg.poll_max_duration,
                overload_timeout=cfg.overload_timeout,
                request_timeout=cfg.request_timeout,
            )
        self.get_result_options = get_result_options

        # Use provided max_workers, or fallback to global config
        if max_workers is None:
            max_workers = cfg.max_workers

        assert max_workers, "Thread-pool max_workers can not be empty."
        assert max_workers > 0, "Thread-pool max_workers must be greater than 0."

        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

        if not http_client:
            from stkai.rqc._http import StkCLIRqcHttpClient
            http_client = StkCLIRqcHttpClient()
        self.http_client: RqcHttpClient = http_client

        # Setup default FileLoggingListener when no listeners are specified (None).
        # To disable logging, pass an empty list: `listeners=[]`
        if listeners is None:
            from stkai.rqc._event_listeners import FileLoggingListener
            listeners = [
                FileLoggingListener(output_dir=f"output/rqc/{self.slug_name}")
            ]
        self.listeners: list[RqcEventListener] = listeners

    # ======================
    # Public API
    # ======================

    def execute_many(
        self,
        request_list: list[RqcRequest],
        result_handler: RqcResultHandler | None = None,
    ) -> list[RqcResponse]:
        """
        Executes multiple RQC requests concurrently, waits for their completion (blocking),
        and returns their responses.

        Each request is executed in parallel threads using the internal thread-pool.
        Returns a list of RqcResponse objects in the same order as `requests_list`.

        Args:
            request_list: List of RqcRequest objects to execute.
            result_handler: Optional custom handler used to process the raw response.

        Returns:
            List[RqcResponse]: One response per request.
        """
        if not request_list:
            return []

        logging.info(
            f"{'RQC-Batch-Execution'[:26]:<26} | RQC | "
            f"🛜 Starting batch execution of {len(request_list)} requests."
        )
        logging.info(f"{'RQC-Batch-Execution'[:26]:<26} | RQC |    ├ max_concurrent={self.max_workers}")
        logging.info(f"{'RQC-Batch-Execution'[:26]:<26} | RQC |    └ slug_name='{self.slug_name}'")

        # Use thread-pool for parallel calls to `_execute_workflow`
        future_to_index = {
            self.executor.submit(
                self._execute_workflow,           # function ref
                request=req,                      # arg-1
                result_handler=result_handler     # arg-2
            ): idx
            for idx, req in enumerate(request_list)
        }

        # Block and waits for all responses to be finished
        responses_map: dict[int, RqcResponse] = {}

        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            correlated_request = request_list[idx]
            try:
                responses_map[idx] = future.result()
            except Exception as e:
                logging.exception(f"{correlated_request.id[:26]:<26} | RQC | ❌ Execution failed in batch(seq={idx}): {e}")
                responses_map[idx] = RqcResponse(
                    request=correlated_request,
                    status=RqcExecutionStatus.ERROR,
                    error=str(e),
                )

        # Rebuild responses list in the same order of requests list
        responses = [
            responses_map[i] for i in range(len(request_list))
        ]

        # Race-condition check: ensure both lists have the same length
        assert len(responses) == len(request_list), (
            f"🌀 Sanity check | Unexpected mismatch: responses(size={len(responses)}) is different from requests(size={len(request_list)})."
        )
        # Race-condition check: ensure each response points to its respective request
        assert all(resp.request is req for req, resp in zip(request_list, responses, strict=True)), (
            "🌀 Sanity check | Unexpected mismatch: some responses do not reference their corresponding requests."
        )

        logging.info(
            f"{'RQC-Batch-Execution'[:26]:<26} | RQC | 🛜 Batch execution finished."
        )
        logging.info(f"{'RQC-Batch-Execution'[:26]:<26} | RQC |    ├ total of responses = {len(responses)}")

        from collections import Counter
        totals_per_status = Counter(r.status for r in responses)
        items = totals_per_status.items()
        for idx, (status, total) in enumerate(items):
            icon = "└" if idx == (len(items) - 1) else "├"
            logging.info(f"{'RQC-Batch-Execution'[:26]:<26} | RQC |    {icon} total of responses with status {status:<9} = {total}")

        return responses

    def execute(
        self,
        request: RqcRequest,
        result_handler: RqcResultHandler | None = None,
    ) -> RqcResponse:
        """
        Executes a Remote QuickCommand synchronously and waits for its completion (blocking).

        This method sends a single request to the remote StackSpot AI QuickCommand API,
        monitors its execution until a terminal status is reached (COMPLETED, FAILURE, ERROR, or TIMEOUT),
        and returns an RqcResponse object containing the result or error details.

        Args:
            request: The RqcRequest instance representing the command to execute.
            result_handler: Optional custom handler used to process the raw response.

        Returns:
            RqcResponse: The final response object, always returned even if an error occurs.
        """
        logging.info(f"{request.id[:26]:<26} | RQC | 🛜 Starting execution of a single request.")
        logging.info(f"{request.id[:26]:<26} | RQC |    └ slug_name='{self.slug_name}'")

        response = self._execute_workflow(
            request=request, result_handler=result_handler
        )

        logging.info(
            f"{request.id[:26]:<26} | RQC | 🛜 Execution finished with status: {response.status}"
        )

        assert response.request is request, \
            "🌀 Sanity check | Unexpected mismatch: response do not reference its corresponding request."
        return response

    def _execute_workflow(
        self,
        request: RqcRequest,
        result_handler: RqcResultHandler | None = None,
    ) -> RqcResponse:
        """
        Internal workflow that executes a Remote QuickCommand.

        This method contains the actual execution logic: creating the execution,
        polling for status, and processing the result. It is called by both
        `execute()` (for single requests) and `execute_many()` (for batch requests).

        Args:
            request: The RqcRequest instance representing the command to execute.
            result_handler: Optional custom handler used to process the raw response.

        Returns:
            RqcResponse: The final response object, always returned even if an error occurs.
        """
        assert request, "🌀 Sanity check | RQC-Request can not be None."
        assert request.id, "🌀 Sanity check | RQC-Request ID can not be None."

        # Create context for listeners (shared across all listener calls for this execution)
        event_context: dict[str, Any] = {}

        # Notify listeners: before execute
        self._notify_listeners("on_before_execute", request=request, context=event_context)

        # Phase-1: Try to create the remote execution
        response = None
        try:
            execution_id = self._create_execution(request=request)
        except Exception as e:
            logging.exception(f"{request.id[:26]:<26} | RQC | ❌ Failed to create execution: {e}")
            # Determine status: TIMEOUT if caused by HTTP timeout, ERROR otherwise
            status = RqcExecutionStatus.ERROR
            if isinstance(e, MaxRetriesExceededError) and isinstance(e.last_exception, requests.exceptions.Timeout):
                status = RqcExecutionStatus.TIMEOUT
            # Notify status change: PENDING → ERROR or TIMEOUT
            self._notify_listeners(
                "on_status_change",
                request=request,
                old_status=RqcExecutionStatus.PENDING,
                new_status=status,
                context=event_context,
            )
            response = RqcResponse(
                request=request,
                status=status,
                error=f"Failed to create execution: {e}",
            )
            return response
        finally:
            # Notify listeners: after execute (in case of error)
            if response:
                self._notify_listeners("on_after_execute", request=request, response=response, context=event_context)

        assert execution_id, "🌀 Sanity check | Execution was created but `execution_id` is missing."
        assert request.execution_id, "🌀 Sanity check | RQC-Request has no `execution_id` registered on it. Was the `request.mark_as_submitted()` method called?"
        assert execution_id == request.execution_id, "🌀 Sanity check | RQC-Request's `execution_id` and response's `execution_id` are different."

        # Notify status change: PENDING → CREATED (execution created successfully)
        self._notify_listeners(
            "on_status_change",
            request=request,
            old_status=RqcExecutionStatus.PENDING,
            new_status=RqcExecutionStatus.CREATED,
            context=event_context,
        )

        # Phase-2: Poll for status
        if not result_handler:
            from stkai.rqc._handlers import DEFAULT_RESULT_HANDLER
            result_handler = DEFAULT_RESULT_HANDLER

        response = None
        try:
            response = self._poll_until_done(
                request=request, handler=result_handler, context=event_context
            )
        except Exception as e:
            logging.error(f"{execution_id} | RQC | ❌ Error during polling: {e}")
            response = RqcResponse(
                request=request,
                status=RqcExecutionStatus.ERROR,
                error=f"Error during polling: {e}",
            )
        finally:
            # Notify listeners: after execute (always called)
            self._notify_listeners("on_after_execute", request=request, response=response, context=event_context)

        assert response, "🌀 Sanity check | RQC-Response was not created during the polling phase."
        return response

    # ======================
    # Internals
    # ======================

    def _create_execution(self, request: RqcRequest) -> str:
        """Creates an RQC execution via POST with retries and exponential backoff."""
        assert request, "🌀 Sanity check | RQC-Request not provided to create-execution phase."

        request_id = request.id
        input_data = request.to_input_data()
        options = self.create_execution_options
        max_attempts = options.max_retries + 1

        for attempt in range(max_attempts):
            try:
                logging.info(f"{request_id[:26]:<26} | RQC | Sending request to create execution (attempt {attempt + 1}/{max_attempts})...")
                response = self.http_client.post_with_authorization(
                    slug_name=self.slug_name, data=input_data, timeout=options.request_timeout
                )
                assert isinstance(response, requests.Response), \
                    f"🌀 Sanity check | Object returned by `post_with_authorization` method is not an instance of `requests.Response`. ({response.__class__})"

                response.raise_for_status()
                execution_id: str = response.json()
                if not execution_id:
                    raise ExecutionIdIsMissingError("No `execution_id` returned in the create execution response by server.")

                # Registers create execution response on its request
                request.mark_as_submitted(execution_id=execution_id)
                logging.info(
                    f"{request_id[:26]:<26} | RQC | ✅ Execution successfully created ({execution_id})"
                )
                return execution_id

            except requests.RequestException as e:
                # Don't retry on 4xx errors
                _response = getattr(e, "response", None)
                if _response is not None and 400 <= _response.status_code < 500:
                    raise
                # Retry up to max_retries
                if attempt < options.max_retries:
                    sleep_time = options.backoff_factor * (2 ** attempt)
                    logging.warning(f"{request_id[:26]:<26} | RQC | ⚠️ Failed to create execution: {e}")
                    logging.warning(f"{request_id[:26]:<26} | RQC | 🔁️ Retrying to create execution in {sleep_time:.1f} seconds...")
                    sleep_with_jitter(sleep_time)
                else:
                    logging.error(f"{request_id[:26]:<26} | RQC | ❌ Max retries exceeded while creating execution. Last error: {e}")
                    raise MaxRetriesExceededError(
                        message=f"Max retries exceeded while creating execution. Last error: {e}",
                        last_exception=e
                    ) from e

        # It should never happen
        raise RuntimeError(
            "Unexpected error while creating execution: "
            "reached end of `_create_execution` method without returning the execution ID."
        )

    def _poll_until_done(
        self,
        request: RqcRequest,
        handler: RqcResultHandler,
        context: dict[str, Any],
    ) -> RqcResponse:
        """Polls the status endpoint until the execution reaches a terminal state."""
        assert request, "🌀 Sanity check | RQC-Request not provided to polling phase."
        assert handler, "🌀 Sanity check | Result Handler not provided to polling phase."
        assert context is not None, "🌀 Sanity check | Event context not provided to polling phase."
        assert request.execution_id, "🌀 Sanity check | Execution ID not provided to polling phase."

        start_time = time.time()
        options = self.get_result_options
        execution_id = request.execution_id

        last_status: RqcExecutionStatus = RqcExecutionStatus.CREATED  # Starts at CREATED since we notify PENDING → CREATED before polling
        created_since: float | None = None

        logging.info(f"{execution_id} | RQC | Starting polling loop...")

        try:
            while True:
                # Gives up after poll max-duration (it prevents infinite loop)
                if time.time() - start_time > options.poll_max_duration:
                    raise TimeoutError(
                        f"Timeout after {options.poll_max_duration} seconds waiting for RQC execution to complete. "
                        f"Last status: `{last_status}`."
                    )

                try:
                    response = self.http_client.get_with_authorization(
                        execution_id=execution_id, timeout=options.request_timeout
                    )
                    assert isinstance(response, requests.Response), \
                        f"🌀 Sanity check | Object returned by `get_with_authorization` method is not an instance of `requests.Response`. ({response.__class__})"

                    response.raise_for_status()
                    response_data = response.json()
                except requests.RequestException as e:
                    # Don't retry on 4xx errors
                    _response = getattr(e, "response", None)
                    if _response is not None and 400 <= _response.status_code < 500:
                        raise
                    # Sleeps a little bit before trying again
                    logging.warning(
                        f"{execution_id} | RQC | ⚠️ Temporary polling failure: {e}"
                    )
                    sleep_with_jitter(options.poll_interval)
                    continue

                status = RqcExecutionStatus(
                    response_data.get('progress', {}).get('status').upper()
                )
                if status != last_status:
                    logging.info(f"{execution_id} | RQC | Current status: {status}")
                    # Notify listeners: status change
                    self._notify_listeners(
                        "on_status_change", request=request,
                        old_status=last_status, new_status=status, context=context
                    )
                    last_status = status

                if status == RqcExecutionStatus.COMPLETED:
                    try:
                        logging.info(f"{execution_id} | RQC | Processing the execution result...")
                        raw_result = response_data.get("result")
                        processed_result = handler.handle_result(
                            context=RqcResultContext(request, raw_result)
                        )
                        logging.info(f"{execution_id} | RQC | ✅ Execution finished with status: {status}")
                        return RqcResponse(
                            request=request,
                            status=RqcExecutionStatus.COMPLETED,
                            result=processed_result,
                            raw_response=response_data
                        )
                    except Exception as e:
                        handler_name = handler.__class__.__name__
                        logging.error(
                            f"{execution_id} | RQC | ❌ It's not possible to handle the result (handler={handler_name}).",
                        )
                        raise RqcResultHandlerError(
                            cause=e,
                            result_handler=handler,
                            message=f"Error while processing the response in the result handler ({handler_name}): {e}",
                        ) from e

                elif status == RqcExecutionStatus.FAILURE:
                    logging.error(
                        f"{execution_id} | RQC | ❌ Execution failed on the server-side with the following response: "
                        f"\n{json.dumps(response_data, indent=2)}"
                    )
                    return RqcResponse(
                        request=request,
                        status=RqcExecutionStatus.FAILURE,
                        error="Execution failed on the server-side with status 'FAILURE'. There's no details at all! Try to look at the logs.",
                        raw_response=response_data,
                    )
                elif status == RqcExecutionStatus.CREATED:
                    # Track how long we've been in CREATED status (possible server overload)
                    if created_since is None:
                        created_since = time.time()

                    elapsed_in_created = time.time() - created_since
                    if elapsed_in_created > options.overload_timeout:
                        raise TimeoutError(
                            f"Execution stuck in CREATED status for {elapsed_in_created:.2f}s. "
                            f"The server may be overloaded (queue backpressure)."
                        )

                    logging.warning(
                        f"{execution_id} | RQC | ⚠️ Execution is still in CREATED status "
                        f"({elapsed_in_created:.2f}s/{options.overload_timeout}s). Possible server overload..."
                    )
                    sleep_with_jitter(options.poll_interval)
                else:
                    logging.info(
                        f"{execution_id} | RQC | Execution is still running. Retrying in {int(options.poll_interval)} seconds..."
                    )
                    sleep_with_jitter(options.poll_interval)

        except TimeoutError as e:
            logging.error(f"{execution_id} | RQC | ❌ Polling timed out due to: {e}")
            # Notify status change: last_status → TIMEOUT
            self._notify_listeners(
                "on_status_change",
                request=request,
                old_status=last_status,
                new_status=RqcExecutionStatus.TIMEOUT,
                context=context,
            )
            return RqcResponse(
                request=request,
                status=RqcExecutionStatus.TIMEOUT,
                error=str(e),
            )

        # It should never happen
        raise RuntimeError(
            "Unexpected error while polling the status of execution: "
            "reached end of `_poll_until_done` method without returning the execution result."
        )

    def _notify_listeners(
        self,
        event: str,
        **kwargs: Any,
    ) -> None:
        """
        Notifies all registered listeners about an event.

        Exceptions raised by listeners are logged but do not interrupt execution.

        Args:
            event: The event method name (e.g., 'on_before_execute').
            **kwargs: Keyword arguments to pass to the listener method.
        """
        request: RqcRequest | None = kwargs.get("request")
        tracking_id = (request.execution_id or request.id) if request else "unknown"

        for listener in self.listeners:
            try:
                method = getattr(listener, event, None)
                if method and callable(method):
                    method(**kwargs)
            except Exception as e:
                listener_name = listener.__class__.__name__
                logging.warning(
                    f"{tracking_id[:26]:<26} | RQC | Event listener `{listener_name}.{event}()` raised an exception: {e}"
                )
