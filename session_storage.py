import os
import json
import time
from typing import Any, Dict, List, Optional

SESSIONS_DIR = os.environ.get("SESSION_STORAGE_DIR", "sessions")

class FileSessionStorage:
    """
    Semplice storage basato su file JSON nella cartella `sessions/`.
    Metodi:
      - load_session(session_id) -> dict | None
      - save_session(session_id, data) -> bool
      - delete_session(session_id) -> bool
      - list_active_sessions() -> List[Dict[str, Any]]
      - cleanup_old_sessions(max_age_hours) -> int (deleted count)
    """
    def __init__(self, base_dir: str = SESSIONS_DIR):
        self.base_dir = os.path.abspath(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)

    def _path(self, session_id: str) -> str:
        # semplice sanificazione del nome file
        safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_.")
        return os.path.join(self.base_dir, f"{safe_id}.json")

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        p = self._path(session_id)
        if not os.path.exists(p):
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def save_session(self, session_id: str, data: Dict[str, Any]) -> bool:
        p = self._path(session_id)
        try:
            # Scrittura atomica semplice: scrivi su file temporaneo e rinomina
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
            return True
        except Exception:
            return False

    def delete_session(self, session_id: str) -> bool:
        p = self._path(session_id)
        try:
            if os.path.exists(p):
                os.remove(p)
                return True
            return False
        except Exception:
            return False

    def list_active_sessions(self) -> List[Dict[str, Any]]:
        results = []
        for fn in os.listdir(self.base_dir):
            if fn.endswith(".json"):
                p = os.path.join(self.base_dir, fn)
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    results.append({
                        "session_id": fn[:-5],
                        "last_modified": time.ctime(os.path.getmtime(p)),
                        "snapshot": data
                    })
                except Exception:
                    continue
        return results

    def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        now = time.time()
        cutoff = now - max_age_hours * 3600
        deleted = 0
        for fn in os.listdir(self.base_dir):
            if fn.endswith(".json"):
                p = os.path.join(self.base_dir, fn)
                try:
                    if os.path.getmtime(p) < cutoff:
                        os.remove(p)
                        deleted += 1
                except Exception:
                    continue
        return deleted

# Factory function (usata dal backend_api.py)
_storage_singleton: Optional[FileSessionStorage] = None

def get_storage() -> FileSessionStorage:
    global _storage_singleton
    if _storage_singleton is None:
        _storage_singleton = FileSessionStorage()
    return _storage_singleton
