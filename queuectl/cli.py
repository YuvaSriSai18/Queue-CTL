"""
CLI commands using Typer and Rich for user-friendly interface.
"""

import json
import os
import signal
import sys
import time
import uuid
from multiprocessing import Process
from pathlib import Path
from typing import Optional

# Fix imports to work when running from any directory
# Add parent directory to path so 'queuectl' package can be found
_current_dir = Path(__file__).parent
_parent_dir = _current_dir.parent
if str(_parent_dir) not in sys.path:
    sys.path.insert(0, str(_parent_dir))

import typer
from rich.console import Console
from rich.table import Table

from queuectl.config import Config
from queuectl.db import (
    get_job,
    get_job_counts,
    init_db,
    insert_job,
    list_dlq,
    list_jobs,
    requeue_from_dlq,
)
from queuectl.scheduler import cleanup_expired_locks, move_ready_jobs_to_pending
from queuectl.utils import get_logger, get_pid_file
from queuectl.worker import start_worker

app = typer.Typer(help="QueueCTL - A CLI-based background job queue tool.")
console = Console()
logger = get_logger(__name__)


@app.callback()
def init_app() -> None:
    """Initialize the app (runs before any command)."""
    init_db()


# ============================================================================
# ENQUEUE COMMANDS
# ============================================================================


@app.command()
def enqueue(
    job_json: str = typer.Argument(
        None, help='Job JSON, e.g. \'{"id":"job1","command":"sleep 2"}\''
    ),
    job_id: str = typer.Option(None, "--id", help="Job ID"),
    command: str = typer.Option(None, "--command", help="Command to execute"),
    max_retries: int = typer.Option(None, "--retries", help="Max retries"),
    priority: int = typer.Option(0, "--priority", help="Priority (0-10, higher = urgent)"),
    run_at: str = typer.Option(None, "--run-at", help="ISO timestamp for scheduled execution (e.g., 2025-11-08T15:30:00)"),
) -> None:
    """
    Enqueue a new job with optional priority and scheduling.

    Examples:
        queuectl enqueue '{"id":"job1","command":"sleep 2"}'
        queuectl enqueue --id job1 --command "echo hello"
        queuectl enqueue --id job2 --command "echo urgent" --priority 10
        queuectl enqueue --id job3 --command "echo later" --run-at "2025-11-08T15:30:00"
    """
    # Support both JSON and individual arguments
    if job_json:
        try:
            job_data = json.loads(job_json)
        except json.JSONDecodeError:
            console.print("[red]Error: Invalid JSON format[/red]")
            raise typer.Exit(1)
        final_id = job_data.get("id") or str(uuid.uuid4())
        final_command = job_data.get("command")
        final_retries = job_data.get("max_retries", Config.get_int("max_retries"))
        final_priority = job_data.get("priority", 0)
        final_run_at = job_data.get("run_at")
    else:
        if not job_id or not command:
            console.print("[red]Error: Either provide JSON or use --id and --command[/red]")
            raise typer.Exit(1)
        final_id = job_id
        final_command = command
        final_retries = max_retries or Config.get_int("max_retries")
        final_priority = priority
        final_run_at = run_at

    if not final_command:
        console.print("[red]Error: 'command' field is required[/red]")
        raise typer.Exit(1)

    # Validate priority
    if not (0 <= final_priority <= 10):
        console.print("[red]Error: Priority must be between 0 and 10[/red]")
        raise typer.Exit(1)

    try:
        insert_job(final_id, final_command, final_retries, final_priority, final_run_at)
        status = f"[green]Job {final_id} enqueued successfully."
        if final_priority > 0:
            status += f" (priority={final_priority})"
        if final_run_at:
            status += f" (scheduled for {final_run_at})"
        status += "[/green]"
        console.print(status)
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


# ============================================================================
# WORKER COMMANDS
# ============================================================================

worker_app = typer.Typer(help="Manage worker processes.")
app.add_typer(worker_app, name="worker")


@worker_app.command(name="start")
def start(
    count: int = typer.Option(1, "--count", help="Number of worker processes to start."),
) -> None:
    """
    Start worker processes.

    Example:
        queuectl worker start --count 2
    """
    if count < 1:
        console.print("[red]Error: count must be >= 1[/red]")
        raise typer.Exit(1)

    pid_file = get_pid_file()
    pids = []

    console.print(f"[cyan]Starting {count} worker(s)...[/cyan]")

    for i in range(count):
        try:
            process = Process(target=start_worker, args=(i,))
            process.start()
            pids.append(process.pid)
            console.print(f"[green]Worker {i} started with PID {process.pid}[/green]")
        except Exception as e:
            console.print(f"[red]Error starting worker {i}: {e}[/red]")
            raise typer.Exit(1)

    # Save PIDs to file
    try:
        existing_pids = []
        if pid_file.exists():
            existing_pids = [int(x) for x in pid_file.read_text().strip().split("\n") if x]

        all_pids = existing_pids + pids
        pid_file.write_text("\n".join(str(p) for p in all_pids))
        console.print(f"[cyan]Worker PIDs saved to {pid_file}[/cyan]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not save PIDs: {e}[/yellow]")

    console.print("[green]All workers started.[/green]")


@worker_app.command(name="stop")
def stop() -> None:
    """
    Stop all worker processes gracefully.

    Example:
        queuectl worker stop
    """
    pid_file = get_pid_file()

    if not pid_file.exists():
        console.print("[yellow]No worker PIDs file found.[/yellow]")
        return

    try:
        pids = [int(x) for x in pid_file.read_text().strip().split("\n") if x]
    except Exception as e:
        console.print(f"[red]Error reading PIDs file: {e}[/red]")
        raise typer.Exit(1)

    if not pids:
        console.print("[yellow]No worker processes to stop.[/yellow]")
        pid_file.unlink(missing_ok=True)
        return

    console.print(f"[cyan]Stopping {len(pids)} worker(s)...[/cyan]")

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            console.print(f"[green]Sent SIGTERM to worker PID {pid}[/green]")
        except ProcessLookupError:
            console.print(f"[yellow]Worker PID {pid} not found (already stopped?)[/yellow]")
        except Exception as e:
            console.print(f"[red]Error stopping PID {pid}: {e}[/red]")

    # Wait a bit for graceful shutdown
    console.print("[cyan]Waiting for workers to shut down gracefully...[/cyan]")
    time.sleep(2)

    # Force kill if necessary
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    # Clear PID file
    pid_file.unlink(missing_ok=True)
    console.print("[green]All workers stopped.[/green]")


# ============================================================================
# STATUS & LIST COMMANDS
# ============================================================================


@app.command()
def status() -> None:
    """
    Show queue status: job counts per state and active worker PIDs.

    Example:
        queuectl status
    """
    # Move ready jobs to pending and cleanup locks
    move_ready_jobs_to_pending()
    cleanup_expired_locks(Config.get_int("lock_lease_seconds"))

    # Get job counts
    counts = get_job_counts()

    # Display job counts
    console.print("[cyan]Job Counts:[/cyan]")
    table = Table(title="Job Status", show_header=True, header_style="bold magenta")
    table.add_column("State", style="cyan")
    table.add_column("Count", justify="right", style="green")

    for state in ["pending", "processing", "completed", "failed", "dead"]:
        count = counts.get(state, 0)
        table.add_row(state, str(count))

    console.print(table)

    # Display active workers
    pid_file = get_pid_file()
    if pid_file.exists():
        try:
            pids = [int(x) for x in pid_file.read_text().strip().split("\n") if x]
            console.print(f"\n[cyan]Active Workers: {', '.join(str(p) for p in pids)}[/cyan]")
        except Exception as e:
            console.print(f"[yellow]Could not read worker PIDs: {e}[/yellow]")
    else:
        console.print("\n[yellow]No active workers.[/yellow]")


@app.command()
def list(
    state: Optional[str] = typer.Option(
        None, "--state", help="Filter by state (pending/processing/completed/failed/dead)."
    ),
    limit: int = typer.Option(100, "--limit", help="Maximum number of jobs to list."),
) -> None:
    """
    List jobs, optionally filtered by state.

    Example:
        queuectl list --state pending
        queuectl list --limit 50
    """
    jobs = list_jobs(state, limit)

    if not jobs:
        console.print("[yellow]No jobs found.[/yellow]")
        return

    table = Table(title=f"Jobs (Total: {len(jobs)})", show_header=True, header_style="bold magenta")
    table.add_column("Job ID", style="cyan", no_wrap=True)
    table.add_column("State", style="green")
    table.add_column("Priority", justify="right", style="yellow")
    table.add_column("Attempts", justify="right", style="yellow")
    table.add_column("Command", style="white", no_wrap=False)
    table.add_column("Scheduled At", style="magenta", no_wrap=True)
    table.add_column("Retry At", style="magenta", no_wrap=True)

    for job in jobs:
        scheduled = job.get("run_at") or "-"
        retry_at = job.get("retry_at") or "-"
        priority = job.get("priority", 0)
        # Truncate long commands
        command = job["command"]
        if len(command) > 40:
            command = command[:37] + "..."
        table.add_row(
            job["id"],
            job["state"],
            str(priority),
            str(job["attempts"]),
            command,
            scheduled,
            retry_at,
        )

    console.print(table)


# ============================================================================
# DLQ COMMANDS
# ============================================================================

dlq_app = typer.Typer(help="Manage Dead Letter Queue.")
app.add_typer(dlq_app, name="dlq")


@dlq_app.command(name="list")
def dlq_list(limit: int = typer.Option(100, "--limit", help="Maximum number of DLQ items to list.")) -> None:
    """
    List jobs in Dead Letter Queue.

    Example:
        queuectl dlq list
        queuectl dlq list --limit 50
    """
    dlq_items = list_dlq(limit)

    if not dlq_items:
        console.print("[yellow]No items in DLQ.[/yellow]")
        return

    table = Table(title=f"Dead Letter Queue (Total: {len(dlq_items)})", show_header=True, header_style="bold magenta")
    table.add_column("Job ID", style="cyan", no_wrap=True)
    table.add_column("Moved At", style="yellow", no_wrap=True)
    table.add_column("Reason", style="red", no_wrap=False)

    for item in dlq_items:
        reason = item["reason"]
        if len(reason) > 60:
            reason = reason[:57] + "..."
        table.add_row(item["job_id"], item["moved_at"], reason)

    console.print(table)


@dlq_app.command(name="retry")
def dlq_retry(job_id: str = typer.Argument(..., help="Job ID to retry from DLQ.")) -> None:
    """
    Retry a job from Dead Letter Queue.

    Example:
        queuectl dlq retry job123
    """
    if requeue_from_dlq(job_id):
        console.print(f"[green]Job {job_id} requeued successfully.[/green]")
    else:
        console.print(f"[red]Job {job_id} not found in DLQ.[/red]")
        raise typer.Exit(1)


# ============================================================================
# OUTPUT COMMANDS
# ============================================================================

output_app = typer.Typer(help="View job output.")
app.add_typer(output_app, name="output")


@output_app.command(name="get")
def output_get(job_id: str = typer.Argument(..., help="Job ID to view output for.")) -> None:
    """
    View captured output from a completed job.

    Example:
        queuectl output get job123
    """
    from queuectl.db import get_job_output
    
    output_data = get_job_output(job_id)
    if output_data is None:
        console.print(f"[yellow]No output found for job '{job_id}'.[/yellow]")
        raise typer.Exit(1)
    
    stdout_log = output_data.get("stdout_log") or ""
    stderr_log = output_data.get("stderr_log") or ""
    exit_code = output_data.get("exit_code")
    completed_at = output_data.get("completed_at") or "N/A"
    
    console.print(f"\n[cyan]Job Output: {job_id}[/cyan]")
    console.print(f"[dim]Completed at: {completed_at}[/dim]")
    console.print(f"[dim]Exit code: {exit_code}[/dim]")
    
    if stdout_log:
        console.print("\n[bold green]STDOUT:[/bold green]")
        console.print(stdout_log)
    
    if stderr_log:
        console.print("\n[bold red]STDERR:[/bold red]")
        console.print(stderr_log)
    
    if not stdout_log and not stderr_log:
        console.print("[dim]No output captured.[/dim]")
    
    console.print()


# ============================================================================
# CONFIG COMMANDS
# ============================================================================

config_app = typer.Typer(help="Manage configuration.")
app.add_typer(config_app, name="config")


@config_app.command(name="get")
def config_get(key: str = typer.Argument(..., help="Configuration key.")) -> None:
    """
    Get a configuration value.

    Example:
        queuectl config get max_retries
        queuectl config get backoff_base
    """
    value = Config.get(key)
    if value is None:
        console.print(f"[yellow]Key '{key}' not found.[/yellow]")
        raise typer.Exit(1)

    console.print(f"[cyan]{key}[/cyan] = [green]{value}[/green]")


@config_app.command(name="set")
def config_set(
    key: str = typer.Argument(..., help="Configuration key."),
    value: str = typer.Argument(..., help="Configuration value."),
) -> None:
    """
    Set a configuration value.

    Example:
        queuectl config set max_retries 5
        queuectl config set backoff_base 3
    """
    try:
        Config.set(key, value)
        console.print(f"[green]Configuration updated: {key} = {value}[/green]")
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
