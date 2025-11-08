"""
Subprocess execution logic for job commands.
"""

import subprocess
from pathlib import Path
from typing import Tuple

from queuectl.config import Config
from queuectl.utils import get_logger

logger = get_logger(__name__)


def execute_command(command: str, output_path: str = None) -> Tuple[int, str, str]:
    """
    Execute a shell command and return exit code, stdout, stderr.

    Args:
        command: Shell command to execute.
        output_path: Optional path to save output.

    Returns:
        Tuple of (exit_code, stdout, stderr).
    """
    try:
        # Get timeout from configuration (default 1 hour)
        timeout = Config.get_int("job_timeout_seconds")
        if timeout <= 0:
            timeout = 3600  # Fall back to 1 hour if config is invalid
        
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        stdout = result.stdout
        stderr = result.stderr
        exit_code = result.returncode

        # Save output if path provided
        if output_path:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, "w") as f:
                f.write(f"=== STDOUT ===\n{stdout}\n")
                f.write(f"=== STDERR ===\n{stderr}\n")
                f.write(f"=== EXIT CODE ===\n{exit_code}\n")

        logger.info(
            f"Command executed: '{command}' (exit_code={exit_code}, "
            f"stdout_len={len(stdout)}, stderr_len={len(stderr)})"
        )

        return exit_code, stdout, stderr

    except subprocess.TimeoutExpired as e:
        error_msg = f"Command timeout: {command}"
        logger.error(error_msg)
        return -1, "", error_msg

    except Exception as e:
        error_msg = f"Command execution error: {str(e)}"
        logger.error(error_msg)
        return -1, "", error_msg
