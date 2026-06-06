"""SQLite connection + schema helpers, shared by every script in cleanup-agent."""
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "seen.db"

# decision values:
#   'known'    — was already in ~/Downloads or ~/Desktop when bootstrap ran
#   'pending'  — discovered later, awaiting review
#   'approved' — user said yes in review.py; file was moved
#   'rejected' — user said no in review.py; file stays put
SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_files (
    path TEXT PRIMARY KEY,
    first_seen DATE NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('known', 'pending', 'approved', 'rejected'))
);
"""


def connect(db_path=None):
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def init_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()
