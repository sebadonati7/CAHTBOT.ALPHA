# utils/id_manager.py - Atomic Session ID Generator with File Locking
"""
Thread-safe and process-safe session ID generator.

Implements atomic file locking to generate sequential daily IDs
in format: 0001_ddMMyy (e.g., 0042_090126 for 42nd session on Jan 9, 2026)

Features:
- Spin-lock with exponential backoff
- Automatic daily reset
- Stale lock cleanup (>30 seconds)
- Atomic file operations
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_LOCK_FILE = "data/id_gen.lock"
DEFAULT_STATE_FILE = "data/id_state.json"
LOCK_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 10
INITIAL_BACKOFF_MS = 10  # milliseconds


# ============================================================================
# CORE FUNCTION
# ============================================================================

def get_next_session_id(
    lock_file: str = DEFAULT_LOCK_FILE,
    state_file: str = DEFAULT_STATE_FILE
) -> str:
    """
    Generate next sequential session ID with atomic file locking.
    
    Algorithm:
    1. Acquire exclusive lock on lock_file (spin with backoff)
    2. Read current state from state_file
    3. Check if date changed → reset counter to 1
    4. Otherwise → increment counter
    5. Write new state atomically
    6. Release lock
    7. Return formatted ID: "0001_ddMMyy"
    
    Args:
        lock_file: Path to lock file (will be created/deleted)
        state_file: Path to state JSON file
    
    Returns:
        Formatted session ID string (e.g., "0042_090126")
    
    Raises:
        RuntimeError: If unable to acquire lock after max retries
    
    Example:
        >>> session_id = get_next_session_id()
        '0001_090126'
        >>> session_id = get_next_session_id()
        '0002_090126'
    """
    # Ensure data directory exists
    os.makedirs(os.path.dirname(lock_file), exist_ok=True)
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    
    # Current date in ddMMyy format
    current_date = datetime.now().strftime("%d%m%y")
    
    # Attempt to acquire lock with exponential backoff
    backoff_ms = INITIAL_BACKOFF_MS
    
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            # Try to create lock file atomically (exclusive creation)
            # O_CREAT | O_EXCL ensures atomic creation (fails if exists)
            lock_fd = os.open(
                lock_file,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644
            )
            
            try:
                # Write PID to lock file for debugging
                os.write(lock_fd, f"{os.getpid()}".encode())
                os.close(lock_fd)
                
                logger.debug(f"Lock acquired on attempt {attempt + 1}")
                
                # === CRITICAL SECTION START ===
                try:
                    # Read current state
                    state = _read_state(state_file)
                    
                    last_id = state.get("last_id", 0)
                    last_date = state.get("date", "")
                    
                    # Check if date changed → reset counter
                    if last_date != current_date:
                        logger.info(f"Date changed from {last_date} to {current_date}, resetting counter")
                        next_id = 1
                    else:
                        next_id = last_id + 1
                    
                    # Write new state atomically
                    new_state = {
                        "last_id": next_id,
                        "date": current_date,
                        "timestamp": datetime.now().isoformat()
                    }
                    _write_state(state_file, new_state)
                    
                    # Format ID: 0001_090126
                    formatted_id = f"{next_id:04d}_{current_date}"
                    
                    logger.info(f"Generated session ID: {formatted_id}")
                    
                    return formatted_id
                    
                finally:
                    # === CRITICAL SECTION END ===
                    # Release lock (delete lock file)
                    try:
                        os.remove(lock_file)
                        logger.debug("Lock released")
                    except OSError:
                        logger.warning(f"Failed to remove lock file: {lock_file}")
            
            except Exception as e:
                # Ensure lock is released on error
                os.close(lock_fd)
                try:
                    os.remove(lock_file)
                except:
                    pass
                raise e
        
        except FileExistsError:
            # Lock file exists - another process holds lock
            logger.debug(f"Lock held by another process, attempt {attempt + 1}/{MAX_RETRY_ATTEMPTS}")
            
            # Check if lock is stale (> 30 seconds old)
            if _is_lock_stale(lock_file, LOCK_TIMEOUT_SECONDS):
                logger.warning(f"Stale lock detected, removing: {lock_file}")
                try:
                    os.remove(lock_file)
                except OSError:
                    pass
                continue
            
            # Exponential backoff
            sleep_time = backoff_ms / 1000.0
            time.sleep(sleep_time)
            backoff_ms = min(backoff_ms * 2, 1000)  # Cap at 1 second
    
    # Failed to acquire lock after max retries
    raise RuntimeError(
        f"Failed to acquire lock after {MAX_RETRY_ATTEMPTS} attempts. "
        f"Lock file: {lock_file}"
    )


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _read_state(state_file: str) -> dict:
    """
    Read state from JSON file.
    
    Returns empty dict if file doesn't exist or is corrupted.
    """
    if not os.path.exists(state_file):
        return {}
    
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
            return state
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to read state file: {e}")
        return {}


def _write_state(state_file: str, state: dict) -> None:
    """
    Write state to JSON file atomically.
    
    Uses temp file + rename for atomic write.
    """
    temp_file = f"{state_file}.tmp"
    
    try:
        # Write to temp file
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
        
        # Atomic rename (overwrites existing file)
        os.replace(temp_file, state_file)
        
    except Exception as e:
        logger.error(f"Failed to write state file: {e}")
        # Clean up temp file
        try:
            os.remove(temp_file)
        except:
            pass
        raise


def _is_lock_stale(lock_file: str, timeout_seconds: int) -> bool:
    """
    Check if lock file is stale (older than timeout).
    
    Args:
        lock_file: Path to lock file
        timeout_seconds: Lock timeout in seconds
    
    Returns:
        True if lock is older than timeout
    """
    try:
        stat_info = os.stat(lock_file)
        age_seconds = time.time() - stat_info.st_mtime
        return age_seconds > timeout_seconds
    except OSError:
        return False


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.DEBUG)
    
    print("Testing ID generation...")
    for i in range(5):
        session_id = get_next_session_id()
        print(f"Generated: {session_id}")
        time.sleep(0.1)
    
    print("\nTest completed!")
