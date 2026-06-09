#!/usr/bin/env python3
"""Reverse the most recent review.py session's moves.

Reads undo_log.json (review.py overwrites it at session start, so it
holds only the latest run). For each entry, moves the file back to its
original location. After a successful undo, the log is wiped.

Dry-run by default. Add --apply to actually reverse the moves."""
import argparse
import json
import sys
from pathlib import Path

from cleanup_agent.db import connect, init_schema
from cleanup_agent.mover import perform_move
from cleanup_agent.undo_log import DEFAULT_LOG_PATH


def undo(conn, log_path, dry_run=True):
    """Walk the undo log in reverse and move each file back.
    Returns (undone, skipped)."""
    log_path = Path(log_path)
    if not log_path.exists():
        print("No undo log found — nothing to undo.")
        return 0, 0
    entries = json.loads(log_path.read_text())
    if not entries:
        print("Undo log is empty — nothing to undo.")
        return 0, 0

    undone = 0
    skipped = 0

    # Iterate in reverse: later moves may have computed collision suffixes
    # that depended on earlier moves' destination state. Undoing in the
    # opposite order keeps the filesystem state consistent at each step.
    for entry in reversed(entries):
        moved_to = Path(entry["to"])
        original = Path(entry["from"])

        if not moved_to.exists():
            print(
                f"  skip: {moved_to} no longer exists "
                f"(deleted or moved manually)",
                file=sys.stderr,
            )
            skipped += 1
            continue

        try:
            # If the original path is now occupied (e.g. user re-downloaded),
            # perform_move adds a timestamp suffix instead of overwriting —
            # same collision logic as the forward move.
            final = perform_move(moved_to, original.parent, dry_run=dry_run)
        except OSError as e:
            print(
                f"  error: {moved_to} → {original.parent}: {e}",
                file=sys.stderr,
            )
            skipped += 1
            continue

        if dry_run:
            print(f"  would restore: {moved_to} → {final}")
        else:
            # DB: row that pointed at moved_to now points at final, decision
            # flips back to 'pending' so next review surfaces it again.
            conn.execute(
                "UPDATE seen_files SET path=?, decision='pending' "
                "WHERE path=?",
                (str(final), str(moved_to)),
            )
            conn.commit()
            print(f"  restored: {moved_to} → {final}")
        undone += 1

    if not dry_run and undone > 0:
        # Wipe the log — once undone, can't be undone again.
        log_path.write_text("[]")

    return undone, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="Path to SQLite DB")
    parser.add_argument(
        "--log",
        help=f"Path to undo log (default: {DEFAULT_LOG_PATH})",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually reverse the moves (default: dry-run)",
    )
    args = parser.parse_args()

    log_path = args.log or DEFAULT_LOG_PATH
    conn = connect(args.db)
    try:
        init_schema(conn)
        undone, skipped = undo(conn, log_path, dry_run=not args.apply)
    finally:
        conn.close()

    if args.apply:
        print(f"\nundo complete: {undone} restored, {skipped} skipped")
    else:
        print(f"\ndry-run: would restore {undone}, skip {skipped}")
        print("(re-run with --apply to actually undo)")


if __name__ == "__main__":
    main()
