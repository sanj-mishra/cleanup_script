#!/usr/bin/env python3
"""One-time bootstrap: records every file currently in ~/Downloads and
~/Desktop as 'known' so future scans only flag genuinely new files.

Safe to re-run — existing entries are left untouched."""
import argparse
from pathlib import Path

from cleanup_agent.db import connect, init_schema
from cleanup_agent.scan import record_new_files

WATCHED_DIRS = [Path.home() / "Downloads", Path.home() / "Desktop"]


def bootstrap(conn, watched_dirs=WATCHED_DIRS):
    """Mark every top-level file in `watched_dirs` as 'known'.
    Returns (added, already_known, missing_dirs)."""
    init_schema(conn)
    return record_new_files(conn, watched_dirs, decision="known")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", help="Path to SQLite DB (default: <project>/seen.db)"
    )
    parser.add_argument(
        "--watch", action="append",
        help="Override watched directory (repeatable). Default: ~/Downloads + ~/Desktop"
    )
    args = parser.parse_args()
    watched = (
        [Path(w).expanduser() for w in args.watch] if args.watch else WATCHED_DIRS
    )
    conn = connect(args.db)
    try:
        added, already_known, missing = bootstrap(conn, watched_dirs=watched)
    finally:
        conn.close()
    print(
        f"bootstrap complete: {added} added, {already_known} already known, "
        f"{missing} watched dirs missing"
    )


if __name__ == "__main__":
    main()
