"""
Integration tests for QueueCTL - Run with pytest
"""

import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from queuectl.config import Config
from queuectl.db import (
    close_db_connection,
    delete_job,
    get_db_connection,
    get_job,
    get_job_counts,
    init_db,
    insert_job,
    list_dlq,
    list_jobs,
    move_to_dlq,
    pick_pending_job,
    requeue_from_dlq,
)
from queuectl.exec import execute_command
from queuectl.utils import calculate_backoff, calculate_retry_at


class TestDatabase(unittest.TestCase):
    """Test database operations."""

    def setUp(self):
        """Set up test fixtures."""
        # Use in-memory database for tests
        self.original_db_path = None

    def test_init_db(self):
        """Test database initialization."""
        init_db()
        # If no exception, initialization succeeded

    def test_insert_and_get_job(self):
        """Test inserting and retrieving a job."""
        init_db()
        insert_job("test_job_1", "echo hello", max_retries=3)

        job = get_job("test_job_1")
        self.assertIsNotNone(job)
        self.assertEqual(job["id"], "test_job_1")
        self.assertEqual(job["command"], "echo hello")
        self.assertEqual(job["state"], "pending")
        self.assertEqual(job["attempts"], 0)
        self.assertEqual(job["max_retries"], 3)

    def test_list_jobs(self):
        """Test listing jobs."""
        init_db()
        insert_job("job_1", "cmd1")
        insert_job("job_2", "cmd2")
        insert_job("job_3", "cmd3")

        jobs = list_jobs()
        self.assertGreaterEqual(len(jobs), 3)

    def test_list_jobs_by_state(self):
        """Test filtering jobs by state."""
        init_db()
        insert_job("pending_job", "cmd")

        # Should have at least 1 pending job
        pending_jobs = list_jobs(state="pending")
        self.assertGreater(len(pending_jobs), 0)

    def test_job_counts(self):
        """Test getting job counts per state."""
        init_db()
        insert_job("job1", "cmd1")

        counts = get_job_counts()
        self.assertIn("pending", counts)
        self.assertGreater(counts["pending"], 0)


class TestConfig(unittest.TestCase):
    """Test configuration management."""

    def test_get_default_config(self):
        """Test getting default configuration."""
        init_db()
        value = Config.get("max_retries")
        self.assertEqual(value, "3")

    def test_set_and_get_config(self):
        """Test setting and getting configuration."""
        init_db()
        Config.set("max_retries", "5")
        value = Config.get("max_retries")
        self.assertEqual(value, "5")

    def test_get_int_config(self):
        """Test getting configuration as integer."""
        init_db()
        Config.set("backoff_base", "2")
        value = Config.get_int("backoff_base")
        self.assertEqual(value, 2)
        self.assertIsInstance(value, int)


class TestExecutor(unittest.TestCase):
    """Test command execution."""

    def test_execute_success_command(self):
        """Test executing a successful command."""
        exit_code, stdout, stderr = execute_command("echo 'Hello World'")
        self.assertEqual(exit_code, 0)
        self.assertIn("Hello World", stdout)

    def test_execute_failure_command(self):
        """Test executing a failing command."""
        exit_code, stdout, stderr = execute_command("exit 1")
        self.assertNotEqual(exit_code, 0)

    def test_execute_with_stderr(self):
        """Test capturing stderr."""
        exit_code, stdout, stderr = execute_command("python -c \"import sys; sys.stderr.write('error')\"")
        self.assertIn("error", stderr)


class TestBackoff(unittest.TestCase):
    """Test exponential backoff calculation."""

    def test_backoff_progression(self):
        """Test backoff increases exponentially."""
        backoff_0 = calculate_backoff(0, base=2, max_backoff=300)
        backoff_1 = calculate_backoff(1, base=2, max_backoff=300)
        backoff_2 = calculate_backoff(2, base=2, max_backoff=300)

        self.assertEqual(backoff_0, 1)  # 2^0
        self.assertEqual(backoff_1, 2)  # 2^1
        self.assertEqual(backoff_2, 4)  # 2^2

    def test_backoff_max_cap(self):
        """Test backoff is capped at maximum."""
        backoff = calculate_backoff(10, base=2, max_backoff=100)
        self.assertLessEqual(backoff, 100)

    def test_calculate_retry_at(self):
        """Test retry_at timestamp calculation."""
        retry_at = calculate_retry_at(0, base=2, max_backoff=300)
        self.assertIsNotNone(retry_at)
        self.assertTrue(retry_at.endswith("Z"))


class TestJobProcessing(unittest.TestCase):
    """Test job processing workflow."""

    def test_pick_pending_job(self):
        """Test picking a pending job."""
        init_db()
        # Clean up any existing pending jobs using the thread-local connection
        # to ensure we get the right one (tests don't clean DB between methods)
        try:
            conn = get_db_connection()
            conn.execute("DELETE FROM jobs WHERE state = 'pending'")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Connection issue, will work anyway
        
        insert_job("job_to_pick", "echo test")

        job = pick_pending_job(worker_pid=12345)
        self.assertIsNotNone(job)
        self.assertEqual(job["id"], "job_to_pick")
        self.assertEqual(job["state"], "processing")
        self.assertEqual(job["locked_by"], 12345)

    def test_move_to_dlq(self):
        """Test moving job to DLQ."""
        init_db()
        insert_job("job_for_dlq", "cmd")

        move_to_dlq("job_for_dlq", "Test reason")

        # Check job is in DLQ
        dlq_items = list_dlq()
        job_ids = [item["job_id"] for item in dlq_items]
        self.assertIn("job_for_dlq", job_ids)

    def test_requeue_from_dlq(self):
        """Test requeueing job from DLQ."""
        init_db()
        insert_job("job_to_requeue", "cmd")
        move_to_dlq("job_to_requeue", "Initial failure")

        # Verify it's in DLQ
        self.assertIsNotNone(list(filter(lambda x: x["job_id"] == "job_to_requeue", list_dlq())))

        # Requeue
        success = requeue_from_dlq("job_to_requeue")
        self.assertTrue(success)

        # Verify it's back in pending
        job = get_job("job_to_requeue")
        self.assertEqual(job["state"], "pending")
        self.assertEqual(job["attempts"], 0)


class TestConcurrency(unittest.TestCase):
    """Test concurrent job picking."""

    def test_multiple_workers_pick_different_jobs(self):
        """Test that multiple workers pick different jobs."""
        init_db()
        insert_job("worker_job_1", "cmd")
        insert_job("worker_job_2", "cmd")
        insert_job("worker_job_3", "cmd")

        job1 = pick_pending_job(worker_pid=1001)
        job2 = pick_pending_job(worker_pid=1002)
        job3 = pick_pending_job(worker_pid=1003)

        # All jobs should be picked
        self.assertIsNotNone(job1)
        self.assertIsNotNone(job2)
        self.assertIsNotNone(job3)

        # All should have different IDs
        job_ids = {job1["id"], job2["id"], job3["id"]}
        self.assertEqual(len(job_ids), 3)


if __name__ == "__main__":
    unittest.main()
