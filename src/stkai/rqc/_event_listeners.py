"""
Event listeners for Remote Quick Command.

This module contains the RqcEventListener base class and concrete implementations
for observing RQC execution lifecycle events.

Available Listeners:
    - RqcEventListener: Base class for all event listeners.
    - RqcPhasedEventListener: Abstract listener with granular phase-specific hooks.
    - FileLoggingListener: Persists request/response to JSON files for debugging.

Internal:
    - RqcEventNotifier: Type-safe dispatcher that notifies registered listeners.

Example:
    >>> from stkai.rqc import RemoteQuickCommand, FileLoggingListener
    >>> listener = FileLoggingListener(Path("./output"))
    >>> rqc = RemoteQuickCommand(slug_name="my-rqc", listeners=[listener])
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, override

from stkai.rqc._models import (
    RqcExecutionStatus,
    RqcRequest,
    RqcResponse,
)


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

    def on_before_execute(self, request: RqcRequest, context: dict[str, Any]) -> None:
        """
        Called before starting the execution.

        Args:
            request: The request about to be executed.
            context: Mutable dict for sharing state between listener calls.
        """
        pass

    def on_status_change(
        self,
        request: RqcRequest,
        old_status: RqcExecutionStatus,
        new_status: RqcExecutionStatus,
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
        request: RqcRequest,
        response: RqcResponse,
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


class RqcPhasedEventListener(RqcEventListener):
    """
    Abstract listener that exposes granular hooks for each execution phase.

    This class implements the base RqcEventListener methods and delegates
    to phase-specific methods, making it easier to implement listeners
    focused on specific phases of the execution lifecycle.

    Phase 1 - Create Execution:
        - on_create_execution_start: Before POST to create execution
        - on_create_execution_end: After creation (success or failure)

    Phase 2 - Get Result (Polling):
        - on_get_result_start: Before polling loop starts
        - on_get_result_end: After polling completes (any terminal status)

    Example:
        >>> class MetricsListener(RqcPhasedEventListener):
        ...     def on_create_execution_start(self, request, context):
        ...         context['create_start'] = time.time()
        ...
        ...     def on_create_execution_end(self, request, status, response, context):
        ...         duration = time.time() - context['create_start']
        ...         if status == RqcExecutionStatus.CREATED:
        ...             statsd.timing('rqc.create.success', duration)
        ...         else:
        ...             statsd.timing('rqc.create.failure', duration)
    """

    # ==================
    # Phase 1: Create Execution
    # ==================

    def on_create_execution_start(
        self,
        request: RqcRequest,
        context: dict[str, Any],
    ) -> None:
        """
        Called before attempting to create the execution on the server.

        Args:
            request: The request about to be submitted.
            context: Mutable dict for sharing state between listener calls.
        """
        pass

    def on_create_execution_end(
        self,
        request: RqcRequest,
        status: RqcExecutionStatus,
        response: RqcResponse | None,
        context: dict[str, Any],
    ) -> None:
        """
        Called after the create-execution phase completes (success or failure).

        Args:
            request: The request that was submitted.
            status: The resulting status (CREATED on success, ERROR/TIMEOUT on failure).
            response: The RqcResponse if creation failed (contains error details),
                      None if creation succeeded (polling will start).
            context: Mutable dict for sharing state between listener calls.
        """
        pass

    # ==================
    # Phase 2: Get Result (Polling)
    # ==================

    def on_get_result_start(
        self,
        request: RqcRequest,
        context: dict[str, Any],
    ) -> None:
        """
        Called before starting the polling loop.

        Only called if create-execution succeeded (request.execution_id is set).

        Args:
            request: The request with execution_id already assigned.
            context: Mutable dict for sharing state between listener calls.
        """
        pass

    def on_get_result_end(
        self,
        request: RqcRequest,
        response: RqcResponse,
        context: dict[str, Any],
    ) -> None:
        """
        Called after the polling phase completes (any terminal status).

        Args:
            request: The executed request.
            response: The final response (COMPLETED, FAILURE, ERROR, or TIMEOUT).
            context: Mutable dict for sharing state between listener calls.
        """
        pass

    # ==================
    # Base method implementations (delegation logic)
    # ==================

    @override
    def on_before_execute(
        self,
        request: RqcRequest,
        context: dict[str, Any],
    ) -> None:
        """Delegates to on_create_execution_start."""
        self.on_create_execution_start(request, context)

    @override
    def on_status_change(
        self,
        request: RqcRequest,
        old_status: RqcExecutionStatus,
        new_status: RqcExecutionStatus,
        context: dict[str, Any],
    ) -> None:
        """
        Delegates to phase-specific methods based on status transitions.

        - PENDING → CREATED: Calls on_create_execution_end (success) + on_get_result_start
        - PENDING → ERROR/TIMEOUT: Handled in on_after_execute (failure case)
        """
        # Create-execution succeeded, polling is about to start
        if old_status == RqcExecutionStatus.PENDING and new_status == RqcExecutionStatus.CREATED:
            self.on_create_execution_end(request, new_status, None, context)
            self.on_get_result_start(request, context)

    @override
    def on_after_execute(
        self,
        request: RqcRequest,
        response: RqcResponse,
        context: dict[str, Any],
    ) -> None:
        """
        Delegates to phase-specific methods based on execution outcome.

        - No execution_id: Create-execution failed → on_create_execution_end
        - Has execution_id: Polling finished → on_get_result_end
        """
        if response.execution_id is None:
            # Failed during create-execution phase
            self.on_create_execution_end(request, response.status, response, context)
        else:
            # Polling phase completed
            self.on_get_result_end(request, response, context)


class FileLoggingListener(RqcEventListener):
    """
    Listener that persists request and response to JSON files for debugging.

    This listener writes files to the specified output directory:
    - `{tracking_id}-request.json`: The request payload
    - `{tracking_id}-response-{status}.json`: The response result or error details

    Example:
        >>> listener = FileLoggingListener(Path("./output/rqc"))
        >>> rqc = RemoteQuickCommand(slug_name="my-rqc", listeners=[listener])
    """

    def __init__(self, output_dir: Path | str):
        """
        Initialize the listener with an output directory.

        Args:
            output_dir: Directory where JSON files will be saved (Path or str).
                       Created automatically if it doesn't exist.
        """
        assert output_dir, "Output directory is required."

        self.output_dir: Path = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)


    @override
    def on_status_change(
        self,
        request: RqcRequest,
        old_status: RqcExecutionStatus,
        new_status: RqcExecutionStatus,
        context: dict[str, Any],
    ) -> None:
        """Writes request file when status transitions from PENDING (for debugging)."""
        if old_status == RqcExecutionStatus.PENDING:
            request.write_to_file(output_dir=self.output_dir, tracking_id=context.get("execution_id"))

    @override
    def on_after_execute(
        self,
        request: RqcRequest,
        response: RqcResponse,
        context: dict[str, Any],
    ) -> None:
        """Writes response to JSON file after execution completes."""
        response.write_to_file(output_dir=self.output_dir)


# ======================
# Internal: Event Notifier
# ======================

logger = logging.getLogger(__name__)


class RqcEventNotifier:
    """
    Type-safe dispatcher that notifies registered listeners about RQC execution lifecycle events.

    Internal class — not exported from the package.
    """

    def __init__(self, listeners: list[RqcEventListener]):
        assert listeners is not None, "Listeners list cannot be None."
        self.listeners = listeners

    def notify_before_execute(self, request: RqcRequest, context: dict[str, Any]) -> None:
        """Notifies all listeners that an execution is about to start."""
        assert request, "request cannot be None."
        assert context is not None, "context cannot be None."
        self._safe_dispatch(request, context, "on_before_execute",
            lambda listener: listener.on_before_execute(request=request, context=context))

    def notify_status_change(
        self,
        request: RqcRequest,
        old_status: RqcExecutionStatus,
        new_status: RqcExecutionStatus,
        context: dict[str, Any],
    ) -> None:
        """Notifies all listeners that the execution status has changed."""
        assert request, "request cannot be None."
        assert context is not None, "context cannot be None."
        assert old_status, "old_status cannot be empty."
        assert new_status, "new_status cannot be empty."
        self._safe_dispatch(request, context, "on_status_change",
            lambda listener: listener.on_status_change(
                request=request,
                old_status=old_status,
                new_status=new_status,
                context=context
            )
        )

    def notify_after_execute(
        self,
        request: RqcRequest,
        response: RqcResponse,
        context: dict[str, Any],
    ) -> None:
        """Notifies all listeners that the execution has completed (success or failure)."""
        assert request, "request cannot be None."
        assert context is not None, "context cannot be None."
        assert response, "response cannot be None."
        self._safe_dispatch(request, context, "on_after_execute",
            lambda listener: listener.on_after_execute(
                request=request, response=response, context=context
            )
        )

    def _safe_dispatch(
        self,
        request: RqcRequest,
        context: dict[str, Any],
        event_name: str,
        action: Callable[[RqcEventListener], None],
    ) -> None:
        """Invokes action on each listener, logging and swallowing any exceptions."""
        tracking_id = context.get("execution_id") or request.id
        for listener in self.listeners:
            try:
                action(listener)
            except Exception as e:
                listener_name = listener.__class__.__name__
                logger.warning(
                    f"{tracking_id[:26]:<26} | RQC | Event listener "
                    f"`{listener_name}.{event_name}()` raised an exception: {e}"
                )
