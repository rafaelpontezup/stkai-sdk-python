"""
Utility functions for Remote Quick Command module.

This module provides internal helper functions used throughout the RQC client.
These functions are not part of the public API and may change without notice.
"""

import json
import logging
import random
import time
from pathlib import Path
from typing import Any


def sleep_with_jitter(seconds: float, jitter_factor: float = 0.1) -> None:
    """
    Sleep for the given duration with random jitter.

    Adds random variation to sleep duration to prevent thundering herd
    problems when multiple clients poll simultaneously.

    Args:
        seconds: Base sleep duration in seconds.
        jitter_factor: Maximum percentage variation (default: 10%).
            For example, 0.1 means sleep time varies by +/- 10%.

    Example:
        >>> sleep_with_jitter(10.0)  # Sleeps between 9.0 and 11.0 seconds
        >>> sleep_with_jitter(10.0, jitter_factor=0.2)  # Sleeps between 8.0 and 12.0 seconds
    """
    jitter = random.uniform(-jitter_factor, jitter_factor)
    sleep_time = max(0.0, seconds * (1 + jitter))
    time.sleep(sleep_time)


def save_json_file(data: dict[str, Any], file_path: Path) -> None:
    """
    Save data as JSON to the specified file path.

    Writes a Python dict to disk as formatted JSON with UTF-8 encoding.
    Non-serializable values are converted to strings using the default=str option.

    Args:
        data: Dictionary to serialize as JSON.
        file_path: Destination path for the JSON file.

    Raises:
        RuntimeError: If the file cannot be written (wraps the original exception).

    Example:
        >>> save_json_file({"key": "value"}, Path("output/data.json"))
    """
    try:
        with file_path.open(mode="w", encoding="utf-8") as file:
            json.dump(
                data, file,
                indent=4, ensure_ascii=False, default=str
            )
    except Exception as e:
        logging.exception(
            f"❌ It's not possible to save JSON file in the disk ({file_path.name}: {e}"
        )
        raise RuntimeError(f"It's not possible to save JSON file in the disk ({file_path.name}: {e}") from e
