"""
QueueCTL - A CLI-based background job queue tool.
"""

__version__ = "1.0.0"
__author__ = "QueueCTL Team"

from queuectl.db import init_db
from queuectl.config import Config

__all__ = ["init_db", "Config"]
