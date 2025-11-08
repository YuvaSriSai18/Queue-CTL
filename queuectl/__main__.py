"""
Entry point for running queuectl as a module: python -m queuectl

This allows the package to be run as:
  python -m queuectl.cli <command>
  python -m queuectl <command>
"""

import sys
from queuectl.cli import main

if __name__ == "__main__":
    main()
