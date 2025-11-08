"""
Quick test to verify basic functionality works
Run with: python tests/test_basic.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.environ['PYTHONPATH'] = str(project_root) + os.pathsep + os.environ.get('PYTHONPATH', '')

# Test imports
try:
    from queuectl.cli import app
    from queuectl.db import init_db, insert_job, list_jobs
    from queuectl.config import Config
    from queuectl.utils import calculate_backoff
    print("✓ All imports successful")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    exit(1)

# Test database
try:
    init_db()
    insert_job("test_1", "echo hello")
    jobs = list_jobs()
    assert len(jobs) > 0
    print("✓ Database operations work")
except Exception as e:
    print(f"✗ Database test failed: {e}")
    exit(1)

# Test config
try:
    Config.set("test_key", "test_value")
    assert Config.get("test_key") == "test_value"
    print("✓ Configuration works")
except Exception as e:
    print(f"✗ Config test failed: {e}")
    exit(1)

# Test backoff
try:
    assert calculate_backoff(0, base=2) == 1
    assert calculate_backoff(1, base=2) == 2
    assert calculate_backoff(2, base=2) == 4
    print("✓ Backoff calculation works")
except Exception as e:
    print(f"✗ Backoff test failed: {e}")
    exit(1)

print("\n✓ All basic tests passed!")
