"""
Database initialization, schema, and helper functions using SQLite.
"""

import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from queuectl.utils import get_db_path, get_logger

logger = get_logger(__name__)

# Thread-local storage for database connections
_thread_local = threading.local()


def get_db_connection() -> sqlite3.Connection:
    """
    Get a thread-safe database connection.
    Each thread gets its own connection.
    """
    if not hasattr(_thread_local, "connection") or _thread_local.connection is None:
        db_path = get_db_path()
        _thread_local.connection = sqlite3.connect(str(db_path), check_same_thread=False)
        _thread_local.connection.row_factory = sqlite3.Row
        # Enable foreign keys
        _thread_local.connection.execute("PRAGMA foreign_keys = ON")
    return _thread_local.connection


def close_db_connection() -> None:
    """Close the thread-local database connection."""
    if hasattr(_thread_local, "connection") and _thread_local.connection:
        _thread_local.connection.close()
        _thread_local.connection = None


def init_db() -> None:
    """Initialize the database schema."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create jobs table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            retry_at TEXT,
            run_at TEXT,
            priority INTEGER DEFAULT 0,
            locked_by INTEGER,
            locked_at TEXT,
            last_error TEXT,
            output_path TEXT,
            stdout_log TEXT,
            stderr_log TEXT,
            exit_code INTEGER,
            completed_at TEXT,
            CHECK (state IN ('pending', 'processing', 'completed', 'failed', 'dead')),
            CHECK (priority >= 0 AND priority <= 10)
        )
    """
    )

    # Create dlq (Dead Letter Queue) table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dlq (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            moved_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            payload TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
    """
    )

    # Create config table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """
    )

    conn.commit()
    logger.info("Database schema initialized.")


def insert_job(
    job_id: str,
    command: str,
    max_retries: int = 3,
    priority: int = 0,
    run_at: Optional[str] = None,
) -> None:
    """
    Insert a new job into the database.

    Args:
        job_id: Unique job identifier.
        command: Command to execute.
        max_retries: Maximum number of retries.
        priority: Job priority (0-10, higher = more urgent). Default: 0
        run_at: ISO timestamp for scheduled execution. If None, job runs immediately.
    """
    from queuectl.utils import now_timestamp

    conn = get_db_connection()
    cursor = conn.cursor()

    now = now_timestamp()
    cursor.execute(
        """
        INSERT INTO jobs (
            id, command, state, attempts, max_retries, created_at, updated_at, priority, run_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (job_id, command, "pending", 0, max_retries, now, now, priority, run_at),
    )

    conn.commit()
    logger.info(f"Job {job_id} enqueued (priority={priority}, run_at={run_at}).")


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get a job by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def list_jobs(state: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """List jobs, optionally filtered by state."""
    conn = get_db_connection()
    cursor = conn.cursor()

    if state:
        cursor.execute(
            "SELECT * FROM jobs WHERE state = ? ORDER BY created_at DESC LIMIT ?",
            (state, limit),
        )
    else:
        cursor.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )

    return [dict(row) for row in cursor.fetchall()]


def update_job_state(job_id: str, state: str) -> None:
    """Update job state."""
    from queuectl.utils import now_timestamp

    conn = get_db_connection()
    cursor = conn.cursor()
    now = now_timestamp()
    cursor.execute(
        "UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?",
        (state, now, job_id),
    )
    conn.commit()


def increment_job_attempts(job_id: str) -> None:
    """Increment job attempt count."""
    from queuectl.utils import now_timestamp

    conn = get_db_connection()
    cursor = conn.cursor()
    now = now_timestamp()
    cursor.execute(
        "UPDATE jobs SET attempts = attempts + 1, updated_at = ? WHERE id = ?",
        (now, job_id),
    )
    conn.commit()


def update_job_error(job_id: str, error: str) -> None:
    """Update job last error."""
    from queuectl.utils import now_timestamp

    conn = get_db_connection()
    cursor = conn.cursor()
    now = now_timestamp()
    cursor.execute(
        "UPDATE jobs SET last_error = ?, updated_at = ? WHERE id = ?",
        (error, now, job_id),
    )
    conn.commit()


def set_job_retry_at(job_id: str, retry_at: str) -> None:
    """Set the next retry time for a job."""
    from queuectl.utils import now_timestamp

    conn = get_db_connection()
    cursor = conn.cursor()
    now = now_timestamp()
    cursor.execute(
        "UPDATE jobs SET retry_at = ?, updated_at = ? WHERE id = ?",
        (retry_at, now, job_id),
    )
    conn.commit()


def lock_job(job_id: str, worker_pid: int, lock_seconds: int = 300) -> bool:
    """
    Attempt to acquire a lock on a job.
    Returns True if lock acquired, False otherwise.
    """
    from datetime import datetime, timedelta

    from queuectl.utils import now_timestamp

    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch current lock
    cursor.execute(
        "SELECT locked_by, locked_at FROM jobs WHERE id = ? AND state = 'pending'",
        (job_id,),
    )
    row = cursor.fetchone()

    if not row:
        return False

    locked_by, locked_at = row

    # If not locked, acquire lock
    if locked_by is None:
        now = now_timestamp()
        cursor.execute(
            """
            UPDATE jobs
            SET locked_by = ?, locked_at = ?, state = 'processing', updated_at = ?
            WHERE id = ? AND locked_by IS NULL
        """,
            (worker_pid, now, now, job_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    # If locked, check if lock expired
    if locked_at:
        lock_time = datetime.fromisoformat(locked_at.replace("Z", "+00:00"))
        now = datetime.utcnow().replace(tzinfo=lock_time.tzinfo)
        if (now - lock_time).total_seconds() > lock_seconds:
            # Lock expired, acquire it
            now_str = now_timestamp()
            cursor.execute(
                """
                UPDATE jobs
                SET locked_by = ?, locked_at = ?, updated_at = ?
                WHERE id = ? AND locked_by = ?
            """,
                (worker_pid, now_str, now_str, job_id, locked_by),
            )
            conn.commit()
            return cursor.rowcount > 0

    return False


def unlock_job(job_id: str) -> None:
    """Release lock on a job (but keep state)."""
    from queuectl.utils import now_timestamp

    conn = get_db_connection()
    cursor = conn.cursor()
    now = now_timestamp()
    cursor.execute(
        "UPDATE jobs SET locked_by = NULL, locked_at = NULL, updated_at = ? WHERE id = ?",
        (now, job_id),
    )
    conn.commit()


def pick_pending_job(worker_pid: int, lock_seconds: int = 300) -> Optional[Dict[str, Any]]:
    """
    Atomically pick and lock a pending job for processing.
    
    Scheduling logic:
    - Jobs WITH priority (priority > 0): Picked by priority DESC, then creation order
    - Jobs WITHOUT priority (priority = 0): Picked by creation order (FIFO)
    - Within same priority level: FIFO (oldest first)

    Args:
        worker_pid: PID of the worker.
        lock_seconds: Lock lease duration.

    Returns:
        Job dict if found, None otherwise.
    """
    from queuectl.config import Config
    from queuectl.utils import now_timestamp

    conn = get_db_connection()
    cursor = conn.cursor()

    # Try to find and lock a job in a transaction
    try:
        cursor.execute("BEGIN IMMEDIATE")

        # Smart scheduling: 
        # 1. First pick any high-priority jobs (priority > 0), ordered by priority DESC
        # 2. Then pick regular FIFO jobs (priority = 0), ordered by creation time
        # This allows urgent jobs to jump the queue while maintaining FIFO for regular jobs
        sort_clause = """
            ORDER BY 
                CASE WHEN priority > 0 THEN 0 ELSE 1 END,  -- High priority jobs first
                priority DESC,                              -- Then by priority level
                created_at ASC                              -- Then FIFO (oldest first)
        """

        # Select pending jobs that are ready to run (run_at <= now)
        query = f"""
            SELECT id FROM jobs
            WHERE state = 'pending'
            AND (run_at IS NULL OR datetime(run_at) <= datetime('now'))
            AND (
                locked_by IS NULL
                OR (
                    locked_at IS NOT NULL
                    AND datetime(locked_at) < datetime('now', '-' || ? || ' seconds')
                )
            )
            {sort_clause}
            LIMIT 1
        """
        
        cursor.execute(query, (lock_seconds,))

        row = cursor.fetchone()
        if not row:
            conn.commit()
            return None

        job_id = row[0]

        # Lock and move to processing state
        now = now_timestamp()
        cursor.execute(
            """
            UPDATE jobs
            SET locked_by = ?, locked_at = ?, state = 'processing', updated_at = ?
            WHERE id = ?
        """,
            (worker_pid, now, now, job_id),
        )

        conn.commit()

        # Fetch and return the full job
        return get_job(job_id)

    except Exception as e:
        conn.rollback()
        logger.error(f"Error picking job: {e}")
        return None


def move_to_dlq(
    job_id: str,
    reason: str,
) -> None:
    """
    Move a job to the Dead Letter Queue.

    Args:
        job_id: Job ID to move to DLQ.
        reason: Reason for moving to DLQ.
    """
    import json
    import uuid

    from queuectl.utils import now_timestamp

    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch job
    job = get_job(job_id)
    if not job:
        return

    now = now_timestamp()
    dlq_id = str(uuid.uuid4())

    # Insert into DLQ
    cursor.execute(
        """
        INSERT INTO dlq (id, job_id, moved_at, reason, payload)
        VALUES (?, ?, ?, ?, ?)
    """,
        (dlq_id, job_id, now, reason, json.dumps(job)),
    )

    # Update job state to dead
    cursor.execute(
        "UPDATE jobs SET state = 'dead', updated_at = ? WHERE id = ?",
        (now, job_id),
    )

    conn.commit()
    logger.info(f"Job {job_id} moved to DLQ: {reason}")


def get_dlq_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get a DLQ entry by job ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dlq WHERE job_id = ?", (job_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def list_dlq(limit: int = 100) -> List[Dict[str, Any]]:
    """List all DLQ entries."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dlq ORDER BY moved_at DESC LIMIT ?", (limit,))
    return [dict(row) for row in cursor.fetchall()]


def requeue_from_dlq(job_id: str) -> bool:
    """
    Requeue a job from DLQ back to pending state.

    Returns:
        True if successful, False otherwise.
    """
    from queuectl.utils import now_timestamp

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if job exists in DLQ
    dlq_entry = get_dlq_job(job_id)
    if not dlq_entry:
        logger.warning(f"Job {job_id} not found in DLQ.")
        return False

    # Reset job to pending, clear lock, reset attempts
    now = now_timestamp()
    cursor.execute(
        """
        UPDATE jobs
        SET state = 'pending',
            attempts = 0,
            locked_by = NULL,
            locked_at = NULL,
            retry_at = NULL,
            updated_at = ?
        WHERE id = ?
    """,
        (now, job_id),
    )

    # Remove from DLQ
    cursor.execute("DELETE FROM dlq WHERE job_id = ?", (job_id,))

    conn.commit()
    logger.info(f"Job {job_id} requeued from DLQ.")
    return True


def get_job_counts() -> Dict[str, int]:
    """Get count of jobs per state."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT state, COUNT(*) as count
        FROM jobs
        GROUP BY state
    """
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


def delete_job(job_id: str) -> None:
    """Delete a job from database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()


def update_job_output(
    job_id: str,
    stdout_log: str,
    stderr_log: str,
    exit_code: int,
) -> None:
    """
    Store job execution output and exit code.

    Args:
        job_id: Job ID.
        stdout_log: Standard output from command.
        stderr_log: Standard error from command.
        exit_code: Exit code from command.
    """
    from queuectl.utils import now_timestamp

    conn = get_db_connection()
    cursor = conn.cursor()
    now = now_timestamp()

    cursor.execute(
        """
        UPDATE jobs
        SET stdout_log = ?, stderr_log = ?, exit_code = ?, updated_at = ?
        WHERE id = ?
    """,
        (stdout_log, stderr_log, exit_code, now, job_id),
    )

    conn.commit()


def update_job_completed_at(job_id: str) -> None:
    """Mark job as completed and record completion time."""
    from queuectl.utils import now_timestamp

    conn = get_db_connection()
    cursor = conn.cursor()
    now = now_timestamp()

    cursor.execute(
        "UPDATE jobs SET completed_at = ?, updated_at = ? WHERE id = ?",
        (now, now, job_id),
    )

    conn.commit()


def get_job_output(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve job output and exit code."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, stdout_log, stderr_log, exit_code, completed_at
        FROM jobs WHERE id = ?
    """,
        (job_id,),
    )

    row = cursor.fetchone()
    return dict(row) if row else None

