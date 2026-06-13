#!/usr/bin/env python3
"""Weekly check: scans ~/Downloads and ~/Desktop, records any newly-appeared
files as 'pending', then fires a Mac notification with the count of pending
files seen in the last PENDING_WINDOW_DAYS days.

The window is wider than the cadence on purpose: launchd runs this weekly,
but the 14-day window means a missed week still gets a second chance to
surface files before they age out."""
import argparse
import datetime as dt
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from cleanup_agent.db import connect, init_schema
from cleanup_agent.scan import prune_missing, record_new_files

WATCHED_DIRS = [Path.home() / "Downloads", Path.home() / "Desktop"]
PENDING_WINDOW_DAYS = 14

# Used to build the notification click action — `cd`'ing into project root
# before invoking `python -m cleanup_agent.launch_review` is required because
# terminal-notifier spawns the click command from an arbitrary cwd, so the
# module import wouldn't otherwise resolve.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def count_pending(conn, window_days=PENDING_WINDOW_DAYS, today=None):
    """Count rows where decision='pending' and first_seen >= today - window_days.
    `today` is injectable for testing; defaults to dt.date.today()."""
    if today is None:
        today = dt.date.today()
    cutoff = (today - dt.timedelta(days=window_days)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM seen_files "
        "WHERE decision = 'pending' AND first_seen >= ?",
        (cutoff,),
    ).fetchone()
    return row[0]


def _format_message(count):
    # "item" not "file" because we track top-level folders too.
    if count == 0:
        return "no new items to review"
    if count == 1:
        return "1 new item to review"
    return f"{count} new items to review"


def display_notification(title, message, click_command=None):
    """Fire a Mac system notification.

    If `terminal-notifier` is installed (brew install terminal-notifier) and
    a `click_command` is supplied, use it so the user can click the
    notification to launch review.py. Otherwise fall back to plain
    osascript, which fires the notification but doesn't support click
    actions (a known macOS limitation).

    Notification is best-effort — failures are reported but don't abort
    the script. The DB state is already correct by the time we get here."""
    if click_command and shutil.which("terminal-notifier"):
        result = subprocess.run(
            [
                "terminal-notifier",
                "-title", title,
                "-message", message,
                "-execute", click_command,
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(
                f"warning: terminal-notifier failed (rc={result.returncode}): "
                f"{result.stderr.strip()}",
                file=sys.stderr,
            )
        return

    # Fallback: plain osascript, no click action.
    def esc(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{esc(message)}" with title "{esc(title)}"'
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(
            f"warning: osascript failed (rc={result.returncode}): "
            f"{result.stderr.strip()}",
            file=sys.stderr,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="Path to SQLite DB")
    parser.add_argument(
        "--watch", action="append",
        help="Override watched directory (repeatable). "
             "Default: ~/Downloads + ~/Desktop"
    )
    parser.add_argument(
        "--days", type=int, default=PENDING_WINDOW_DAYS,
        help=f"Window in days for counting pending files "
             f"(default: {PENDING_WINDOW_DAYS})"
    )
    parser.add_argument(
        "--print-only", action="store_true",
        help="Print the notification text instead of firing osascript "
             "(useful for testing and dry runs)"
    )
    args = parser.parse_args()

    watched = (
        [Path(w).expanduser() for w in args.watch] if args.watch else WATCHED_DIRS
    )

    conn = connect(args.db)
    try:
        init_schema(conn)
        # Prune BEFORE inserting: a file moved to Trash leaves a stale row,
        # and if we don't clean it up first, a re-download of the same path
        # would be silently swallowed by INSERT OR IGNORE.
        pruned = prune_missing(conn, watched)
        added, _, _ = record_new_files(conn, watched, decision="pending")
        count = count_pending(conn, window_days=args.days)
    finally:
        conn.close()

    title = "cleanup-agent"
    message = _format_message(count)

    if args.print_only:
        print(f"[notification] {title}: {message}")
    else:
        # Click action (only used when terminal-notifier is installed):
        # opens a new Terminal window and runs review.py.
        # We cd into PROJECT_ROOT so the `-m cleanup_agent.launch_review`
        # import resolves from terminal-notifier's spawned shell.
        # shlex.quote both paths: terminal-notifier runs this through a shell,
        # so a project path with a space, quote, or `$` must not break out.
        click_cmd = (
            f"cd {shlex.quote(str(PROJECT_ROOT))} && "
            f"{shlex.quote(sys.executable)} -m cleanup_agent.launch_review"
        )
        display_notification(title, message, click_command=click_cmd)
        print(
            f"notified: {message} "
            f"({added} newly discovered, {pruned} pruned this run)"
        )


if __name__ == "__main__":
    main()
