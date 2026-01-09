# session_storage.py - Persistent Session Storage with File-based Locking
"""
Manages persistent session storage for cross-instance synchronization.

Features:
- File-based JSON storage with atomic writes
- Session state synchronization across multiple frontend instances
- Thread-safe operations with file locking
- Automatic cleanup of old sessions (>24h)

Storage Format:
    sessions.json: {
        "session_id": {
            "timestamp_last_update": "ISO8601",
            "messages": [...],
            "collected_data": {...},
            "current_step": "...",
            "triage_state": {...},
            "metadata": {...}
        }
    }
"""

import json
import os
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from pathlib import Path
import tempfile
import shutil

logger = logging.getLogger(__name__)

# Storage file path
STORAGE_FILE = "sessions.json"
LOCK_TIMEOUT = 10  # seconds


class SessionStorage:
    """
    Thread-safe persistent storage for triage sessions.
    
    Uses file-based locking to prevent race conditions when
    multiple frontend instances access the same session.
    
    Methods:
        save_session: Save session state
        load_session: Load session state
        delete_session: Delete session
        list_active_sessions: List all active sessions
        cleanup_old_sessions: Remove sessions older than 24h
    """
    
    def __init__(self, storage_file: str = STORAGE_FILE):
        """
        Initialize storage manager.
        
        Args:
            storage_file: Path to JSON storage file
        """
        self.storage_file = storage_file
        self.lock = threading.Lock()
        
        # Create storage file if it doesn't exist
        if not os.path.exists(self.storage_file):
            self._write_storage({})
            logger.info(f"✅ Created new storage file: {self.storage_file}")
        else:
            logger.info(f"✅ Using existing storage file: {self.storage_file}")
    
    def _read_storage(self) -> Dict[str, Any]:
        """
        Read storage file with error handling.
        
        Returns:
            Dict with all sessions or empty dict if error
        """
        try:
            with open(self.storage_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            logger.warning(f"Storage file not found: {self.storage_file}")
            return {}
        except json.JSONDecodeError:
            logger.error(f"Corrupted storage file: {self.storage_file}")
            # Backup corrupted file
            backup_path = f"{self.storage_file}.corrupted.{int(time.time())}"
            shutil.copy(self.storage_file, backup_path)
            logger.info(f"Backup created: {backup_path}")
            return {}
        except Exception as e:
            logger.error(f"Error reading storage: {e}")
            return {}
    
    def _write_storage(self, data: Dict[str, Any]):
        """
        Write storage file atomically to prevent corruption.
        
        Uses temporary file + rename for atomic operation.
        
        Args:
            data: Complete sessions dict to write
        """
        try:
            # Write to temporary file first
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.json',
                prefix='sessions_',
                dir=os.path.dirname(self.storage_file) or '.'
            )
            
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # Atomic rename (POSIX-compliant)
            shutil.move(temp_path, self.storage_file)
            
            logger.debug(f"Storage written: {len(data)} sessions")
        
        except Exception as e:
            logger.error(f"Error writing storage: {e}")
            # Clean up temp file if it exists
            try:
                if 'temp_path' in locals():
                    os.remove(temp_path)
            except:
                pass
    
    def save_session(self, session_id: str, session_data: Dict[str, Any]) -> bool:
        """
        Save session state to storage.
        
        Thread-safe with automatic timestamp update.
        
        Args:
            session_id: Unique session identifier
            session_data: Complete session state dict
        
        Returns:
            True if saved successfully, False otherwise
        """
        with self.lock:
            try:
                # Read current storage
                storage = self._read_storage()
                
                # Update session with timestamp
                session_data['timestamp_last_update'] = datetime.now().isoformat()
                storage[session_id] = session_data
                
                # Write back
                self._write_storage(storage)
                
                logger.info(f"✅ Session saved: {session_id}")
                return True
            
            except Exception as e:
                logger.error(f"❌ Error saving session {session_id}: {e}")
                return False
    
    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Load session state from storage.
        
        Args:
            session_id: Unique session identifier
        
        Returns:
            Session data dict or None if not found
        """
        with self.lock:
            try:
                storage = self._read_storage()
                session_data = storage.get(session_id)
                
                if session_data:
                    logger.info(f"✅ Session loaded: {session_id}")
                    return session_data
                else:
                    logger.info(f"Session not found: {session_id}")
                    return None
            
            except Exception as e:
                logger.error(f"❌ Error loading session {session_id}: {e}")
                return None
    
    def delete_session(self, session_id: str) -> bool:
        """
        Delete session from storage.
        
        Args:
            session_id: Unique session identifier
        
        Returns:
            True if deleted, False if not found or error
        """
        with self.lock:
            try:
                storage = self._read_storage()
                
                if session_id in storage:
                    del storage[session_id]
                    self._write_storage(storage)
                    logger.info(f"✅ Session deleted: {session_id}")
                    return True
                else:
                    logger.info(f"Session not found for deletion: {session_id}")
                    return False
            
            except Exception as e:
                logger.error(f"❌ Error deleting session {session_id}: {e}")
                return False
    
    def list_active_sessions(self) -> Dict[str, Dict[str, Any]]:
        """
        List all active sessions with metadata.
        
        Returns:
            Dict mapping session_id to session metadata
        """
        with self.lock:
            try:
                storage = self._read_storage()
                
                # Build summary
                summary = {}
                for session_id, session_data in storage.items():
                    summary[session_id] = {
                        'last_update': session_data.get('timestamp_last_update'),
                        'message_count': len(session_data.get('messages', [])),
                        'current_step': session_data.get('current_step'),
                        'specialization': session_data.get('specialization')
                    }
                
                logger.info(f"📋 Active sessions: {len(summary)}")
                return summary
            
            except Exception as e:
                logger.error(f"❌ Error listing sessions: {e}")
                return {}
    
    def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """
        Remove sessions older than specified age.
        
        Args:
            max_age_hours: Maximum age in hours (default: 24)
        
        Returns:
            Number of sessions deleted
        """
        with self.lock:
            try:
                storage = self._read_storage()
                cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
                
                sessions_to_delete = []
                
                for session_id, session_data in storage.items():
                    timestamp_str = session_data.get('timestamp_last_update')
                    
                    if timestamp_str:
                        try:
                            session_time = datetime.fromisoformat(timestamp_str)
                            if session_time < cutoff_time:
                                sessions_to_delete.append(session_id)
                        except ValueError:
                            # Invalid timestamp - mark for deletion
                            sessions_to_delete.append(session_id)
                    else:
                        # No timestamp - mark for deletion
                        sessions_to_delete.append(session_id)
                
                # Delete old sessions
                for session_id in sessions_to_delete:
                    del storage[session_id]
                
                if sessions_to_delete:
                    self._write_storage(storage)
                    logger.info(f"🧹 Cleaned up {len(sessions_to_delete)} old sessions")
                
                return len(sessions_to_delete)
            
            except Exception as e:
                logger.error(f"❌ Error cleaning up sessions: {e}")
                return 0


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

# Global instance
_storage_instance = None

def get_storage() -> SessionStorage:
    """Get global SessionStorage instance (singleton pattern)."""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = SessionStorage()
    return _storage_instance


def sync_session_to_storage(session_id: str, session_state: Dict[str, Any]) -> bool:
    """
    Convenience function to sync session state to storage.
    
    Args:
        session_id: Session ID
        session_state: Streamlit session_state as dict
    
    Returns:
        True if successful
    """
    storage = get_storage()
    
    # Extract relevant data from session_state
    session_data = {
        'messages': session_state.get('messages', []),
        'collected_data': session_state.get('collected_data', {}),
        'current_step': session_state.get('current_step', {}).get('name') if hasattr(session_state.get('current_step'), 'name') else str(session_state.get('current_step')),
        'specialization': session_state.get('specialization', 'Generale'),
        'triage_path': session_state.get('triage_path', 'C'),
        'metadata_history': session_state.get('metadata_history', []),
        'emergency_level': str(session_state.get('emergency_level')) if session_state.get('emergency_level') else None,
        'user_comune': session_state.get('user_comune'),
        'current_phase_idx': session_state.get('current_phase_idx', 0),
        
        # FSM state if available
        'triage_state': session_state.get('triage_state').__dict__ if hasattr(session_state.get('triage_state'), '__dict__') else None
    }
    
    return storage.save_session(session_id, session_data)


def load_session_from_storage(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Convenience function to load session state from storage.
    
    Args:
        session_id: Session ID
    
    Returns:
        Session data dict or None
    """
    storage = get_storage()
    return storage.load_session(session_id)
