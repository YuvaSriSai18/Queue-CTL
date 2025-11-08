# Smart Scheduling - No Config Needed

## Overview

QueueCTL now uses **intelligent, automatic scheduling** based on job priority:

- **Jobs WITHOUT priority (priority = 0)** → Execute in **FIFO order** (creation sequence)
- **Jobs WITH priority (priority > 0)** → Execute by **importance level**, jumping ahead of FIFO jobs
- **Within same priority level** → FIFO order (oldest first)

## The Concept

Think of it as a **mixed queue**:

```
┌─────────────────────────────────────────┐
│         JOB EXECUTION ORDER             │
├─────────────────────────────────────────┤
│  Priority 10 jobs                       │  ← Execute FIRST
│  Priority 9 jobs                        │
│  Priority 8 jobs                        │
│  ...                                    │
│  Priority 1 jobs                        │
├─────────────────────────────────────────┤
│  Priority 0 jobs (FIFO)                 │  ← Execute AFTER
│  In creation order (oldest first)       │
└─────────────────────────────────────────┘
```

## How It Works

### Automatic, No Configuration Needed

There's **no global `scheduling_mode` setting** to manage. The scheduling is determined **automatically** based on each job's priority value:

```python
ORDER BY 
    CASE WHEN priority > 0 THEN 0 ELSE 1 END,  -- High priority first
    priority DESC,                              -- Then by priority level
    created_at ASC                              -- Then FIFO (oldest first)
```

This SQL query ensures:
1. Any job with priority > 0 comes before priority 0 jobs
2. Within priority > 0 jobs, higher values execute first
3. Within same priority, oldest job executes first

### Zero Global State

- No configuration to remember
- No mode switching needed
- Each job's behavior is determined by **its priority value alone**
- Simple and intuitive

## Examples

### Example 1: Pure FIFO (No Priority)

```bash
# Enqueue 3 jobs without specifying priority (defaults to 0)
python queuectl.py enqueue '{"id":"step1","command":"echo step 1"}'
python queuectl.py enqueue '{"id":"step2","command":"echo step 2"}'
python queuectl.py enqueue '{"id":"step3","command":"echo step 3"}'

# Execution order: step1 → step2 → step3 (in creation order)
python queuectl.py worker start --count 1
```

**Result**:
```
Step 1 executes (oldest, priority=0)
Step 2 executes (second oldest, priority=0)
Step 3 executes (newest, priority=0)
```

### Example 2: Urgent Job Interrupts FIFO

```bash
# Queue regular tasks
python queuectl.py enqueue '{"id":"download","command":"wget file.zip"}' 
python queuectl.py enqueue '{"id":"process","command":"python process.py"}'

# Emergency task arrives - give it high priority!
python queuectl.py enqueue '{"id":"alert","command":"send-alert.sh"}' --priority 10

# Check queue status
python queuectl.py list pending
```

**Result**:
```
Queue Status:
  alert (priority 10)      ← Executes FIRST (urgent)
  download (priority 0)    ← Executes SECOND (FIFO)
  process (priority 0)     ← Executes THIRD (FIFO)
```

When worker starts:
1. `alert` executes immediately
2. `download` executes next
3. `process` executes last

### Example 3: Multi-Level Priorities

```bash
# Mix of regular and priority jobs
python queuectl.py enqueue '{"id":"j1","command":"echo j1"}' --priority 0   # FIFO
python queuectl.py enqueue '{"id":"j2","command":"echo j2"}' --priority 0   # FIFO
python queuectl.py enqueue '{"id":"j3","command":"echo j3"}' --priority 5   # Medium
python queuectl.py enqueue '{"id":"j4","command":"echo j4"}' --priority 10  # Urgent
python queuectl.py enqueue '{"id":"j5","command":"echo j5"}' --priority 5   # Medium
python queuectl.py enqueue '{"id":"j6","command":"echo j6"}' --priority 0   # FIFO
```

**Execution Order**:
```
1. j4 (priority 10)  ← Highest priority first
2. j3 (priority 5)   ← Medium priority second
3. j5 (priority 5)   ← Same priority, but FIFO (older than j3? depends on creation time)
4. j1 (priority 0)   ← FIFO jobs execute last
5. j2 (priority 0)   ← In creation order
6. j6 (priority 0)   ← Last FIFO job
```

### Example 4: Scheduled + Priority

```bash
# Schedule a priority job for later
python queuectl.py enqueue \
    '{"id":"backup","command":"backup.sh"}' \
    --priority 8 \
    --run-at "2025-11-08T22:00:00Z"

# Regular queue
python queuectl.py enqueue '{"id":"cleanup","command":"cleanup.sh"}'  # priority 0
python queuectl.py enqueue '{"id":"sync","command":"sync.sh"}'        # priority 0
```

**Behavior**:
- `backup`: Waits until 22:00, then executes BEFORE `cleanup` and `sync`
- `cleanup` & `sync`: Execute in FIFO order after `backup` runs
- Scheduled + Priority work together seamlessly

## Practical Use Cases

### Use Case 1: Batch Processing with Emergency Tasks

```bash
# Regular batch jobs (all FIFO, no priority specified)
for file in dataset_*.csv; do
    python queuectl.py enqueue "{\"id\":\"process_$file\",\"command\":\"process.py $file\"}"
done

# If urgent task appears, give it priority
python queuectl.py enqueue '{"id":"urgent_fix","command":"fix_bug.py"}' --priority 10
# This jumps ahead of all batch jobs!
```

### Use Case 2: API with Priority Support

```bash
# From web API - enqueue with priority based on request type
# Regular user request (FIFO)
python queuectl.py enqueue '{"id":"req_123","command":"handle_user_request.py 123"}'

# Premium user request (higher priority)
python queuectl.py enqueue '{"id":"req_456","command":"handle_premium_request.py 456"}' --priority 8

# Admin task (urgent)
python queuectl.py enqueue '{"id":"admin_task","command":"admin_action.py"}' --priority 10
```

### Use Case 3: Maintenance + Regular Work

```bash
# Regular jobs (FIFO)
python queuectl.py enqueue '{"id":"report1","command":"generate_report.py"}'
python queuectl.py enqueue '{"id":"report2","command":"generate_report.py"}'

# Schedule maintenance with priority for specific time
python queuectl.py enqueue \
    '{"id":"maintenance","command":"maintenance.sh"}' \
    --priority 9 \
    --run-at "2025-11-09T02:00:00Z"  # 2 AM
```

Execution flow:
- report1 → report2 (run immediately in order)
- maintenance (runs at 2 AM, before other tasks waiting at that time)

## CLI Defaults

**No priority specified → Priority = 0 (FIFO)**

```bash
# This defaults to priority 0
python queuectl.py enqueue --id task --command "echo hello"
# Equivalent to:
python queuectl.py enqueue --id task --command "echo hello" --priority 0
```

## Priority Scale (0-10)

```
0 = Default (FIFO, no special treatment)
1 = Very low
2 = Low
3 = Below normal
4 = Below normal
5 = Normal
6 = Above normal
7 = Above normal
8 = High
9 = Very high
10 = Urgent/Emergency
```

## Comparison: Before vs After

### Before (Global Mode)
```
Config: scheduling_mode = "fifo" or "priority" (global setting)
Problem: All jobs must follow one mode
Flexibility: Low (can't mix FIFO and priority)
```

### After (Smart Scheduling)
```
Each job: Has its own priority
Behavior: Automatic based on priority value
Problem: Solved! Can mix FIFO and priority seamlessly
Flexibility: High (each job decides its execution priority)
```

## Summary

✅ **No configuration management needed**  
✅ **Automatic scheduling based on priority**  
✅ **FIFO jobs (priority=0) execute in creation order**  
✅ **Priority jobs jump ahead by importance level**  
✅ **Within same priority: FIFO order**  
✅ **Simple, intuitive, zero config**

**It just works!** 🚀
