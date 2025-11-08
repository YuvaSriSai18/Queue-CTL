#!/usr/bin/env python3
"""
QueueCTL - Standalone CLI Tool
This is a wrapper that makes queuectl work as a standalone executable.

Run this as: python queuectl.py [COMMAND] [OPTIONS]
Or use the compiled queuectl.exe on Windows
"""

import sys
import os
from pathlib import Path

# Add current directory and parent to path so imports work
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

# Import the main CLI app
from queuectl.cli import app

if __name__ == "__main__":
    # Run the Typer app
    app()
