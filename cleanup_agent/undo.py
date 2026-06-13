#!/usr/bin/env python3
"""Reverse the most recent review.py session's moves.

Reads undo_log.json (review.py overwrites it at session start, so it
holds only the latest run). For each entry, moves the file back to its
original location. After a successful undo, the log is wiped.

Reverses the moves by default. Add --dry-run to preview without touching
any files.

Security note: undo_log.json is plain text and drives where files get
written (each entry's "from" becomes a restore destination). A tampered
or corrupted log is therefore a trust boundary — see _restore_is_safe.
We refuse any entry that would restore a file outside the watched dirs,
so a doctored log can't relocate files into, say, ~/Library/LaunchAgents."""
import argparse
import json
import sys
from pathlib import Path

from cleanup_agent.db import connect, init_schema
from cleanup_agent.mover import perform_move
from cleanup_agent.undo_log import DEFAULT_LOG_PATH

WATCHED_DIRS = [Path.home() / "Downloads", Path.home() / "Desktop"]


def _restore_is_safe(original, watched_dirs):
    """True if restoring to `original` would land inside one of `watched_dirs`.

    Both sides are resolved first, so `..` segments in a doctored log can't
    escape the watched roots (`~/Downloads/../../etc` resolves to `/etc`
    and fails the check). `original` is the file's pre-move location, which
    by construction is a direct child of a watched dir — anything else means
    the log was tampered with or corrupted."""
    try:
        original = Path(original).resolve()
    except (OSError, ValueError):
        return False
    for root in watched_dirs:
        root = Path(root).expanduser().resolve()
        if original == root or root in original.parents:
            return True
    return False


def undo(conn, log_path, dry_run=True, watched_dirs=WATCHED_DIRS):
    """Walk the undo log in reverse and move each file back.
    Returns (undone, skipped)."""
    log_path = Path(log_path)
    if not log_path.exists():
        print("No undo log found — nothing to undo.")
        return 0, 0
    try:
        entries = json.loads(log_path.read_text())
    except json.JSONDecodeError:
        print(f"error: {log_path} is not valid JSON — refusing to undo.",
              file=sys.stderr)
        return 0, 0
    if not isinstance(entries, list):
        print(f"error: {log_path} is not a list of entries — refusing to undo.",
              file=sys.stderr)
        return 0, 0
    if not entries:
        print("Undo log is empty — nothing to undo.")
        return 0, 0

    undone = 0
    skipped = 0

    # Iterate in reverse: later moves may have computed collision suffixes
    # that depended on earlier moves' destination state. Undoing in the
    # opposite order keeps the filesystem state consistent at each step.
    for entry in reversed(entries):
        # Validate shape before touching the filesystem — a malformed entry
        # shouldn't crash the whole undo or be acted on.
        if not isinstance(entry, dict) or not isinstance(entry.get("from"), str) \
                or not isinstance(entry.get("to"), str):
            print(f"  skip: malformed undo entry {entry!r}", file=sys.stderr)
            skipped += 1
            continue

        moved_to = Path(entry["to"])
        original = Path(entry["from"])

        # Trust boundary: the destination comes from the log file. Refuse to
        # restore anywhere outside the watched dirs.
        if not _restore_is_safe(original, watched_dirs):
            print(
                f"  skip: refusing to restore outside watched dirs → {original} "
                f"(log entry may be tampered or stale)",
                file=sys.stderr,
            )
            skipped += 1
            continue

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
        "--watch", action="append",
        help="Override watched directory (repeatable). Restores are refused "
             "outside these. Default: ~/Downloads + ~/Desktop",
    )
    parser.add_argument(
        "--log",
        help=f"Path to undo log (default: {DEFAULT_LOG_PATH})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview the reversal without moving anything (default: reverses)",
    )
    args = parser.parse_args()

    watched = (
        [Path(w).expanduser() for w in args.watch] if args.watch else WATCHED_DIRS
    )
    log_path = args.log or DEFAULT_LOG_PATH
    conn = connect(args.db)
    try:
        init_schema(conn)
        undone, skipped = undo(
            conn, log_path, dry_run=args.dry_run, watched_dirs=watched
        )
    finally:
        conn.close()

    if args.dry_run:
        print(f"\ndry-run: would restore {undone}, skip {skipped}")
        print("(re-run without --dry-run to actually undo)")
    else:
        print(f"\nundo complete: {undone} restored, {skipped} skipped")


if __name__ == "__main__":
    main()
