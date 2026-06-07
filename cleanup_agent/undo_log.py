"""Per-session undo log: every move review.py makes appends a {"from", "to"}
entry. start_session() wipes any previous session, so you can only undo the
most recent run — keeps the data model simple and the undo behavior
predictable."""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = PROJECT_ROOT / "undo_log.json"


class UndoLog:
    def __init__(self, path=None):
        self.path = Path(path) if path else DEFAULT_LOG_PATH
        self.entries = []

    def start_session(self):
        """Wipe any previous session's entries. Call once at the start of
        a review run, before the first move."""
        self.entries = []
        self._write()

    def add(self, src, dst):
        self.entries.append({"from": str(src), "to": str(dst)})
        self._write()

    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, indent=2))
