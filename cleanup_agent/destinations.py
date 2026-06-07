"""Lists the existing subfolders of watched dirs — the only places the
classifier is allowed to suggest moves into. Phase 3 scope is deliberately
narrow: no Documents/Pictures/Movies, no config file, just whatever
subfolders you've already created under ~/Downloads and ~/Desktop."""
from pathlib import Path


def list_destinations(watched_dirs):
    """Return existing one-level-deep subdirectories of each watched dir,
    sorted alphabetically. Skips dotfolders. The list is what gets shown
    to the classifier as the universe of valid destinations."""
    dests = []
    for d in watched_dirs:
        d = Path(d).expanduser()
        if not d.is_dir():
            continue
        for entry in d.iterdir():
            if not entry.is_dir():
                continue
            if entry.name.startswith("."):
                continue
            dests.append(entry)
    return sorted(dests, key=lambda p: str(p))
