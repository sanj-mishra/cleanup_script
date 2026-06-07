"""Moves a file (or folder) into a destination directory. Adds a timestamp
suffix on collision rather than overwriting. Dry-run computes the final
path without touching the filesystem."""
import datetime as dt
import shutil
from pathlib import Path


def perform_move(src, dst_dir, dry_run=False, now=None):
    """Move `src` into `dst_dir`. Returns the final Path the file ended up
    at (or would end up at, in dry-run).

    On filename collision, the new file gets a timestamp suffix inserted
    before its extension (or appended to the name, for folders):
    `foo.pdf` → `foo_2026-06-06_18-30-15.pdf`
    `project` → `project_2026-06-06_18-30-15`

    Raises FileNotFoundError if `src` doesn't exist (in non-dry-run)."""
    src = Path(src)
    dst_dir = Path(dst_dir)
    final = _resolve_collision(src, dst_dir, now=now)
    if dry_run:
        return final
    shutil.move(str(src), str(final))
    return final


def _resolve_collision(src, dst_dir, now=None):
    candidate = dst_dir / src.name
    if not candidate.exists():
        return candidate
    if now is None:
        now = dt.datetime.now()
    ts = now.strftime("%Y-%m-%d_%H-%M-%S")
    if src.is_dir():
        base, ext = src.name, ""
    else:
        base, ext = src.stem, src.suffix
    candidate = dst_dir / f"{base}_{ts}{ext}"
    n = 1
    while candidate.exists():
        candidate = dst_dir / f"{base}_{ts}_{n}{ext}"
        n += 1
    return candidate
