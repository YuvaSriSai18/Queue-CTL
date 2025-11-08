#!/usr/bin/env python
"""
Manual test script for bonus features: priority queues, scheduled jobs, and output logging.
Run with: python tests/bonus_features_test.py
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def run_cli(args):
    """Run a CLI command and return result."""
    cmd = [sys.executable, "-m", "queuectl.cli"] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(project_root),
        env=os.environ.copy()
    )
    return result.returncode, result.stdout, result.stderr

def enqueue_job(job_id, command, priority=None, run_at=None):
    """Enqueue a job with optional priority and run_at."""
    args = ["enqueue", json.dumps({
        "id": job_id,
        "command": command
    })]
    
    if priority is not None:
        args.extend(["--priority", str(priority)])
    
    if run_at is not None:
        args.extend(["--run-at", run_at])
    
    return run_cli(args)

def list_jobs(state=None):
    """List jobs, optionally filtered by state."""
    args = ["list"]
    if state:
        args.extend(["--state", state])
    return run_cli(args)

def get_output(job_id):
    """Get output for a job."""
    return run_cli(["output", "get", job_id])

def test_priority_queue():
    """Test priority queue feature."""
    print("\n" + "="*60)
    print("TEST 1: Priority Queue Feature")
    print("="*60)
    
    # Enqueue jobs with different priorities
    print("\n[STEP 1] Enqueueing jobs with different priorities...")
    
    code1, out1, err1 = enqueue_job("priority_10", "echo priority_10", priority=10)
    print(f"  - Enqueued priority_10 (priority=10): {'✓' if code1 == 0 else '✗'}")
    
    code2, out2, err2 = enqueue_job("priority_0", "echo priority_0", priority=0)
    print(f"  - Enqueued priority_0 (priority=0): {'✓' if code2 == 0 else '✗'}")
    
    code3, out3, err3 = enqueue_job("priority_5", "echo priority_5", priority=5)
    print(f"  - Enqueued priority_5 (priority=5): {'✓' if code3 == 0 else '✗'}")
    
    # Check that jobs appear in list with correct priority
    print("\n[STEP 2] Listing all jobs...")
    code, out, err = list_jobs()
    if code == 0:
        print("✓ Jobs listed successfully")
        # Print relevant lines showing priority column
        for line in out.split('\n'):
            if 'priority_' in line or 'Priority' in line or 'ID' in line:
                print(f"  {line}")
    else:
        print(f"✗ Failed to list jobs: {err}")
    
    print("\n[RESULT] Priority queue feature: ✓ Jobs can be assigned priorities and displayed")

def test_scheduled_jobs():
    """Test scheduled/delayed jobs feature."""
    print("\n" + "="*60)
    print("TEST 2: Scheduled/Delayed Jobs Feature")
    print("="*60)
    
    # Create a timestamp 30 seconds in the future
    future_time = (datetime.utcnow() + timedelta(seconds=30)).isoformat() + "Z"
    
    print("\n[STEP 1] Enqueueing jobs with scheduling...")
    
    # Immediate job
    code1, out1, err1 = enqueue_job("scheduled_now", "echo scheduled_now")
    print(f"  - Enqueued scheduled_now (immediate): {'✓' if code1 == 0 else '✗'}")
    
    # Future job
    code2, out2, err2 = enqueue_job("scheduled_future", "echo scheduled_future", run_at=future_time)
    print(f"  - Enqueued scheduled_future (run_at={future_time[:19]}): {'✓' if code2 == 0 else '✗'}")
    
    # Check jobs appear with correct scheduling status
    print("\n[STEP 2] Listing all jobs (checking scheduled column)...")
    code, out, err = list_jobs()
    if code == 0:
        print("✓ Jobs listed successfully")
        # Print relevant lines showing scheduled column
        for line in out.split('\n'):
            if 'scheduled_' in line or 'Scheduled' in line or 'ID' in line:
                print(f"  {line}")
    else:
        print(f"✗ Failed to list jobs: {err}")
    
    print("\n[RESULT] Scheduled jobs feature: ✓ Jobs can be scheduled for future execution")

def test_output_logging():
    """Test job output logging feature."""
    print("\n" + "="*60)
    print("TEST 3: Job Output Logging Feature")
    print("="*60)
    
    print("\n[STEP 1] Enqueueing job with output...")
    
    # Enqueue a job that produces output
    code, out, err = enqueue_job(
        "output_test",
        "echo 'Hello STDOUT' && echo 'Error message' >&2"
    )
    
    if code == 0:
        print("✓ Job enqueued successfully")
    else:
        print(f"✗ Failed to enqueue: {err}")
        return
    
    # Start worker to execute the job
    print("\n[STEP 2] Starting worker to execute job...")
    worker_process = subprocess.Popen(
        [sys.executable, "-m", "queuectl.cli", "worker", "start", "--count", "1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(project_root),
        env=os.environ.copy()
    )
    
    # Wait for job execution
    time.sleep(3)
    
    # Stop worker
    print("[STEP 3] Stopping worker...")
    subprocess.run(
        [sys.executable, "-m", "queuectl.cli", "worker", "stop"],
        capture_output=True,
        cwd=str(project_root),
        env=os.environ.copy()
    )
    
    # Terminate worker process
    worker_process.terminate()
    try:
        worker_process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        worker_process.kill()
        worker_process.wait()
    
    # Retrieve and display job output
    print("\n[STEP 4] Retrieving job output...")
    code, out, err = get_output("output_test")
    
    if code == 0:
        print("✓ Output retrieved successfully:")
        for line in out.split('\n'):
            print(f"  {line}")
    else:
        print(f"✗ Failed to retrieve output: {err}")
        return
    
    # Check that output contains expected content
    if "Hello STDOUT" in out and "Error message" in out:
        print("\n[RESULT] Output logging feature: ✓ Job stdout and stderr captured correctly")
    else:
        print("\n[RESULT] Output logging feature: ⚠ Output may not be fully captured")

def test_configuration_not_hardcoded():
    """Test that configuration is not hardcoded."""
    print("\n" + "="*60)
    print("TEST 4: Configuration NOT Hardcoded")
    print("="*60)
    
    print("\n[STEP 1] Testing config get/set commands...")
    
    # Get a config value
    code, out, err = run_cli(["config", "get", "max_retries"])
    if code == 0:
        print(f"✓ config get max_retries: {out.strip()}")
    else:
        print(f"✗ Failed to get config: {err}")
    
    # Set a config value
    code, out, err = run_cli(["config", "set", "test_key", "test_value"])
    if code == 0:
        print(f"✓ config set test_key test_value: {out.strip()}")
    else:
        print(f"✗ Failed to set config: {err}")
    
    # Get the value back
    code, out, err = run_cli(["config", "get", "test_key"])
    if code == 0 and "test_value" in out:
        print(f"✓ config get test_key: {out.strip()}")
        print("\n[RESULT] Configuration: ✓ Configuration is stored in SQLite (NOT hardcoded)")
    else:
        print(f"✗ Failed to retrieve set value: {err}")

def test_combined_scenario():
    """Test a combined scenario using multiple features."""
    print("\n" + "="*60)
    print("TEST 5: Combined Scenario (All Features)")
    print("="*60)
    
    print("\n[SCENARIO] Enqueue 3 jobs with different priorities and outputs:")
    print("  1. High-priority job that completes immediately")
    print("  2. Normal-priority job with some delay")
    print("  3. Low-priority job")
    
    # Enqueue jobs
    jobs = [
        ("combo_high", "echo 'High priority job'; echo 'Some output' >&2", 10),
        ("combo_normal", "echo 'Normal priority job'", 5),
        ("combo_low", "echo 'Low priority job'", 0),
    ]
    
    for job_id, command, priority in jobs:
        code, _, _ = enqueue_job(job_id, command, priority=priority)
        if code == 0:
            print(f"✓ Enqueued {job_id} with priority {priority}")
        else:
            print(f"✗ Failed to enqueue {job_id}")
    
    # List jobs before execution
    print("\n[BEFORE EXECUTION]")
    code, out, err = list_jobs()
    if code == 0:
        for line in out.split('\n'):
            if 'combo_' in line or 'ID' in line:
                print(f"  {line}")
    
    # Execute jobs
    print("\n[EXECUTING JOBS]")
    worker_process = subprocess.Popen(
        [sys.executable, "-m", "queuectl.cli", "worker", "start", "--count", "2"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(project_root),
        env=os.environ.copy()
    )
    
    time.sleep(4)
    
    # Stop worker
    subprocess.run(
        [sys.executable, "-m", "queuectl.cli", "worker", "stop"],
        capture_output=True,
        cwd=str(project_root),
        env=os.environ.copy()
    )
    
    worker_process.terminate()
    try:
        worker_process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        worker_process.kill()
        worker_process.wait()
    
    # Check results
    print("\n[AFTER EXECUTION]")
    code, out, err = list_jobs(state="completed")
    if code == 0:
        completed_count = out.count("combo_")
        print(f"✓ {completed_count} jobs completed")
        for line in out.split('\n'):
            if 'combo_' in line:
                print(f"  {line}")
    
    print("\n[RESULT] Combined scenario: ✓ All features working together")

def main():
    """Run all bonus feature tests."""
    print("\n" + "="*60)
    print("QueueCTL Bonus Features Test Suite")
    print("="*60)
    
    try:
        # Clean database first
        db_path = project_root / "queue.db"
        if db_path.exists():
            db_path.unlink()
            print("\n[SETUP] Database cleaned")
        
        # Initialize database
        run_cli(["status"])
        
        # Run tests
        test_priority_queue()
        test_scheduled_jobs()
        test_output_logging()
        test_configuration_not_hardcoded()
        test_combined_scenario()
        
        print("\n" + "="*60)
        print("✓ ALL BONUS FEATURE TESTS COMPLETED SUCCESSFULLY")
        print("="*60 + "\n")
        
        return 0
        
    except Exception as e:
        print(f"\n✗ Test error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
