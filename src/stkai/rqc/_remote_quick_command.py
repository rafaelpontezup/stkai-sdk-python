"""
Remote Quick Command (RQC) client for StackSpot AI.

This module provides a synchronous client for executing Remote Quick Commands
with built-in polling, retries, and thread-based concurrency.
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stkai._config import RqcConfig

import requests

from stkai._http import HttpClient
from stkai._retry import Retrying
from stkai._utils import sleep_with_jitter
from stkai.rqc._event_listeners import RqcEventListener
from stkai.rqc._handlers import RqcResultContext, RqcResultHandler
from stkai.rqc._models import RqcExecutionStatus, RqcRequest, RqcResponse

logger = logging.getLogger(__name__)

# ======================
# Options
# ======================

@dataclass(frozen=True)
class CreateExecutionOptions:
    """
    Options for the create-execution phase.

    Controls retry behavior and timeouts when creating a new RQC execution.
    Fields set to None will use values from global config (STKAI.config.rqc).

    Attributes:
        retry_max_retries: Maximum retry attempts for failed create-execution calls.
            Use 0 to disable retries (single attempt only).
            Use 3 for 4 total attempts (1 original + 3 retries).
        retry_initial_delay: Initial delay in seconds for the first retry attempt.
            Subsequent retries use exponential backoff (delay doubles each attempt).
        request_timeout: HTTP request timeout in seconds.
    """
    retry_max_retries: int | None = None
    retry_initial_delay: float | None = None
    request_timeout: int | None = None


@dataclass(frozen=True)
class GetResultOptions:
    """
    Options for the get-result (polling) phase.

    Controls polling behavior and timeouts when waiting for execution completion.
    Fields set to None will use values from global config (STKAI.config.rqc).

    Attributes:
        poll_interval: Seconds to wait between polling status checks.
        poll_max_duration: Maximum seconds to wait before timing out.
        poll_overload_timeout: Maximum seconds to tolerate CREATED status before assuming server overload.
        request_timeout: HTTP request timeout in seconds.
    """
    poll_interval: float | None = None
    poll_max_duration: float | None = None
    poll_overload_timeout: float | None = None
    request_timeout: int | None = None


@dataclass(frozen=True)
class RqcOptions:
    """
    Consolidated configuration options for RemoteQuickCommand.

    Groups all options for RQC execution into a single configuration object.
    Fields set to None will use values from global config (STKAI.config.rqc).

    Attributes:
        create_execution: Options for the create-execution phase.
        get_result: Options for the get-result (polling) phase.
        max_workers: Maximum number of threads for batch execution (execute_many).

    Example:
        >>> # Customize only what you need - rest comes from STKAI.config
        >>> options = RqcOptions(
        ...     create_execution=CreateExecutionOptions(retry_max_retries=5),
        ... )
        >>> rqc = RemoteQuickCommand(slug_name="my-command", options=options)
    """
    create_execution: CreateExecutionOptions | None = None
    get_result: GetResultOptions | None = None
    max_workers: int | None = None

    def with_defaults_from(self, cfg: "RqcConfig") -> "RqcOptions":
        """
        Returns a new RqcOptions with None values filled from config.

        User-provided values take precedence; None values use config defaults.
        This follows the Single Source of Truth principle where STKAI.config
        is the authoritative source for default values.

        Args:
            cfg: The RqcConfig to use for default values.

        Returns:
            A new RqcOptions with all fields resolved (no None values).

        Example:
            >>> options = RqcOptions(
            ...     create_execution=CreateExecutionOptions(retry_max_retries=5),
            ... )
            >>> resolved = options.with_defaults_from(STKAI.config.rqc)
            >>> resolved.create_execution.retry_max_retries  # 5 (user-defined)
            >>> resolved.create_execution.retry_initial_delay  # from config
        """
        ce = self.create_execution or CreateExecutionOptions()
        gr = self.get_result or GetResultOptions()

        return RqcOptions(
            create_execution=CreateExecutionOptions(
                retry_max_retries=ce.retry_max_retries if ce.retry_max_retries is not None else cfg.retry_max_retries,
                retry_initial_delay=ce.retry_initial_delay if ce.retry_initial_delay is not None else cfg.retry_initial_delay,
                request_timeout=ce.request_timeout if ce.request_timeout is not None else cfg.request_timeout,
            ),
            get_result=GetResultOptions(
                poll_interval=gr.poll_interval if gr.poll_interval is not None else cfg.poll_interval,
                poll_max_duration=gr.poll_max_duration if gr.poll_max_duration is not None else cfg.poll_max_duration,
                poll_overload_timeout=gr.poll_overload_timeout if gr.poll_overload_timeout is not None else cfg.poll_overload_timeout,
                request_timeout=gr.request_timeout if gr.request_timeout is not None else cfg.request_timeout,
            ),
            max_workers=self.max_workers if self.max_workers is not None else cfg.max_workers,
        )


# ======================
# Errors and exceptions
# ======================

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
        base_url: The base URL for the StackSpot AI API.
        options: Consolidated configuration options (resolved with defaults from config).
        http_client: HTTP client for API calls (default: EnvironmentAwareHttpClient).
        listeners: List of event listeners for observing execution lifecycle.
    """

    def __init__(
        self,
        slug_name: str,
        base_url: str | None = None,
        options: RqcOptions | None = None,
        http_client: HttpClient | None = None,
        listeners: list[RqcEventListener] | None = None,
    ):
        """
        Initialize the RemoteQuickCommand client.

        By default, a FileLoggingListener is registered to persist request/response
        to JSON files in `output/rqc/{slug_name}/`. Pass `listeners=[]` to disable
        this behavior, or provide your own list of listeners.

        Args:
            slug_name: The Quick Command slug name (identifier) to execute.
            base_url: Base URL for the StackSpot AI API.
                If None, uses global config (STKAI.config.rqc.base_url).
            options: Configuration options for execution behavior.
                If None, uses defaults from global config (STKAI.config.rqc).
                Partial options are merged with config defaults via with_defaults_from().
            http_client: Custom HTTP client implementation for API calls.
                If None, uses EnvironmentAwareHttpClient (auto-detects CLI or standalone).
            listeners: Event listeners for observing execution lifecycle.
                If None (default), registers a FileLoggingListener.
                If [] (empty list), disables default logging.

        Raises:
            AssertionError: If any required parameter is invalid.
        """
        # Get global config for defaults
        from stkai._config import STKAI
        cfg = STKAI.config.rqc

        # Resolve options with defaults from config (Single Source of Truth)
        resolved_options = (options or RqcOptions()).with_defaults_from(cfg)

        # Resolve base_url
        if base_url is None:
            base_url = cfg.base_url

        if not http_client:
            from stkai._http import EnvironmentAwareHttpClient
            http_client = EnvironmentAwareHttpClient()

        # Setup default FileLoggingListener when no listeners are specified (None).
        # To disable logging, pass an empty list: `listeners=[]`
        if listeners is None:
            from stkai.rqc._event_listeners import FileLoggingListener
            listeners = [
                FileLoggingListener(output_dir=f"output/rqc/{slug_name}")
            ]

        assert slug_name, "RQC slug_name can not be empty."
        assert base_url, "RQC base_url can not be empty."
        assert resolved_options.max_workers is not None, "Thread-pool max_workers can not be empty."
        assert resolved_options.max_workers > 0, "Thread-pool max_workers must be greater than 0."
        assert http_client is not None, "RQC http_client can not be None."
        assert listeners is not None, "RQC listeners can not be None."

        self.slug_name = slug_name
        self.base_url = base_url.rstrip("/")
        self.options = resolved_options
        self.max_workers = resolved_options.max_workers
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self.http_client: HttpClient = http_client
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

        logger.info(
            f"{'RQC-Batch-Execution'[:26]:<26} | RQC | "
            f"🛜 Starting batch execution of {len(request_list)} requests."
        )
        logger.info(f"{'RQC-Batch-Execution'[:26]:<26} | RQC |    ├ base_url={self.base_url}")
        logger.info(f"{'RQC-Batch-Execution'[:26]:<26} | RQC |    ├ slug_name='{self.slug_name}'")
        logger.info(f"{'RQC-Batch-Execution'[:26]:<26} | RQC |    └ max_concurrent={self.max_workers}")

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
                logger.error(
                    f"{correlated_request.id[:26]:<26} | RQC | ❌ Execution failed in batch(seq={idx}). {e}",
                    exc_info=logger.isEnabledFor(logging.DEBUG)
                )
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

        logger.info(
            f"{'RQC-Batch-Execution'[:26]:<26} | RQC | 🛜 Batch execution finished."
        )
        logger.info(f"{'RQC-Batch-Execution'[:26]:<26} | RQC |    ├ total of responses = {len(responses)}")

        from collections import Counter
        totals_per_status = Counter(r.status for r in responses)
        items = totals_per_status.items()
        for idx, (status, total) in enumerate(items):
            icon = "└" if idx == (len(items) - 1) else "├"
            logger.info(f"{'RQC-Batch-Execution'[:26]:<26} | RQC |    {icon} total of responses with status {status:<9} = {total}")

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
        logger.info(f"{request.id[:26]:<26} | RQC | 🛜 Starting execution of a single request.")
        logger.info(f"{request.id[:26]:<26} | RQC |    ├ base_url={self.base_url}")
        logger.info(f"{request.id[:26]:<26} | RQC |    └ slug_name='{self.slug_name}'")

        response = self._execute_workflow(
            request=request, result_handler=result_handler
        )

        logger.info(
            f"{request.id[:26]:<26} | RQC | 🛜 Execution finished."
        )
        if response.is_completed():
            logger.info(f"{request.id[:26]:<26} | RQC |    └ with status = {response.status}")
        else:
            logger.info(f"{request.id[:26]:<26} | RQC |    ├ with status = {response.status}")
            logger.info(f"{request.id[:26]:<26} | RQC |    └ with error message = \"{response.error}\"")

        assert response.request is request, \
            "🌀 Sanity check | Unexpected mismatch: response does not reference its corresponding request."
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
        self._notify_listeners(
            "on_before_execute",
            request=request, context=event_context
        )

        response = None
        try:
            # Phase-1: Create execution
            execution_id, error_response = self._create_execution(request=request, context=event_context)
            if error_response:
                response = error_response
                return response

            # Sanity checks after Phase-1
            assert execution_id, "🌀 Sanity check | Execution was created but `execution_id` is missing."
            assert request.execution_id, "🌀 Sanity check | RQC-Request has no `execution_id` registered on it. Was the `request.mark_as_submitted()` method called?"
            assert execution_id == request.execution_id, "🌀 Sanity check | RQC-Request's `execution_id` and response's `execution_id` are different."

            # Phase-2: Poll
            if not result_handler:
                from stkai.rqc._handlers import DEFAULT_RESULT_HANDLER
                result_handler = DEFAULT_RESULT_HANDLER

            response = self._poll_until_done(
                request=request, handler=result_handler, context=event_context
            )

            # Sanity check after Phase-2
            assert response, "🌀 Sanity check | RQC-Response was not created during the polling phase."
            return response
        finally:
            # Single point of notification: on_after_execute (always called)
            self._notify_listeners(
                "on_after_execute",
                request=request, response=response, context=event_context
            )

    # ======================
    # Internals
    # ======================

    def _create_execution(
        self,
        request: RqcRequest,
        context: dict[str, Any],
    ) -> tuple[str | None, RqcResponse | None]:
        """
        Creates an RQC execution via POST with retries and exponential backoff.

        This method follows the same pattern as `_poll_until_done()`: it receives
        the event context, dispatches status change events, and encapsulates
        exceptions into an error response.

        Args:
            request: The RqcRequest instance to create execution for.
            context: Shared event context for listeners.

        Returns:
            (execution_id, None) on success - execution was created
            (None, error_response) on failure - contains error details
        """
        assert request, "🌀 Sanity check | RQC-Request not provided to create-execution phase."
        assert context is not None, "🌀 Sanity check | Event context not provided to create-execution phase."

        # Get options and assert for type narrowing
        opts = self.options.create_execution
        assert opts is not None, "create_execution options must be set after with_defaults_from()"
        assert opts.retry_max_retries is not None, "retry_max_retries must be set after with_defaults_from()"
        assert opts.retry_initial_delay is not None, "retry_initial_delay must be set after with_defaults_from()"
        assert opts.request_timeout is not None, "request_timeout must be set after with_defaults_from()"

        request_id = request.id
        input_data = request.to_input_data()

        # Build full URL using base_url
        url = f"{self.base_url}/v1/quick-commands/create-execution/{self.slug_name}"

        try:
            for attempt in Retrying(
                max_retries=opts.retry_max_retries,
                initial_delay=opts.retry_initial_delay,
                logger_prefix=f"{request_id[:26]:<26} | RQC",
            ):
                with attempt:
                    logger.info(
                        f"{request_id[:26]:<26} | RQC | "
                        f"Sending request to create execution (attempt {attempt.attempt_number}/{attempt.max_attempts})..."
                    )
                    response = self.http_client.post(
                        url=url, data=input_data, timeout=opts.request_timeout
                    )
                    assert isinstance(response, requests.Response), \
                        f"🌀 Sanity check | Object returned by `post` method is not an instance of `requests.Response`. ({response.__class__})"

                    response.raise_for_status()
                    execution_id: str = response.json()
                    if not execution_id:
                        raise ExecutionIdIsMissingError("No `execution_id` returned in the create execution response by server.")

                    # Registers create execution response on its request
                    request.mark_as_submitted(execution_id=execution_id)
                    logger.info(
                        f"{request_id[:26]:<26} | RQC | ✅ Execution successfully created ({execution_id})"
                    )

                    # Notify status change: PENDING → CREATED (execution created successfully)
                    self._notify_listeners(
                        "on_status_change",
                        request=request,
                        old_status=RqcExecutionStatus.PENDING,
                        new_status=RqcExecutionStatus.CREATED,
                        context=context,
                    )
                    return (execution_id, None)

            # Should never reach here - Retrying raises MaxRetriesExceededError
            raise RuntimeError(
                "Unexpected error while creating execution: "
                "reached end of `_create_execution` method without returning the execution ID."
            )

        except Exception as e:
            error_status = RqcExecutionStatus.from_exception(e)
            error_msg = f"Failed to create execution: {e}"
            if isinstance(e, requests.HTTPError) and e.response is not None:
                error_msg = f"Failed to create execution due to an HTTP error {e.response.status_code}: {e.response.text}"
            logger.error(
                f"{request_id[:26]:<26} | RQC | ❌ {error_msg}",
                exc_info=logger.isEnabledFor(logging.DEBUG)
            )

            # Notify status change: PENDING → ERROR or TIMEOUT
            self._notify_listeners(
                "on_status_change",
                request=request,
                old_status=RqcExecutionStatus.PENDING,
                new_status=error_status,
                context=context,
            )

            error_response = RqcResponse(
                request=request,
                status=error_status,
                error=error_msg,
            )
            return (None, error_response)

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

        # Get options and assert for type narrowing
        opts = self.options.get_result
        assert opts is not None, "get_result options must be set after with_defaults_from()"
        assert opts.poll_interval is not None, "poll_interval must be set after with_defaults_from()"
        assert opts.poll_max_duration is not None, "poll_max_duration must be set after with_defaults_from()"
        assert opts.poll_overload_timeout is not None, "poll_overload_timeout must be set after with_defaults_from()"
        assert opts.request_timeout is not None, "request_timeout must be set after with_defaults_from()"

        start_time = time.time()
        execution_id = request.execution_id

        last_status: RqcExecutionStatus = RqcExecutionStatus.CREATED  # Starts at CREATED since we notify PENDING → CREATED before polling
        created_since: float | None = None

        logger.info(f"{execution_id} | RQC | Starting polling loop...")

        try:
            while True:
                # Gives up after poll max-duration (it prevents infinite loop)
                if time.time() - start_time > opts.poll_max_duration:
                    raise TimeoutError(
                        f"Timeout after {opts.poll_max_duration} seconds waiting for RQC execution to complete. "
                        f"Last status: `{last_status}`."
                    )

                try:
                    # Build full URL using base_url and prevents client-side caching
                    import uuid
                    nocache_param = str(uuid.uuid4())
                    url = f"{self.base_url}/v1/quick-commands/callback/{execution_id}?nocache={nocache_param}"
                    nocache_headers = {
                        "Cache-Control": "no-cache, no-store",
                        "Pragma": "no-cache",
                    }

                    response = self.http_client.get(
                        url=url, headers=nocache_headers, timeout=opts.request_timeout
                    )
                    assert isinstance(response, requests.Response), \
                        f"🌀 Sanity check | Object returned by `get` method is not an instance of `requests.Response`. ({response.__class__})"

                    response.raise_for_status()
                    response_data = response.json()
                except requests.RequestException as e:
                    # Don't retry on 4xx errors
                    _response = getattr(e, "response", None)
                    if _response is not None and 400 <= _response.status_code < 500:
                        raise
                    # Sleeps a little bit before trying again
                    logger.warning(
                        f"{execution_id} | RQC | ⚠️ Temporary polling failure: {e}"
                    )
                    sleep_with_jitter(opts.poll_interval)
                    continue

                status = RqcExecutionStatus(
                    response_data.get('progress', {}).get('status').upper()
                )
                if status != last_status:
                    logger.info(f"{execution_id} | RQC | Current status: {status}")
                    # Notify listeners: status change
                    self._notify_listeners(
                        "on_status_change", request=request,
                        old_status=last_status, new_status=status, context=context
                    )
                    last_status = status

                if status == RqcExecutionStatus.COMPLETED:
                    try:
                        logger.info(f"{execution_id} | RQC | Processing the execution result...")
                        raw_result = response_data.get("result")
                        processed_result = handler.handle_result(
                            context=RqcResultContext(request, raw_result)
                        )
                        logger.info(f"{execution_id} | RQC | ✅ Execution finished with status: {status}")
                        return RqcResponse(
                            request=request,
                            status=RqcExecutionStatus.COMPLETED,
                            result=processed_result,
                            raw_response=response_data
                        )
                    except Exception as e:
                        handler_name = handler.__class__.__name__
                        logger.error(
                            f"{execution_id} | RQC | ❌ It's not possible to handle the result (handler={handler_name}).",
                        )
                        raise RqcResultHandlerError(
                            cause=e,
                            result_handler=handler,
                            message=f"Error while processing the response in the result handler ({handler_name}): {e}",
                        ) from e

                elif status == RqcExecutionStatus.FAILURE:
                    logger.error(
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
                    if elapsed_in_created > opts.poll_overload_timeout:
                        raise TimeoutError(
                            f"Execution stuck in CREATED status for {elapsed_in_created:.2f}s. "
                            f"The server may be overloaded (queue backpressure)."
                        )

                    logger.warning(
                        f"{execution_id} | RQC | ⚠️ Execution is still in CREATED status "
                        f"({elapsed_in_created:.2f}s/{opts.poll_overload_timeout}s). Possible server overload..."
                    )
                    sleep_with_jitter(opts.poll_interval)
                else:
                    logger.info(
                        f"{execution_id} | RQC | Execution is still running. Retrying in {int(opts.poll_interval)} seconds..."
                    )
                    sleep_with_jitter(opts.poll_interval)

        except Exception as e:
            # Catch-all for TimeoutError, HTTPError 4xx, RqcResultHandlerError, etc.
            error_status = RqcExecutionStatus.from_exception(e)
            error_msg = f"Error during polling: {e}"
            if isinstance(e, requests.HTTPError) and e.response is not None:
                error_msg = f"Error during polling due to an HTTP error {e.response.status_code}: {e.response.text}"
            logger.error(
                f"{execution_id} | RQC | ❌ {error_msg}",
                exc_info=logger.isEnabledFor(logging.DEBUG)
            )
            # Notify status change: last_status → ERROR/TIMEOUT
            self._notify_listeners(
                "on_status_change",
                request=request,
                old_status=last_status,
                new_status=error_status,
                context=context,
            )
            return RqcResponse(
                request=request,
                status=error_status,
                error=error_msg,
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
                logger.warning(
                    f"{tracking_id[:26]:<26} | RQC | Event listener `{listener_name}.{event}()` raised an exception: {e}"
                )
