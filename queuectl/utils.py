"""
Utility functions for logging, time handling, and common operations.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Configure logging
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(".queuectl.log", mode="a"),
    ],
)


def get_logger(name: str) -> logging.Logger:
    """Get or create a logger instance."""
    return logging.getLogger(name)


def get_db_path() -> Path:
    """Get the database file path."""
    return Path(".") / "queue.db"


def get_pid_file() -> Path:
    """Get the PID file path."""
    return Path(".") / ".queuectl.pid"


def now_timestamp() -> str:
    """Get current timestamp as ISO string."""
    return datetime.utcnow().isoformat() + "Z"


def calculate_backoff(
    attempts: int,
    base: int = 2,
    max_backoff: int = 300,
) -> int:
    """
    Calculate exponential backoff in seconds.

    Args:
        attempts: Number of attempts made so far.
        base: Base for exponential calculation (default 2).
        max_backoff: Maximum backoff in seconds (default 300).

    Returns:
        Seconds to wait before next retry.
    """
    backoff = base ** attempts
    return min(backoff, max_backoff)


def calculate_retry_at(
    attempts: int,
    base: int = 2,
    max_backoff: int = 300,
) -> str:
    """
    Calculate retry_at timestamp with exponential backoff.

    Args:
        attempts: Current attempt number.
        base: Base for exponential calculation.
        max_backoff: Maximum backoff in seconds.

    Returns:
        ISO timestamp string for next retry.
    """
    from datetime import datetime, timedelta

    backoff_seconds = calculate_backoff(attempts, base, max_backoff)
    retry_at = datetime.utcnow() + timedelta(seconds=backoff_seconds)
    return retry_at.isoformat() + "Z"
