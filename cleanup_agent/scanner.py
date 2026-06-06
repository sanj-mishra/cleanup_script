"""Top-level directory scanner. Used by bootstrap now and by notify/review later."""
from pathlib import Path

# macOS / shell artifacts we never want to track.
IGNORED_NAMES = {".DS_Store", ".localized", ".CFUserTextEncoding"}


def scan_top_level(directory):
    """Yield Path objects for top-level files in `directory`.

    Skips subdirectories (no recursion), dotfiles, and known system cruft.
    Files that disappear between listing and stat'ing are silently skipped —
    that's a race, not an error. Raises PermissionError if the directory
    itself is unreadable (caller decides how to surface that)."""
    directory = Path(directory).expanduser()
    if not directory.is_dir():
        return
    for entry in directory.iterdir():
        name = entry.name
        if name.startswith(".") or name in IGNORED_NAMES:
            continue
        try:
            if not entry.is_file():
                continue
        except OSError:
            # File vanished between iterdir() and stat — race with the user
            # deleting/moving something. Treat as "not there."
            continue
        yield entry
