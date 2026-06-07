"""Top-level directory scanner. Used by bootstrap now and by notify/review later."""
from pathlib import Path

# macOS / shell artifacts we never want to track.
IGNORED_NAMES = {".DS_Store", ".localized", ".CFUserTextEncoding"}


def scan_top_level(directory):
    """Yield Path objects for top-level files AND directories in `directory`.

    Folders are treated as atomic units (no recursion into them) — a project
    folder dropped on the Desktop is just as much "clutter to triage" as a
    stray PDF. Skips dotfiles and known system cruft. Entries that vanish
    between listing and stat'ing are silently skipped. Raises PermissionError
    if `directory` itself is unreadable."""
    directory = Path(directory).expanduser()
    if not directory.is_dir():
        return
    for entry in directory.iterdir():
        name = entry.name
        if name.startswith(".") or name in IGNORED_NAMES:
            continue
        try:
            if not (entry.is_file() or entry.is_dir()):
                continue
        except OSError:
            # Entry vanished between iterdir() and stat — race with the user
            # deleting/moving something. Treat as "not there."
            continue
        yield entry
