"""
Utility functions for Remote Quick Command module.
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path


def sleep_with_jitter(seconds: float, jitter_factor: float = 0.1) -> None:
    """Sleep for the given duration with random jitter to prevent thundering herd."""
    jitter = random.uniform(-jitter_factor, jitter_factor)
    sleep_time = max(0.0, seconds * (1 + jitter))
    time.sleep(sleep_time)


def save_json_file(data: dict, file_path: Path) -> None:
    """Save data as JSON to the specified file path."""
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
        raise RuntimeError(f"It's not possible to save JSON file in the disk ({file_path.name}: {e}")
