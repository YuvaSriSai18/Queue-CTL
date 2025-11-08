"""
Configuration management for QueueCTL.
Stores and retrieves configuration from SQLite.
"""

from typing import Optional

from queuectl.db import get_db_connection
from queuectl.utils import get_logger

logger = get_logger(__name__)

# Default configuration values
DEFAULT_CONFIG = {
    "max_retries": "3",
    "backoff_base": "2",
    "max_backoff_seconds": "300",
    "lock_lease_seconds": "300",
    "job_timeout_seconds": "3600",  # 1 hour timeout for job execution
}


class Config:
    """Configuration manager for QueueCTL."""

    @staticmethod
    def get(key: str) -> Optional[str]:
        """
        Get a configuration value.

        Args:
            key: Configuration key.

        Returns:
            Configuration value or None if not set.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = cursor.fetchone()

        if row:
            return row[0]

        # Return default if exists
        return DEFAULT_CONFIG.get(key)

    @staticmethod
    def set(key: str, value: str) -> None:
        """
        Set a configuration value.

        Args:
            key: Configuration key.
            value: Configuration value.
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        # Try to update first
        cursor.execute("UPDATE config SET value = ? WHERE key = ?", (value, key))

        if cursor.rowcount == 0:
            # Insert if not exists
            cursor.execute("INSERT INTO config (key, value) VALUES (?, ?)", (key, value))

        conn.commit()
        logger.info(f"Config set: {key} = {value}")

    @staticmethod
    def get_all() -> dict:
        """Get all configuration as a dictionary."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM config")
        config = {row[0]: row[1] for row in cursor.fetchall()}

        # Merge with defaults
        for key, value in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = value

        return config

    @staticmethod
    def get_int(key: str) -> int:
        """Get a configuration value as integer."""
        value = Config.get(key)
        return int(value) if value else 0
