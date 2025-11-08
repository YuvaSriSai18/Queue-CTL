#!/usr/bin/env python
"""
Windows-compatible test script for QueueCTL
Run with: python tests/windows_test.py
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Add project root to Python path so queuectl module can be imported
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.environ['PYTHONPATH'] = str(project_root) + os.pathsep + os.environ.get('PYTHONPATH', '')

def run_command(cmd, use_shell=True):
    """Run a command and return output."""
    try:
        result = subprocess.run(
            cmd,
            shell=use_shell,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(project_root),
            env=os.environ.copy()
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timeout"
    except Exception as e:
        return -1, "", str(e)

def test_imports():
    """Test that all imports work."""
    print("[TEST] Testing imports...")
    try:
        from queuectl.cli import app
        from queuectl.db import init_db
        from queuectl.config import Config
        print("✓ All imports successful")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False

def test_cli_status():
    """Test CLI status command."""
    print("[TEST] Testing CLI status...")
    code, out, err = run_command(f"{sys.executable} -m queuectl.cli status")
    if code == 0:
        print("✓ Status command works")
        return True
    else:
        print(f"✗ Status failed: {err}")
        return False

def test_enqueue():
    """Test enqueue command."""
    print("[TEST] Testing enqueue...")
    job_json = json.dumps({
        "id": "test_job_1",
        "command": "echo test"
    })
    # Use subprocess with args list to avoid shell quoting issues on Windows
    result = subprocess.run(
        [sys.executable, "-m", "queuectl.cli", "enqueue", job_json],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(project_root),
        env=os.environ.copy()
    )
    code, out, err = result.returncode, result.stdout, result.stderr
    if code == 0 and "enqueued" in out.lower():
        print("✓ Enqueue works")
        return True
    else:
        # Print both stdout and stderr for debugging
        print(f"✗ Enqueue failed (code={code})")
        if out:
            print(f"  stdout: {out}")
        if err:
            print(f"  stderr: {err}")
        return False

def test_list():
    """Test list command."""
    print("[TEST] Testing list...")
    code, out, err = run_command(f"{sys.executable} -m queuectl.cli list --limit 5")
    if code == 0:
        print("✓ List works")
        return True
    else:
        print(f"✗ List failed: {err}")
        return False

def test_config():
    """Test config commands."""
    print("[TEST] Testing config...")
    
    # Test get
    result = subprocess.run(
        [sys.executable, "-m", "queuectl.cli", "config", "get", "max_retries"],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(project_root),
        env=os.environ.copy()
    )
    code, out, err = result.returncode, result.stdout, result.stderr
    if code == 0:
        print("✓ Config get works")
        
        # Test set
        result = subprocess.run(
            [sys.executable, "-m", "queuectl.cli", "config", "set", "test_key", "test_value"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(project_root),
            env=os.environ.copy()
        )
        code, out, err = result.returncode, result.stdout, result.stderr
        if code == 0:
            print("✓ Config set works")
            return True
        else:
            print(f"✗ Config set failed: {err}")
            return False
    else:
        print(f"✗ Config get failed: {err}")
        return False

def test_worker():
    """Test worker commands."""
    print("[TEST] Testing worker start...")
    
    # Start worker with Popen to avoid blocking
    import subprocess as sp
    try:
        # Start in background using Popen
        proc = sp.Popen(
            [sys.executable, "-m", "queuectl.cli", "worker", "start", "--count", "1"],
            stdout=sp.PIPE,
            stderr=sp.PIPE,
            text=True,
            cwd=str(project_root),
            env=os.environ.copy()
        )
        
        # Give it a moment to start
        time.sleep(2)
        
        # Check if still running
        if proc.poll() is None or proc.returncode == 0:
            print("✓ Worker start works")
            
            # Stop workers
            print("[TEST] Testing worker stop...")
            result = subprocess.run(
                [sys.executable, "-m", "queuectl.cli", "worker", "stop"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(project_root),
                env=os.environ.copy()
            )
            code, out, err = result.returncode, result.stdout, result.stderr
            
            # Terminate the worker process
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except:
                proc.kill()
                proc.wait()
            
            if code == 0 or "stop" in out.lower() or "No worker" in out:
                print("✓ Worker stop works")
                return True
            else:
                print(f"✗ Worker stop failed: {err}")
                return False
        else:
            out, err = proc.communicate()
            print(f"✗ Worker start failed: {err}")
            return False
    except Exception as e:
        print(f"✗ Worker test error: {e}")
        return False

def main():
    """Run all tests."""
    print("=" * 60)
    print("QueueCTL Windows Compatibility Test")
    print("=" * 60)
    print()
    
    tests = [
        test_imports,
        test_cli_status,
        test_enqueue,
        test_list,
        test_config,
        test_worker,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"✗ Test error: {e}")
            results.append(False)
        print()
    
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())
