#!/usr/bin/env python3
"""Interactive review of pending items.

Sequential, oldest-first. Each decision commits immediately, so quitting
mid-session is safe — already-decided items stay decided, and re-running
picks up where you left off.

Moves files by default — but every move still needs an explicit per-item
keypress. Add --dry-run to preview the whole session without touching
anything."""
import argparse
import datetime as dt
import functools
import shutil
import subprocess
import sys
from pathlib import Path

from cleanup_agent.classifier import (
    DEFAULT_MODEL,
    OllamaUnreachable,
    classify,
    resolve_model,
)
from cleanup_agent.db import connect, init_schema
from cleanup_agent.destinations import list_destinations
from cleanup_agent.mover import perform_move
from cleanup_agent.scan import prune_missing, record_new_files
from cleanup_agent.undo_log import UndoLog

WATCHED_DIRS = [Path.home() / "Downloads", Path.home() / "Desktop"]
PENDING_WINDOW_DAYS = 14

# ANSI color escapes — only emitted when stdout is a real terminal.
COLORS = {
    "low": "\033[31m",      # red — think twice
    "medium": "\033[33m",   # yellow
    "high": "\033[32m",     # green
    "reset": "\033[0m",
}


def fetch_pending(conn, window_days=PENDING_WINDOW_DAYS, today=None):
    """Pending items within the window, oldest first."""
    if today is None:
        today = dt.date.today()
    cutoff = (today - dt.timedelta(days=window_days)).isoformat()
    rows = conn.execute(
        "SELECT path FROM seen_files "
        "WHERE decision='pending' AND first_seen >= ? "
        "ORDER BY first_seen ASC, path ASC",
        (cutoff,),
    ).fetchall()
    return [Path(r[0]) for r in rows]


def colorize(text, key, use_color):
    if not use_color or key not in COLORS:
        return text
    return f"{COLORS[key]}{text}{COLORS['reset']}"


def review_session(conn, watched_dirs, dry_run, log_path=None,
                   classifier=classify, prompter=None):
    """Main loop. classifier and prompter are injectable for tests."""
    init_schema(conn)
    prune_missing(conn, watched_dirs)
    record_new_files(conn, watched_dirs, decision="pending")

    pending = fetch_pending(conn)
    if not pending:
        print("No pending items. You're all caught up.")
        return

    destinations = list_destinations(watched_dirs)
    if not destinations:
        print(
            "No existing subfolders found in the watched dirs. "
            "Create some destination folders first.",
            file=sys.stderr,
        )
        return

    prompter = prompter or _interactive_prompter()
    use_color = sys.stdout.isatty()
    log = UndoLog(log_path)
    log.start_session()

    watched_str = ", ".join(str(d) for d in watched_dirs)
    print(f"Reviewing {len(pending)} pending items in {watched_str}.")
    print("Oldest first. Press 'q' to quit (already-decided items stay decided).")
    if dry_run:
        print("\n  DRY-RUN — no files will be moved. Drop --dry-run to commit moves.\n")
    else:
        print()

    stats = {"moved": 0, "rejected": 0, "skipped": 0}
    total = len(pending)
    for i, item in enumerate(pending, start=1):
        print(f"[{i}/{total}] {item.name}")
        print("       Thinking…", end="\r", flush=True)
        try:
            suggested, confidence = classifier(item.name, destinations)
        except OllamaUnreachable as e:
            print(f"\nerror: {e}", file=sys.stderr)
            raise SystemExit(2)
        # Wipe the "Thinking…" line.
        print("       " + " " * 40, end="\r")

        if suggested:
            label = colorize(f"[{confidence} confidence]", confidence, use_color)
            print(f"       suggested: {suggested}/   {label}")
        else:
            print("       suggested: (none — classifier returned no valid destination)")

        cont = _handle_choice(
            item, suggested, conn, dry_run, log, stats, prompter
        )
        print()
        if not cont:
            break

    decided = stats["moved"] + stats["rejected"] + stats["skipped"]
    print(
        f"reviewed {decided} items: "
        f"{stats['moved']} moved, "
        f"{stats['rejected']} rejected, "
        f"{stats['skipped']} skipped"
    )
    if dry_run:
        print("(dry-run — no files were actually moved)")
    elif stats["moved"]:
        print(f"undo log: {log.path} ({stats['moved']} moves)")


def _handle_choice(item, suggested, conn, dry_run, log, stats, prompter):
    """Handle one item's prompt. Returns False to quit the whole session,
    True to continue."""
    while True:
        choice = prompter.ask_action()
        if choice == "y":
            if not suggested:
                print("       no suggestion to accept — use 'e' to pick one")
                continue
            _do_move(conn, item, suggested, dry_run, log, stats)
            return True
        if choice == "n":
            conn.execute(
                "UPDATE seen_files SET decision='rejected' WHERE path=?",
                (str(item),),
            )
            conn.commit()
            stats["rejected"] += 1
            print("       rejected (won't surface again)")
            return True
        if choice == "e":
            dest = prompter.ask_destination()
            if dest is None:
                print("       canceled")
                return True
            dest = Path(dest).expanduser()
            if not dest.exists():
                if not prompter.confirm_create(dest):
                    print("       canceled")
                    return True
                if not dry_run:
                    dest.mkdir(parents=True, exist_ok=True)
            _do_move(conn, item, dest, dry_run, log, stats)
            return True
        if choice == "s":
            stats["skipped"] += 1
            print("       skipped (decide later)")
            return True
        if choice == "p":
            # Non-terminal: peek, then fall back to the same prompt so the
            # user still has to pick a real action for this item.
            prompter.preview(item)
            continue
        if choice == "q":
            print("       quitting")
            return False


def _do_move(conn, src, dst_dir, dry_run, log, stats):
    try:
        final = perform_move(src, dst_dir, dry_run=dry_run)
    except OSError as e:
        print(f"       error: move failed: {e}", file=sys.stderr)
        return
    if dry_run:
        print(f"       would move → {final}")
    else:
        conn.execute(
            "UPDATE seen_files SET path=?, decision='approved' WHERE path=?",
            (str(final), str(src)),
        )
        conn.commit()
        log.add(src, final)
        print(f"       moved → {final}")
    stats["moved"] += 1


class _interactive_prompter:
    """Wraps stdin prompts so tests can inject deterministic answers."""

    def ask_action(self):
        valid = {"y", "n", "e", "s", "p", "q"}
        while True:
            raw = input(
                "       [y]es  [n]o  [e]dit  [s]kip  [p]review  [q]uit  > "
            ).strip().lower()
            if raw in valid:
                return raw
            print("       (please enter y, n, e, s, p, or q)")

    def preview(self, path):
        """Pop a macOS Quick Look window for `path` (the 'p' action).

        Blocks until the preview is closed — that's the intended flow:
        peek, dismiss, then decide. Mirrors notify.py's shell-out style:
        confirm the tool with shutil.which first, capture its (noisy)
        output, and surface a non-zero exit instead of swallowing it."""
        if not Path(path).exists():
            print("       (can't preview — file is no longer there)")
            return
        if not shutil.which("qlmanage"):
            print("       (preview unavailable — qlmanage not found)")
            return
        print("       opening preview… (close the Quick Look window to continue)")
        result = subprocess.run(
            ["qlmanage", "-p", str(path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(
                f"       preview failed: {result.stderr.strip()}",
                file=sys.stderr,
            )

    def ask_destination(self):
        raw = input("       Enter destination: ").strip()
        return raw or None

    def confirm_create(self, dest):
        raw = input(
            f"       {dest}/ doesn't exist. Create? [y/n] > "
        ).strip().lower()
        return raw == "y"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="Path to SQLite DB")
    parser.add_argument(
        "--watch", action="append",
        help="Override watched directory (repeatable)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview the session without moving anything (default: moves files)"
    )
    parser.add_argument(
        "--log", help="Path to undo_log.json (default: <project>/undo_log.json)"
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"Ollama model to use for classification (default: {DEFAULT_MODEL}). "
             "Check `ollama list` for what you have pulled — common tags are "
             "llama3:latest, llama3.1, llama3.2:latest."
    )
    args = parser.parse_args()

    watched = (
        [Path(w).expanduser() for w in args.watch] if args.watch else WATCHED_DIRS
    )

    # Auto-resolve the requested model to whatever Ollama actually has
    # pulled — saves passing --model llama3.2:latest every run when 'llama3'
    # would do.
    try:
        model = resolve_model(args.model)
    except OllamaUnreachable as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(2)
    if model != args.model:
        print(f"using model: {model} (resolved from '{args.model}')")
    classifier_fn = functools.partial(classify, model=model)

    conn = connect(args.db)
    try:
        review_session(
            conn, watched, dry_run=args.dry_run, log_path=args.log,
            classifier=classifier_fn,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
