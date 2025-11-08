"""
Job scheduler for managing job selection, retries, and scheduling.
"""

from datetime import datetime
from typing import List, Optional

from queuectl.db import get_db_connection
from queuectl.utils import get_logger

logger = get_logger(__name__)


def move_ready_jobs_to_pending() -> int:
    """
    Move jobs from scheduled/retry state to pending if their retry_at time has passed.

    Returns:
        Number of jobs moved to pending.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE jobs
        SET state = 'pending', locked_by = NULL, locked_at = NULL
        WHERE state = 'pending'
        AND retry_at IS NOT NULL
        AND datetime(retry_at) < datetime('now')
    """
    )

    conn.commit()
    count = cursor.rowcount

    if count > 0:
        logger.info(f"Moved {count} jobs from retry to pending.")

    return count


def cleanup_expired_locks(lock_seconds: int = 300) -> int:
    """
    Unlock jobs with expired locks.

    Args:
        lock_seconds: Lock lease duration in seconds.

    Returns:
        Number of locks released.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE jobs
        SET locked_by = NULL, locked_at = NULL, state = 'pending'
        WHERE state = 'processing'
        AND locked_at IS NOT NULL
        AND datetime(locked_at) < datetime('now', '-' || ? || ' seconds')
    """,
        (lock_seconds,),
    )

    conn.commit()
    count = cursor.rowcount

    if count > 0:
        logger.info(f"Released {count} expired locks.")

    return count
