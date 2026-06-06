#!/usr/bin/env python3
"""One-time bootstrap: records every file currently in ~/Downloads and
~/Desktop as 'known' so future scans only flag genuinely new files.

Safe to re-run — existing entries are left untouched and any files that
appeared since the last run are recorded as 'known' too. (After Phase 2,
notify.py / review.py will be what surfaces *new* files; bootstrap is just
the baseline.)"""
import argparse
import datetime as dt
import sys
from pathlib import Path

from cleanup_agent.db import connect, init_schema
from cleanup_agent.scanner import scan_top_level

WATCHED_DIRS = [Path.home() / "Downloads", Path.home() / "Desktop"]

FDA_HINT = (
    "Permission denied reading {path}. On macOS, grant your terminal Full Disk "
    "Access: System Settings → Privacy & Security → Full Disk Access → add and "
    "enable your terminal app, then restart it."
)


def bootstrap(conn, watched_dirs=WATCHED_DIRS):
    """Scan each watched directory and insert any new file paths as 'known'.
    Returns (added, already_known, missing_dirs)."""
    init_schema(conn)
    today = dt.date.today().isoformat()
    added = 0
    already_known = 0
    missing_dirs = 0

    for d in watched_dirs:
        if not d.exists():
            missing_dirs += 1
            print(f"warning: {d} does not exist, skipping", file=sys.stderr)
            continue
        try:
            files = list(scan_top_level(d))
        except PermissionError:
            print("error: " + FDA_HINT.format(path=d), file=sys.stderr)
            raise SystemExit(2)
        for f in files:
            cur = conn.execute(
                "INSERT OR IGNORE INTO seen_files (path, first_seen, decision) "
                "VALUES (?, ?, 'known')",
                (str(f), today),
            )
            if cur.rowcount == 1:
                added += 1
            else:
                already_known += 1
    conn.commit()
    return added, already_known, missing_dirs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", help="Path to SQLite DB (default: <project>/seen.db)"
    )
    args = parser.parse_args()
    conn = connect(args.db)
    try:
        added, already_known, missing = bootstrap(conn)
    finally:
        conn.close()
    print(
        f"bootstrap complete: {added} added, {already_known} already known, "
        f"{missing} watched dirs missing"
    )


if __name__ == "__main__":
    main()
