# QueueCTL Architecture Documentation

## Overview

QueueCTL is a single-machine, background job queue system designed for reliable job execution with automatic retries and dead-letter queue management. This document describes the architectural design, component interactions, and implementation details.

---

## System Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────┐
│                  CLI Interface Layer                         │
│  (queuectl.py - Typer + Rich - User Commands)              │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
   ┌────▼─────────┐          ┌───────▼────────┐
   │  Job Queue   │          │   Worker Pool  │
   │  Operations  │          │   Management   │
   │  (cli.py)    │          │   (cli.py)     │
   └────┬─────────┘          └───────┬────────┘
        │                             │
        │   Shared Data Access        │
        │           │                 │
        └───────────┼─────────────────┘
                    │
        ┌───────────▼────────────┐
        │  Data Access Layer     │
        │  (db.py - SQLite ORM)  │
        └───────────┬────────────┘
                    │
        ┌───────────▼────────────┐
        │  SQLite Database       │
        │  (queue.db)            │
        └────────────────────────┘
        
        ┌────────────────────────┐
        │  Execution Engine      │
        │  (worker.py + exec.py) │
        └────────────────────────┘
```

### Component Layer

**User Interface Layer**
- Entry point: `queuectl.py`
- Framework: Typer CLI library
- Rendering: Rich tables and formatted output

**Business Logic Layer**
- `cli.py` - Command handlers and routing
- `worker.py` - Job execution orchestration
- `scheduler.py` - Job state transitions
- `config.py` - Configuration management

**Data Access Layer**
- `db.py` - SQLite abstraction with thread-safe connections
- Transaction management
- Lock management for job atomicity

**Execution Layer**
- `exec.py` - Subprocess invocation with timeout
- `utils.py` - Supporting utilities

---

## Data Model

### Job Object

```json
{
  "id": "job_12345",
  "command": "echo Hello World",
  "state": "pending",
  "priority": 5,
  "attempts": 0,
  "max_retries": 3,
  "locked_by": null,
  "locked_until": null,
  "error": null,
  "retry_at": null,
  "run_at": null,
  "created_at": "2025-11-08T10:30:00Z",
  "updated_at": "2025-11-08T10:30:00Z"
}
```

### Job States

```
pending     → Job waiting to be picked by worker
processing  → Job currently being executed
completed   → Job succeeded (exit code 0)
failed      → Job failed during processing (intermediate state, rarely seen)
dead        → Job moved to DLQ (max retries exceeded)
```

### Database Schema

**jobs table**
```sql
CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  command TEXT NOT NULL,
  state TEXT DEFAULT 'pending',
  attempts INTEGER DEFAULT 0,
  max_retries INTEGER DEFAULT 3,
  locked_by INTEGER,
  locked_until REAL,
  error TEXT,
  retry_at REAL,
  created_at TEXT,
  updated_at TEXT
);

CREATE INDEX idx_jobs_state ON jobs(state);
CREATE INDEX idx_jobs_retry_at ON jobs(retry_at);
```

**dlq table** (Dead Letter Queue)
```sql
CREATE TABLE dlq (
  job_id TEXT PRIMARY KEY,
  reason TEXT,
  moved_at TEXT
);
```

**config table**
```sql
CREATE TABLE config (
  key TEXT PRIMARY KEY,
  value TEXT
);
```

---

## Process Flow

### Job Lifecycle Flowchart

```
START: User enqueues job
  │
  ├─ INSERT into jobs table (state='pending')
  │
  ▼
JOB IN QUEUE
  │
  ├─ Worker starts (python queuectl.py worker start)
  │
  ▼
WORKER MAIN LOOP
  │
  ├─ Check for ready jobs (state='pending' AND retry_at <= now)
  │
  ├─ Call pick_pending_job()
  │  │
  │  ├─ BEGIN IMMEDIATE transaction (atomic)
  │  ├─ SELECT job WHERE state='pending'
  │  │  ORDER BY (priority > 0 ? 0 : 1), priority DESC, created_at ASC
  │  │  (Smart Scheduling: Priority jobs first, then FIFO)
  │  ├─ UPDATE job: state='processing', locked_by=pid, locked_until=now+lease
  │  ├─ COMMIT
  │  │
  │  └─ Return job (or None if queue empty)
  │
  ├─ Execute subprocess (exec.py execute_command)
  │  │
  │  ├─ Run: subprocess.run(command, shell=True, timeout=3600)
  │  ├─ Capture exit_code, stdout, stderr
  │  │
  │  └─ Return (exit_code, stdout, stderr)
  │
  ▼
EXIT CODE CHECK
  │
  ├─ If exit_code == 0
  │  │
  │  ├─ UPDATE job: state='completed'
  │  ├─ Log: Job completed successfully
  │  │
  │  └─ Loop back to WORKER MAIN LOOP
  │
  └─ If exit_code != 0
     │
     ├─ Increment attempts
     │
     ├─ Check attempts < max_retries
     │  │
     │  ├─ If YES
     │  │  │
     │  │  ├─ Calculate retry_at = now + backoff_delay(attempts, config)
     │  │  ├─ UPDATE job: state='pending', retry_at, error
     │  │  ├─ Log: Job scheduled for retry
     │  │  │
     │  │  └─ Loop back to WORKER MAIN LOOP
     │  │
     │  └─ If NO
     │     │
     │     ├─ Move to DLQ
     │     │  │
     │     │  ├─ UPDATE job: state='dead'
     │     │  ├─ INSERT INTO dlq: job_id, reason, moved_at
     │     │  ├─ Log: Job moved to DLQ
     │     │  │
     │     │  └─ Loop back to WORKER MAIN LOOP
```

### Database Transaction Flow

**Atomic Job Picking** (Most Critical)

```
Worker 1                           Worker 2
  │                                  │
  ├─ BEGIN IMMEDIATE                 │
  ├─ SELECT ... WHERE state='pending'│
  │  (Holds IMMEDIATE lock)          │
  │                                  ├─ BEGIN IMMEDIATE
  │                                  │ (WAITS for lock)
  ├─ UPDATE job: state='processing'  │
  ├─ COMMIT (releases lock)          │
  │                                  ├─ Acquires lock
  │                                  ├─ SELECT ... WHERE state='pending'
  │                                  ├─ (gets different job or empty set)
  │                                  ├─ UPDATE (if job found)
  │                                  ├─ COMMIT
```

Why IMMEDIATE? 
- Regular BEGIN uses deferred locking → can deadlock
- BEGIN IMMEDIATE acquires exclusive lock immediately
- Ensures only one worker can query pending jobs at a time
- Prevents race conditions and duplicate job processing

---

## Concurrency & Locking Strategy

### Lock Mechanism

**Database Locks (jobs.locked_by and jobs.locked_until)**

```python
# When worker picks job:
job.locked_by = worker_pid
job.locked_until = time.time() + config.lock_lease_seconds  # 300 seconds

# When worker completes job:
job.locked_by = None
job.locked_until = None

# If worker crashes:
# Stale locks detected by cleanup_expired_locks() scheduler
# Automatic release after lock_lease_seconds timeout
```

### Thread Safety

**Thread-Local Connections**
```python
# In db.py
_thread_local = threading.local()

def _get_connection():
    if not hasattr(_thread_local, 'connection'):
        _thread_local.connection = sqlite3.connect(db_path)
        _thread_local.connection.isolation_level = None  # Autocommit OFF for transaction control
    return _thread_local.connection
```

**Why Thread-Local Storage?**
- SQLite connections not safe for multi-threaded access
- Each thread gets its own connection instance
- Prevents "database is locked" errors from concurrent connections
- Threads are used only in scheduler; workers use separate processes

### Process-Based Parallelism

**Why multiprocessing instead of threading?**
- Python's GIL (Global Interpreter Lock) limits threading
- True parallel CPU usage on multi-core systems
- Process isolation prevents crashes from affecting other workers
- Each worker gets its own Python interpreter

```python
# Windows compatibility (spawn mode)
multiprocessing.set_start_method('spawn', force=True)

# Reasons for spawn:
# - Default on Windows anyway
# - Safest method across platforms
# - Avoids fork issues on Windows (no fork() syscall)
```

---

## Retry & Backoff Strategy

### Exponential Backoff Formula

```
backoff_delay = min(base^attempts, max_backoff_seconds)

Where:
  base = config.backoff_base (default: 2)
  attempts = job.attempts (0, 1, 2, ...)
  max_backoff_seconds = config.max_backoff_seconds (default: 300)
```

### Example Timeline

With base=2, max_backoff=300:
```
Attempt 0 (initial):    execute immediately
Attempt 1 (fail):       retry after 2^1 = 2 seconds
Attempt 2 (fail):       retry after 2^2 = 4 seconds
Attempt 3 (fail):       retry after 2^3 = 8 seconds
Attempt 4 (fail):       retry after 2^4 = 16 seconds
Attempt 5 (fail):       retry after 2^5 = 32 seconds
Attempt 6 (fail):       retry after 2^6 = 64 seconds
Attempt 7 (fail):       retry after 2^7 = 128 seconds
Attempt 8 (fail):       retry after 2^8 = 256 seconds
Attempt 9 (fail):       retry after min(2^9=512, 300) = 300 seconds
Attempt 10 (fail):      move to DLQ (exceeds max_retries=3)
```

### Why Exponential Backoff?

1. **Prevents Load Spikes** - Failed services get recovery time
2. **Reduces Database Load** - Less polling under failure
3. **Fair Resource Sharing** - Temporary failures don't starve system
4. **Industry Standard** - Used by AWS, Google Cloud, Azure

---

## Worker Lifecycle

### Worker Process Startup

```python
# Command: python queuectl.py worker start --count 2

1. Parse CLI arguments
2. Get config (max_retries, backoff_base, etc.)
3. Create N worker processes using multiprocessing.Process
4. Each process runs: worker.start_worker(worker_id)
5. Main process waits for SIGTERM/SIGINT
6. On signal: gracefully shutdown each worker
```

### Worker Process Main Loop

```python
def start_worker(worker_id):
    logger.info(f"Worker {worker_id} started with PID {os.getpid()}")
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)
    
    while True:
        try:
            # Check if shutdown requested
            if _shutdown_requested:
                logger.info(f"Worker {worker_id} shutting down gracefully")
                break
            
            # Move jobs with ready retry_at to pending
            scheduler.move_ready_jobs_to_pending()
            
            # Clean up expired locks
            scheduler.cleanup_expired_locks()
            
            # Pick one pending job atomically
            job = db.pick_pending_job()
            
            if job is None:
                # No jobs available, sleep to prevent busy-wait
                time.sleep(1)
                continue
            
            # Process this job
            _process_one_job(job)
            
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
            time.sleep(1)
```

### Graceful Shutdown

```
User: python queuectl.py worker stop
    │
    ├─ Send SIGTERM to all active worker processes
    │
    ├─ Workers receive SIGTERM
    │  │
    │  ├─ Set _shutdown_requested = True
    │  │
    │  ├─ Finish current job if processing
    │  │
    │  ├─ Exit main loop gracefully
    │  │
    │  └─ Log: "Worker shutdown complete"
    │
    ├─ Main process waits for all workers to exit
    │
    └─ Clean process shutdown, no lost jobs
```

**Why Graceful Shutdown?**
- Jobs can complete before worker exits
- No partial job execution
- Database consistency maintained
- No orphaned processes

---

## Configuration Management

### Configuration Architecture

```
User CLI Command
  │
  ├─ config get max_retries
  │  │
  │  ├─ Call config.Config.get("max_retries")
  │  │
  │  ├─ Query database: SELECT value FROM config WHERE key='max_retries'
  │  │
  │  ├─ If not found: return DEFAULT_CONFIG['max_retries']
  │  │
  │  └─ Display to user
  │
  └─ config set max_retries 5
     │
     ├─ Call config.Config.set("max_retries", "5")
     │
     ├─ INSERT OR REPLACE INTO config (key, value) VALUES (...)
     │
     └─ Confirm updated
```

### Default Configuration

```python
DEFAULT_CONFIG = {
    'max_retries': '3',
    'backoff_base': '2',
    'max_backoff_seconds': '300',
    'lock_lease_seconds': '300'
}
```

### Configuration Persistence

- Stored in SQLite `config` table
- Survives application restart
- Changed during runtime without code modification
- Different settings for different jobs via job-specific max_retries

---

## Error Handling Strategy

### Exit Code Interpretation

```
exit_code == 0       → Job succeeded (completed)
exit_code != 0       → Job failed (command returned error)
subprocess.TimeoutExpired  → Job timeout (1 hour)
subprocess.CalledProcessError  → Job execution error
Exception (generic)  → Unexpected error (logged, retried)
```

### Error Logging

Each failed job captures:
- exit_code
- error message
- stdout (if available)
- stderr (if available)
- Timestamp of failure
- Attempt number

Example error log:
```
2025-11-08 10:45:32 ERROR Job job_123 failed (attempt 1/3)
  Command: python invalid_script.py
  Exit Code: 1
  Error: FileNotFoundError: [Errno 2] No such file or directory: 'invalid_script.py'
  Scheduled retry at: 2025-11-08 10:45:34 (in 2 seconds)
```

---

## Scheduler Operations

### Scheduled Tasks

Scheduler runs in worker main loop and performs two key operations:

**1. Move Ready Jobs to Pending**
```python
# Every 1-5 seconds (during main loop)
# SELECT * FROM jobs WHERE state='pending' AND retry_at <= NOW()
# (These are jobs with retry_at in the past - now ready)
# Workers will pick these in next iteration
```

**2. Cleanup Expired Locks**
```python
# Every 1-5 seconds (during main loop)
# SELECT * FROM jobs WHERE locked_until < NOW()
# (These are jobs locked by crashed workers)
# UPDATE jobs: locked_by=NULL, locked_until=NULL
# (Release lock so other workers can pick them)
```

### Lock Lease Pattern

```
Normal Flow:
  Worker picks job
  ├─ locked_by = 12345 (worker PID)
  ├─ locked_until = now + 300 seconds
  ├─ Execute job
  ├─ Update job: locked_by=NULL, locked_until=NULL
  ├─ Set state to completed/pending (retry)
  └─ Lock released

Worker Crash Flow:
  Worker picks job
  ├─ locked_by = 12345 (worker PID)
  ├─ locked_until = now + 300 seconds
  ├─ (Process crashes)
  │
  ├─ (Time passes...)
  │
  ├─ Scheduler detects: locked_until < now
  ├─ Release lock: locked_by=NULL, locked_until=NULL
  ├─ Job returned to pending state
  └─ Another worker can pick it up
```

---

## Performance Considerations

### Throughput Optimization

```
Job Execution Time: ~100-5000ms (depends on command)
Lock/Retry Overhead: ~10-50ms
Database I/O: ~5-20ms per operation

Calculated Throughput:
- 1 worker: ~10-100 jobs/second (depending on command complexity)
- 4 workers: ~40-400 jobs/second
- Bottleneck: Usually the command execution time, not QueueCTL
```

### Database Index Strategy

```sql
-- Fast job picking
CREATE INDEX idx_jobs_state ON jobs(state);

-- Fast retry scheduling
CREATE INDEX idx_jobs_retry_at ON jobs(retry_at);

-- These two indexes ensure worker main loop is O(1) for finding jobs
```

### Memory Usage

```
Per Worker Process:
  Python interpreter: ~20MB
  Database connection: ~5MB
  Job object: ~10KB
  Buffer/overhead: ~25MB
  Total: ~50MB per worker

Shared:
  SQLite database: 1KB per job
  Shared libraries: ~20MB
  
With 4 workers and 10,000 jobs:
  Estimate: 50MB*4 + 10,000KB + 20MB = ~210MB
```

---

## Security Considerations

### Command Execution

**Current Implementation**
```python
# exec.py
subprocess.run(command, shell=True, timeout=3600)
```

**Risks**
- Shell injection if job.command from untrusted source
- Access to system commands (rm, del, etc.)

**Mitigations**
- Users responsible for validating job commands
- Commands logged for audit trail
- Run in isolated user account (can be done at OS level)
- Timeout prevents infinite loops (1 hour max)

### Database Access

**Current Implementation**
- SQLite file-based, no remote access
- File permissions controlled by OS
- User must have write access to queue.db

**Mitigations**
- Run QueueCTL with minimal privilege account
- Restrict access to queue.db file permissions
- Consider encryption at rest for sensitive data

---

## Scalability Limitations

### Single-Machine Constraint

QueueCTL is designed for single-machine deployment:
- **Max Recommended**: 100,000 jobs in database
- **Max Workers**: 16 (CPU-bound, beyond diminishing returns)
- **Max Throughput**: 1,000-10,000 jobs/second (command-dependent)

### For Larger Workloads

Consider alternatives:
- **Celery**: Distributed, multi-machine
- **RQ (Redis Queue)**: Redis-backed, scalable
- **AWS SQS + Lambda**: Managed service
- **Apache Kafka**: Event streaming

---

## Testing Architecture

### Unit Tests (test_basic.py)
- Database operations
- Configuration management
- Backoff calculations

### Integration Tests (windows_test.py)
- CLI command execution
- Worker lifecycle
- Job processing

### End-to-End Tests (integration_test.py)
- Full job lifecycle
- Multi-worker concurrency
- Retry mechanisms
- DLQ operations

### Test Data Isolation

```python
# Each test clears database first
db.clear_all_tables()

# Ensures tests don't interfere
# Allows parallel test execution potential
```

---

## Deployment Topology

### Development Setup
```
User Workstation
  │
  ├─ Python 3.8+
  ├─ queue.db (local)
  ├─ queuectl.py
  └─ .queuectl.log
```

### Production Setup (Same Machine)
```
Production Server
  │
  ├─ Python 3.8+
  ├─ queue.db (backed up regularly)
  ├─ queuectl.exe (Windows binary from build_exe.bat)
  ├─ Systemd service (Linux) or Task Scheduler (Windows)
  ├─ .queuectl.log (monitored)
  └─ .queuectl.pid (for process management)
```

### Suggested Enhancements for Production

1. **Log Rotation**
   - Implement logrotate (Linux) or Windows Event Log
   - Keep only last 30 days of logs

2. **Monitoring**
   - Alert on worker crash
   - Monitor job DLQ growth
   - Track throughput metrics

3. **Backup**
   - Backup queue.db daily
   - Restore capability tested

4. **High Availability**
   - Run multiple QueueCTL instances (separate databases)
   - Or implement distributed locking for shared database

---

## Future Architectural Enhancements

### Not Currently Implemented (Bonus Features)

1. **Job Priority Queue**
   - Add priority column to jobs table
   - Sort by priority in job selection

2. **Job Scheduling (Cron)**
   - Add scheduled_for column
   - Move to pending when time arrives

3. **Job Dependencies**
   - Add depends_on column
   - Check dependencies before execution

4. **Metrics/Dashboard**
   - Track job counts per state over time
   - Web dashboard for monitoring
   - API endpoint for external tools

5. **Distributed Queue**
   - Add node_id column
   - Distributed lock coordination
   - Multiple machines sharing same queue

---

## References

- **SQLite**: https://www.sqlite.org/
- **Typer CLI**: https://typer.tiangolo.com/
- **Rich**: https://rich.readthedocs.io/
- **Exponential Backoff**: https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
- **Process-based Parallelism**: https://docs.python.org/3/library/multiprocessing.html

---

**Document Version**: 1.0
**Last Updated**: November 8, 2025
**Audience**: Developers, DevOps, System Architects
