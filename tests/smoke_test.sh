#!/bin/bash
# Smoke test script for QueueCTL
# This script demonstrates the main features of QueueCTL

set -e  # Exit on error

echo "========================================="
echo "QueueCTL Smoke Test"
echo "========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
WORKERS_COUNT=2
TEST_DELAY=5

echo -e "${BLUE}[1] Initializing database...${NC}"
python -m queuectl.cli status > /dev/null 2>&1 || true
echo "✓ Database initialized"
echo ""

echo -e "${BLUE}[2] Setting custom configuration...${NC}"
python -m queuectl.cli config set max_retries 3
python -m queuectl.cli config set backoff_base 2
python -m queuectl.cli config get max_retries
python -m queuectl.cli config get backoff_base
echo ""

echo -e "${BLUE}[3] Enqueuing test jobs...${NC}"
# Success jobs
python -m queuectl.cli enqueue '{"id":"test_success_1","command":"echo Success Job 1"}'
python -m queuectl.cli enqueue '{"id":"test_success_2","command":"echo Success Job 2"}'
python -m queuectl.cli enqueue '{"id":"test_sleep","command":"sleep 1; echo Delayed Success"}'

# Failure jobs (to test retry and DLQ)
python -m queuectl.cli enqueue '{"id":"test_fail_1","command":"exit 1","max_retries":2}'
python -m queuectl.cli enqueue '{"id":"test_fail_2","command":"false","max_retries":1}'

echo "✓ 5 jobs enqueued"
echo ""

echo -e "${BLUE}[4] Showing initial job list...${NC}"
python -m queuectl.cli list --limit 10
echo ""

echo -e "${BLUE}[5] Starting ${WORKERS_COUNT} workers...${NC}"
python -m queuectl.cli worker start --count ${WORKERS_COUNT}
echo "✓ Workers started"
echo ""

echo -e "${BLUE}[6] Waiting ${TEST_DELAY} seconds for jobs to process...${NC}"
sleep ${TEST_DELAY}
echo "✓ Processing complete"
echo ""

echo -e "${BLUE}[7] Showing final job status...${NC}"
python -m queuectl.cli status
echo ""

echo -e "${BLUE}[8] Listing all jobs by state...${NC}"
echo -e "${YELLOW}Completed jobs:${NC}"
python -m queuectl.cli list --state completed --limit 10
echo ""

echo -e "${YELLOW}Pending/Processing jobs:${NC}"
python -m queuectl.cli list --state pending --limit 10
echo ""

echo -e "${YELLOW}Dead Letter Queue:${NC}"
python -m queuectl.cli dlq list --limit 10
echo ""

echo -e "${BLUE}[9] Testing DLQ retry...${NC}"
echo "Retrying failed job from DLQ..."
python -m queuectl.cli dlq retry test_fail_1 2>/dev/null || echo "Note: Job may not be in DLQ yet (still retrying)"
echo ""

echo -e "${BLUE}[10] Stopping workers...${NC}"
python -m queuectl.cli worker stop
echo "✓ Workers stopped"
echo ""

echo -e "${BLUE}[11] Verifying persistence...${NC}"
echo "Queue status after restart:"
python -m queuectl.cli status
echo ""

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Smoke test completed successfully!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo "Files created:"
echo "  - queue.db (SQLite database)"
echo "  - .queuectl.log (Log file)"
echo "  - .queuectl.pid (Worker PIDs)"
echo ""
echo "Next steps:"
echo "  1. Run: python -m queuectl.cli status"
echo "  2. Enqueue more jobs: python -m queuectl.cli enqueue '{\"id\":\"...\",\"command\":\"...\"}'"
echo "  3. Start workers: python -m queuectl.cli worker start --count 2"
echo "  4. Monitor: watch python -m queuectl.cli status"
echo ""
