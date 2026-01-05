"""
Remote Quick Command (RQC) client for StackSpot AI.

This module provides a synchronous client for executing Remote Quick Commands
with built-in polling, retries, and thread-based concurrency.
"""

import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import requests

from stkai.rqc._utils import save_json_file, sleep_with_jitter

# ======================
# Data Models
# ======================

@dataclass
class RqcRequest:
    """Represents a Remote QuickCommand request."""
    payload: Any
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict[str, Any] | None = None
    _execution_id: str | None = None

    def __post_init__(self) -> None:
        assert self.id, "Request ID can not be empty."
        assert self.payload, "Request payload can not be empty."

    @property
    def execution_id(self) -> str | None:
        return self._execution_id

    def mark_as_finished(self, execution_id: str) -> None:
        self._execution_id = execution_id

    def to_input_data(self) -> dict[str, Any]:
        return {
            "input_data": self.payload,
        }

    def write_to_file(self, output_dir: Path) -> None:
        assert output_dir, "Output directory is required."
        assert output_dir.is_dir(), f"Output directory is not a directory ({output_dir})."

        _tracking_id = self.execution_id or self.id
        save_json_file(
            data=self.to_input_data(),
            file_path=output_dir / f"{_tracking_id}-request.json"
        )


class RqcResponseStatus(str, Enum):
    """Status of an RQC execution."""
    COMPLETED = "COMPLETED"
    FAILURE = "FAILURE"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class RqcResponse:
    """Represents the full Remote QuickCommand response."""
    request: RqcRequest
    status: RqcResponseStatus
    result: Any | None = None
    error: str | None = None
    raw_response: Any | None = None

    def __post_init__(self) -> None:
        assert self.request, "RQC-Request can not be empty."
        assert self.status, "Status can not be empty."

    @property
    def execution_id(self) -> str | None:
        return self.request.execution_id

    @property
    def raw_result(self) -> Any:
        if not self.raw_response:
            return None

        _raw_result = None
        if isinstance(self.raw_response, dict):
            _raw_result = self.raw_response.get("result")

        return _raw_result

    def is_error(self) -> bool:
        return self.status == RqcResponseStatus.ERROR

    def is_timeout(self) -> bool:
        return self.status == RqcResponseStatus.TIMEOUT

    def is_failure(self) -> bool:
        return self.status == RqcResponseStatus.FAILURE

    def is_completed(self) -> bool:
        return self.status == RqcResponseStatus.COMPLETED

    def error_with_details(self) -> dict[str, Any]:
        if self.is_completed():
            return {}

        return {
            "status": self.status,
            "error_message": self.error,
            "response_body": self.raw_response or {},
        }

    def write_to_file(self, output_dir: Path) -> None:
        assert output_dir, "Output directory is required."
        assert output_dir.is_dir(), f"Output directory is not a directory ({output_dir})."

        response_result = self.raw_result
        if self.is_completed():
            # Tries to convert the JSON result to Python object...
            try:
                from stkai.rqc._handlers import JsonResultHandler
                response_result = JsonResultHandler().handle_result(
                    context=RqcResultContext(request=self.request, raw_result=response_result)
                )
            except json.JSONDecodeError:
                # ... otherwise uses it as-is.
                pass
        else:
            response_result = self.error_with_details()

        save_json_file(
            data=response_result,
            file_path=output_dir / f"{self.execution_id}-response-{self.status}.json"
        )


# ======================
# Result Handler
# ======================

@dataclass(frozen=True)
class RqcResultContext:
    """Context passed to result handlers during processing."""
    request: RqcRequest
    raw_result: Any
    handled: bool = False

    def __post_init__(self) -> None:
        assert self.request, "RQC-Request can not be empty."
        assert self.request.execution_id, "RQC-Request's execution_id can not be empty."
        assert self.handled is not None, "Context's handled flag can not be None."

    @property
    def execution_id(self) -> str:
        assert self.request.execution_id, "Execution ID is expected to exist at this point."
        return self.request.execution_id


class RqcResultHandler(ABC):
    """Abstract base class for result handlers."""

    @abstractmethod
    def handle_result(self, context: RqcResultContext) -> Any:
        """Process the result and return the transformed value."""
        pass


# ======================
# HTTP Client
# ======================

class RqcHttpClient(ABC):
    """Abstract base class for RQC HTTP clients."""

    @abstractmethod
    def get_with_authorization(self, execution_id: str, timeout: int = 30) -> requests.Response:
        """Execute an authorized GET request to retrieve execution status."""
        pass

    @abstractmethod
    def post_with_authorization(self, slug_name: str, data: dict[str, Any] | None = None, timeout: int = 20) -> requests.Response:
        """Execute an authorized POST request to create an execution."""
        pass


# ======================
# Errors and exceptions
# ======================

class MaxRetriesExceededError(RuntimeError):
    """Raised when the maximum number of retries is exceeded."""

    def __init__(self, message: str, last_exception: Exception | None = None):
        super().__init__(message)
        self.last_exception = last_exception


class RqcResultHandlerError(RuntimeError):
    """Raised when the result handler fails to process the result."""

    def __init__(self, message: str, cause: Exception | None = None, result_handler: "RqcResultHandler | None" = None):
        super().__init__(message)
        self.cause = cause
        self.result_handler = result_handler


class ExecutionIdIsMissingError(RuntimeError):
    """Raised when the execution ID is missing or not provided."""

    def __init__(self, message: str):
        super().__init__(message)


# ======================
# Client
# ======================

class RemoteQuickCommand:
    """
    Synchronous client for executing Remote QuickCommands (RQC)
    with built-in polling, retries, and thread-based concurrency.
    """

    def __init__(
        self,
        slug_name: str,
        poll_interval: float = 10.0,
        poll_max_duration: float = 600.0,  # 10min
        max_workers: int = 8,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        output_dir: Path | None = None,
        http_client: RqcHttpClient | None = None,
    ):
        assert slug_name, "RQC slug_name can not be empty."
        assert poll_interval, "Poll interval (in seconds) can not be empty."
        assert poll_interval > 0, "Poll interval (in seconds) must be greater than 0."
        assert poll_max_duration, "Poll max_duration (in seconds) can not be empty."
        assert poll_max_duration > 0, "Poll max_duration (in seconds) must be greater than 0."
        assert max_workers, "Thread-pool max_workers can not be empty."
        assert max_workers > 0, "Thread-pool max_workers must be greater than 0."
        assert max_retries, "Create-execution max_retries can not be empty."
        assert max_retries > 0, "Create-execution max_retries must be greater than 0."
        assert backoff_factor, "Create-execution backoff_factor can not be empty."
        assert backoff_factor > 0, "Create-execution backoff_factor must be greater than 0."

        self.slug_name = slug_name
        self.poll_interval = poll_interval
        self.poll_max_duration = poll_max_duration
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        if not output_dir:
            output_dir = Path(f"output/rqc/{self.slug_name}")
            output_dir.mkdir(parents=True, exist_ok=True)
        if not http_client:
            from stkai.rqc._http import StkCLIRqcHttpClient
            http_client = StkCLIRqcHttpClient()

        self.output_dir: Path = output_dir
        self.http_client: RqcHttpClient = http_client

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

        Each request is executed using `execute()` in parallel threads.
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
        logging.info(f"{'RQC-Batch-Execution'[:26]:<26} | RQC |    ├ slug_name='{self.slug_name}'")
        logging.info(f"{'RQC-Batch-Execution'[:26]:<26} | RQC |    └ output_dir='{self.output_dir}'")

        # Use thread-pool for parallel calls to `execute`
        future_to_index = {
            self.executor.submit(
                self.execute,                     # function ref
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
                    status=RqcResponseStatus.ERROR,
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
        assert request, "🌀 Sanity check | RQC-Request can not be None."
        assert request.id, "🌀 Sanity check | RQC-Request ID can not be None."

        # Try to create the remote execution
        request_id = request.id
        try:
            execution_id = self._create_execution(request=request)
        except Exception as e:
            logging.exception(f"{request_id[:26]:<26} | RQC | ❌ Failed to create execution: {e}")
            return RqcResponse(
                request=request,
                status=RqcResponseStatus.ERROR,
                error=f"Failed to create execution: {e}",
            )
        finally:
            # Logs request payload to disk
            request.write_to_file(output_dir=self.output_dir)

        assert execution_id, "🌀 Sanity check | Execution was created but `execution_id` is missing."
        assert request.execution_id, "🌀 Sanity check | RQC-Request has no `execution_id` registered on it. Was the `request.mark_as_finished()` method called?"

        # Poll for status
        if not result_handler:
            from stkai.rqc._handlers import DEFAULT_RESULT_HANDLER
            result_handler = DEFAULT_RESULT_HANDLER

        response = None
        try:
            response = self._poll_until_done(
                request=request, handler=result_handler
            )
        except Exception as e:
            logging.error(f"{execution_id} | RQC | ❌ Error during polling: {e}")
            response = RqcResponse(
                request=request,
                status=RqcResponseStatus.ERROR,
                error=f"Error during polling: {e}",
            )
        finally:
            # Logs response result or error-details to disk
            if response:
                response.write_to_file(output_dir=self.output_dir)

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
        max_attempts = self.max_retries + 1

        for attempt in range(max_attempts):
            try:
                logging.info(f"{request_id[:26]:<26} | RQC | Sending request to create execution (attempt {attempt + 1}/{max_attempts})...")
                response = self.http_client.post_with_authorization(
                    slug_name=self.slug_name, data=input_data, timeout=30
                )
                assert isinstance(response, requests.Response), \
                    f"🌀 Sanity check | Object returned by `post_with_authorization` method is not an instance of `requests.Response`. ({response.__class__})"

                response.raise_for_status()
                execution_id: str = response.json()
                if not execution_id:
                    raise ExecutionIdIsMissingError("No `execution_id` returned in the create execution response by server.")

                # Registers create execution response on its request
                request.mark_as_finished(execution_id=execution_id)
                logging.info(
                    f"{request_id[:26]:<26} | RQC | ✅ Execution successfully created with Execution ID ({execution_id})."
                )
                return execution_id

            except requests.RequestException as e:
                # Don't retry on 4xx errors
                _response = getattr(e, "response", None)
                if _response is not None and 400 <= _response.status_code < 500:
                    raise
                # Retry up to max_retries
                if attempt < self.max_retries:
                    sleep_time = self.backoff_factor * (2 ** attempt)
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
    ) -> RqcResponse:
        """Polls the status endpoint until the execution reaches a terminal state."""
        assert request, "🌀 Sanity check | RQC-Request not provided to polling phase."
        assert handler, "🌀 Sanity check | Result Handler not provided to polling phase."
        assert request.execution_id, "🌀 Sanity check | Execution ID not provided to polling phase."

        start_time = time.time()
        execution_id = request.execution_id

        retry_created = 0
        max_retry_created = 3
        last_status = "UNKNOWN"

        logging.info(f"{execution_id} | RQC | Starting polling loop...")

        try:
            while True:
                # Gives up after poll max-duration (it prevents infinite loop)
                if time.time() - start_time > self.poll_max_duration:
                    raise TimeoutError(
                        f"Timeout after {self.poll_max_duration} seconds waiting for RQC execution to complete. "
                        f"Last status: `{last_status}`."
                    )

                try:
                    response = self.http_client.get_with_authorization(
                        execution_id=execution_id, timeout=30
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
                    sleep_with_jitter(self.poll_interval)
                    continue

                status = response_data.get('progress', {}).get('status').upper()
                if status != last_status:
                    logging.info(f"{execution_id} | RQC | Current status: {status}")
                    last_status = status

                if status == "COMPLETED":
                    try:
                        logging.info(f"{execution_id} | RQC | Processing the execution result...")
                        raw_result = response_data.get("result")
                        processed_result = handler.handle_result(
                            context=RqcResultContext(request, raw_result)
                        )
                        logging.info(f"{execution_id} | RQC | ✅ Execution finished with status: {status}")
                        return RqcResponse(
                            request=request,
                            status=RqcResponseStatus.COMPLETED,
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

                elif status == "FAILURE":
                    logging.error(
                        f"{execution_id} | RQC | ❌ Execution failed on the server-side with the following response: "
                        f"\n{json.dumps(response_data, indent=2)}"
                    )
                    return RqcResponse(
                        request=request,
                        status=RqcResponseStatus.FAILURE,
                        error="Execution failed on the server-side with status 'FAILURE'. There's no details at all! Try to look at the logs.",
                        raw_response=response_data,
                    )
                elif status == "CREATED":
                    # There's a great chance the StackSpot AI is overloaded and needs some time to recover
                    retry_created += 1
                    backoff_delay = (self.poll_interval * retry_created) * 1.5  # Apply linear-backoff with +50%
                    if retry_created > max_retry_created:
                        raise TimeoutError(
                            "Quick Command execution is possibly stuck on status `CREATED` because the StackSpot AI server is overloaded."
                        )

                    logging.warning(
                        f"{execution_id} | RQC | ⚠️ Retry count for status `CREATED`: {retry_created}/{max_retry_created}. "
                        f"Retrying in {backoff_delay} seconds..."
                    )
                    sleep_with_jitter(backoff_delay)
                else:
                    logging.info(
                        f"{execution_id} | RQC | Execution is still running. Retrying in {int(self.poll_interval)} seconds..."
                    )
                    sleep_with_jitter(self.poll_interval)

        except TimeoutError as e:
            logging.error(f"{execution_id} | RQC | ❌ Polling timed out due to: {e}")
            return RqcResponse(
                request=request,
                status=RqcResponseStatus.TIMEOUT,
                error=str(e),
            )

        # It should never happen
        raise RuntimeError(
            "Unexpected error while polling the status of execution: "
            "reached end of `_poll_until_done` method without returning the execution result."
        )
