"""Shared scan helper: walks watched directories, inserts any path not
already in the DB with the given decision and today's date. Used by
bootstrap (decision='known'), notify, and review (decision='pending')."""
import datetime as dt
import sys
from pathlib import Path

from cleanup_agent.scanner import scan_top_level

FDA_HINT = (
    "Permission denied reading {path}. On macOS, grant your terminal Full Disk "
    "Access: System Settings → Privacy & Security → Full Disk Access → add and "
    "enable your terminal app, then restart it."
)


def record_new_files(conn, watched_dirs, decision):
    """For each directory in `watched_dirs`, scan top-level files and INSERT
    OR IGNORE each path into seen_files with the given `decision` and today's
    date. Existing rows are left untouched — re-running never flips a row's
    decision (so a 'pending' file doesn't get demoted to 'known' on the next
    bootstrap, and an 'approved'/'rejected' file doesn't get re-surfaced).

    Returns (added, already_present, missing_dirs).
    Raises SystemExit(2) with the FDA hint if a directory is unreadable."""
    today = dt.date.today().isoformat()
    added = 0
    already_present = 0
    missing_dirs = 0

    for d in watched_dirs:
        d = Path(d).expanduser()
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
                "VALUES (?, ?, ?)",
                (str(f), today, decision),
            )
            if cur.rowcount == 1:
                added += 1
            else:
                already_present += 1
    conn.commit()
    return added, already_present, missing_dirs


def prune_missing(conn, watched_dirs):
    """Delete rows whose paths are direct children of any of `watched_dirs`
    but no longer exist on disk. Returns the number of rows removed.

    Scoped on purpose: only rows whose parent directory matches one of the
    currently-watched dirs are eligible. That way `notify --watch /tmp/foo`
    can't accidentally nuke rows for ~/Desktop.

    Without this, a file moved to Trash leaves a stale row in seen_files,
    and any future redownload to the same path would be silently swallowed
    by INSERT OR IGNORE — the whole "new file detection" idea breaks for
    any name we've ever had before."""
    watched = {str(Path(d).expanduser().resolve()) for d in watched_dirs}
    removed = 0
    for (path_str,) in list(conn.execute("SELECT path FROM seen_files")):
        p = Path(path_str)
        if str(p.parent) not in watched:
            continue
        if p.exists():
            continue
        conn.execute("DELETE FROM seen_files WHERE path = ?", (path_str,))
        removed += 1
    conn.commit()
    return removed
