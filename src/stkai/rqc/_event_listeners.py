"""
Event listener implementations for Remote Quick Command.

This module contains concrete implementations of RqcEventListener
for observing RQC execution lifecycle events.

Available Listeners:
    - FileLoggingListener: Persists request/response to JSON files for debugging.

Example:
    >>> from stkai.rqc import RemoteQuickCommand, FileLoggingListener
    >>> listener = FileLoggingListener(Path("./output"))
    >>> rqc = RemoteQuickCommand(slug_name="my-rqc", listeners=[listener])
"""

from pathlib import Path
from typing import Any, override

from stkai.rqc._remote_quick_command import (
    RqcEventListener,
    RqcExecutionStatus,
    RqcRequest,
    RqcResponse,
)


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
            request.write_to_file(output_dir=self.output_dir)

    @override
    def on_after_execute(
        self,
        request: RqcRequest,
        response: RqcResponse,
        context: dict[str, Any],
    ) -> None:
        """Writes response to JSON file after execution completes."""
        response.write_to_file(output_dir=self.output_dir)
