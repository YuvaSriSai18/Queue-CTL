"""
Worker process that picks and executes jobs from the queue.
"""

import os
import signal
import sys
import time
from datetime import datetime
from typing import Optional

# Important for Windows multiprocessing
if sys.platform == 'win32':
    import multiprocessing
    multiprocessing.set_start_method('spawn', force=True)

from queuectl.config import Config
from queuectl.db import (
    get_job,
    increment_job_attempts,
    lock_job,
    move_to_dlq,
    pick_pending_job,
    set_job_retry_at,
    unlock_job,
    update_job_error,
    update_job_state,
    update_job_output,
    update_job_completed_at,
)
from queuectl.exec import execute_command
from queuectl.utils import calculate_retry_at, get_logger, now_timestamp

logger = get_logger(__name__)


class Worker:
    """Worker process for handling jobs from the queue."""

    def __init__(self, worker_id: int):
        """
        Initialize a worker.

        Args:
            worker_id: Unique worker identifier.
        """
        self.worker_id = worker_id
        self.pid = os.getpid()
        self.shutdown_requested = False

        # Register signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

        logger.info(f"Worker {self.worker_id} (PID {self.pid}) started.")

    def _handle_shutdown(self, signum, frame) -> None:
        """Handle shutdown signals gracefully."""
        logger.info(f"Worker {self.worker_id} received shutdown signal.")
        self.shutdown_requested = True

    def run(self) -> None:
        """Main worker loop."""
        while not self.shutdown_requested:
            try:
                self._process_one_job()
            except Exception as e:
                logger.error(f"Worker loop error: {e}", exc_info=True)
                time.sleep(1)

        logger.info(f"Worker {self.worker_id} shutting down.")

    def _process_one_job(self) -> None:
        """
        Pick one job and process it.
        If no job is available, sleep briefly.
        """
        lock_seconds = Config.get_int("lock_lease_seconds")
        job = pick_pending_job(self.pid, lock_seconds)

        if not job:
            time.sleep(0.5)
            return

        job_id = job["id"]
        logger.info(f"Worker {self.worker_id} picked job {job_id}.")

        try:
            self._execute_job(job)
        except Exception as e:
            logger.error(f"Error processing job {job_id}: {e}", exc_info=True)
            self._handle_job_error(job_id, str(e))

    def _execute_job(self, job: dict) -> None:
        """
        Execute a single job.

        Args:
            job: Job dictionary.
        """
        job_id = job["id"]
        command = job["command"]

        # Increment attempts
        increment_job_attempts(job_id)

        # Execute command
        exit_code, stdout, stderr = execute_command(command)

        # Store output and exit code in database
        update_job_output(job_id, stdout, stderr, exit_code)

        # Determine if successful
        if exit_code == 0:
            self._handle_job_success(job_id, stdout)
        else:
            error_msg = f"Exit code {exit_code}: {stderr}"
            self._handle_job_failure(job_id, job, error_msg)

    def _handle_job_success(self, job_id: str, output: str) -> None:
        """Handle successful job completion."""
        update_job_state(job_id, "completed")
        update_job_completed_at(job_id)
        unlock_job(job_id)
        logger.info(f"Job {job_id} completed successfully.")

    def _handle_job_failure(self, job_id: str, job: dict, error: str) -> None:
        """
        Handle job failure with retry logic.

        Args:
            job_id: Job ID.
            job: Job dictionary.
            error: Error message.
        """
        job = get_job(job_id)
        attempts = job["attempts"]
        max_retries = job["max_retries"]

        # Update error
        update_job_error(job_id, error)

        # Check if should retry
        if attempts < max_retries:
            # Schedule retry with exponential backoff
            backoff_base = Config.get_int("backoff_base")
            max_backoff = Config.get_int("max_backoff_seconds")
            retry_at = calculate_retry_at(attempts, backoff_base, max_backoff)
            set_job_retry_at(job_id, retry_at)

            # Set back to pending
            update_job_state(job_id, "pending")
            unlock_job(job_id)

            logger.info(
                f"Job {job_id} scheduled for retry at {retry_at} "
                f"(attempt {attempts} of {max_retries})."
            )
        else:
            # Move to DLQ
            move_to_dlq(job_id, f"Max retries exceeded: {error}")
            logger.error(f"Job {job_id} moved to DLQ after {attempts} attempts.")

    def _handle_job_error(self, job_id: str, error: str) -> None:
        """
        Handle unexpected error during job processing.

        Args:
            job_id: Job ID.
            error: Error message.
        """
        job = get_job(job_id)
        if job:
            self._handle_job_failure(job_id, job, error)


def start_worker(worker_id: int) -> None:
    """
    Entry point for a worker process.

    Args:
        worker_id: Worker identifier.
    """
    worker = Worker(worker_id)
    worker.run()
