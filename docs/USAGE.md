QUEUECTL - USAGE GUIDE
======================

This is a standalone CLI tool for managing background job queues.

INSTALLATION
============

1. Ensure you have Python 3.8+ installed
2. Install dependencies:
   pip install -r requirements.txt

3. Run as standalone script:
   python queuectl.py [COMMAND]

Or build Windows executable:
   build_exe.bat
   Then use: queuectl.exe [COMMAND]


BASIC COMMANDS
==============

Status - Check queue status:
  python queuectl.py status

Enqueue - Add a new job:
  python queuectl.py enqueue --id job1 --command "echo hello"
  python queuectl.py enqueue --id job2 --command "dir C:\"
  python queuectl.py enqueue --id job3 --command "python script.py" --retries 5
  
  With priority (0-10, higher = more urgent):
  python queuectl.py enqueue --id urgent --command "alert.sh" --priority 10
  python queuectl.py enqueue --id normal --command "process.sh" --priority 5
  
  With scheduled execution:
  python queuectl.py enqueue --id later --command "backup.sh" --run-at "2025-11-08T15:30:00Z"

List - Show all jobs:
  python queuectl.py list
  python queuectl.py list --state pending
  python queuectl.py list --state completed
  python queuectl.py list --limit 50

Worker - Start/stop workers:
  python queuectl.py worker start
  python queuectl.py worker start --count 4
  python queuectl.py worker stop

Config - Get/set configuration:
  python queuectl.py config get max_retries
  python queuectl.py config set max_retries 10
  python queuectl.py config set backoff_base 2

DLQ - Manage dead letter queue:
  python queuectl.py dlq list
  python queuectl.py dlq retry job_id


WORKFLOW EXAMPLE
================

Terminal 1 - Start workers:
  cd d:\Projects\Personel\queue CTL
  python queuectl.py worker start --count 2

Terminal 2 - Enqueue some jobs:
  cd d:\Projects\Personel\queue CTL
  python queuectl.py enqueue --id task1 --command "echo Task 1"
  python queuectl.py enqueue --id task2 --command "echo Task 2"
  python queuectl.py enqueue --id task3 --command "dir C:\"

Terminal 3 - Monitor progress:
  cd d:\Projects\Personel\queue CTL
  python queuectl.py status
  python queuectl.py list
  python queuectl.py list --state pending
  python queuectl.py list --state completed

When done:
  python queuectl.py worker stop


OPTIONS REFERENCE
=================

enqueue:
  --id JOBID          Unique job identifier
  --command CMD       Command to execute
  --retries N         Max retries (default: 3)
  --priority P        Priority level 0-10 (default: 0, higher = urgent)
  --run-at TIME       ISO timestamp for scheduled execution

list:
  --state STATE       Filter by state (pending/processing/completed/failed/dead)
  --limit N           Max jobs to show (default: 100)

worker start:
  --count N           Number of workers (default: 1)

config set:
  max_retries         Maximum job retries (default: 3)
  backoff_base        Exponential backoff base (default: 2)
  max_backoff_seconds Maximum backoff delay (default: 300)
  lock_lease_seconds  Worker lock timeout (default: 300)
  job_timeout_seconds Job execution timeout (default: 3600)


SMART JOB SCHEDULING
====================

QueueCTL uses SMART AUTOMATIC SCHEDULING:

Priority = 0 (Default):
  - Jobs execute in FIFO order (creation sequence)
  - No special treatment
  - Use for regular batch work

Priority > 0:
  - Jobs execute by importance level (higher = sooner)
  - Jump ahead of priority 0 jobs
  - Use for urgent work

Priority Scale:
  0    = Default (FIFO)
  1-3  = Low
  4-6  = Normal
  7-9  = High
  10   = Emergency/Urgent

Examples:
  # Regular FIFO job
  queuectl enqueue --id task --command "echo task"
  
  # High priority job (executes before FIFO)
  queuectl enqueue --id urgent --command "alert.sh" --priority 10
  
  # Scheduled job with priority
  queuectl enqueue --id backup --command "backup.sh" --priority 8 --run-at "2025-11-08T22:00:00Z"


JOB STATES
==========

pending    - Waiting to be executed
processing - Currently being executed
completed  - Executed successfully
failed     - Execution failed
dead       - Moved to DLQ after max retries


FILES
=====

queuectl.py         - Main standalone script
queue.db            - SQLite database with all jobs
.queuectl.log       - Application log file
.queuectl.pid       - Active worker process IDs

queuectl/           - Python package
  cli.py            - CLI interface
  db.py             - Database layer
  worker.py         - Worker processes
  config.py         - Configuration
  exec.py           - Command execution
  scheduler.py      - Job scheduling
  utils.py          - Utilities


BUILDING WINDOWS EXECUTABLE
============================

One-time setup:
  build_exe.bat

This creates queuectl.exe which you can distribute and use as:
  queuectl.exe status
  queuectl.exe enqueue --id job1 --command "echo test"
  queuectl.exe worker start --count 2


TROUBLESHOOTING
===============

Error: "No module named 'queuectl'"
  Make sure you're running from the project root directory

Error: "Command not found"
  Use: python queuectl.py --help to see available commands

Error: "Job already exists"
  Use unique --id values for each job

Error: "Database locked"
  Stop all workers first: python queuectl.py worker stop

View logs:
  type .queuectl.log (Windows)
  cat .queuectl.log (Linux/Mac)


CONFIGURATION DEFAULTS
======================

max_retries = 3                  (retry failed jobs max 3 times)
backoff_base = 2                 (exponential backoff multiplier)
max_backoff_seconds = 300        (max 5 minute delay)
lock_lease_seconds = 300         (worker lock timeout 5 minutes)


EXAMPLES
========

Simple echo command:
  python queuectl.py enqueue --id hello --command "echo Hello World"

Run Python script:
  python queuectl.py enqueue --id pyscript --command "python myscript.py"

List directory:
  python queuectl.py enqueue --id ls --command "dir C:\"

Run with retries:
  python queuectl.py enqueue --id critical --command "curl https://api.example.com" --retries 5

Start multiple workers:
  python queuectl.py worker start --count 4

Monitor specific state:
  python queuectl.py list --state processing

Retry failed job:
  python queuectl.py dlq retry job_id


VERSION
=======
QueueCTL 1.0
