"""Phase 1 tests for bootstrap.py.

We never touch the real ~/Downloads or ~/Desktop — every test uses tmp_path
to build fake watched directories."""
import pytest

from cleanup_agent.bootstrap import bootstrap
from cleanup_agent.db import connect, init_schema


@pytest.fixture
def fake_dirs(tmp_path):
    """Build a Downloads + Desktop pair that mimics what Finder would show:
    real files, one nested subdir (its file should be ignored), and a couple of
    hidden / system files (also ignored)."""
    downloads = tmp_path / "Downloads"
    desktop = tmp_path / "Desktop"
    downloads.mkdir()
    desktop.mkdir()

    # Visible top-level files — these are what Finder shows and what bootstrap
    # should record.
    (downloads / "report.pdf").write_text("x")
    (downloads / "song.mp3").write_text("x")
    (desktop / "notes.md").write_text("x")
    (desktop / "screenshot.png").write_text("x")

    # Stuff that should NOT be recorded.
    (downloads / ".DS_Store").write_text("x")        # system cruft
    (downloads / ".hidden").write_text("x")           # dotfile
    nested = downloads / "old_project"
    nested.mkdir()
    (nested / "buried.txt").write_text("x")           # top-level only, ignored

    return downloads, desktop


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "seen.db")
    init_schema(conn)
    yield conn
    conn.close()


def finder_visible_count(dirs):
    """How many top-level files Finder would show across `dirs`, after hiding
    dotfiles. Matches the user-facing definition of 'files in this folder'."""
    count = 0
    for d in dirs:
        for entry in d.iterdir():
            if not entry.is_file() or entry.name.startswith("."):
                continue
            count += 1
    return count


def test_row_count_matches_finder(db, fake_dirs):
    downloads, desktop = fake_dirs
    added, already_known, missing = bootstrap(
        db, watched_dirs=[downloads, desktop]
    )

    rows = db.execute("SELECT COUNT(*) FROM seen_files").fetchone()[0]
    expected = finder_visible_count([downloads, desktop])

    assert rows == expected == 4  # report, song, notes, screenshot
    assert added == expected
    assert already_known == 0
    assert missing == 0

    # And every row should be marked 'known' — not 'approved' / 'pending'.
    decisions = {row[0] for row in db.execute("SELECT DISTINCT decision FROM seen_files")}
    assert decisions == {"known"}


def test_new_file_shows_up_as_new_on_rerun(db, fake_dirs):
    """Bootstrap is idempotent: re-running it after a new file is dropped
    in Downloads records exactly that one new file and leaves the rest alone."""
    downloads, desktop = fake_dirs
    bootstrap(db, watched_dirs=[downloads, desktop])
    baseline = db.execute("SELECT COUNT(*) FROM seen_files").fetchone()[0]

    new_file = downloads / "fresh.txt"
    new_file.write_text("hi")

    added, already_known, _ = bootstrap(db, watched_dirs=[downloads, desktop])

    assert added == 1
    assert already_known == baseline
    after = db.execute("SELECT COUNT(*) FROM seen_files").fetchone()[0]
    assert after == baseline + 1

    # The new file is in the DB.
    hit = db.execute(
        "SELECT path FROM seen_files WHERE path = ?", (str(new_file),)
    ).fetchone()
    assert hit is not None


def test_missing_dir_does_not_crash(db, tmp_path):
    """If a watched directory doesn't exist (e.g. user has no ~/Desktop),
    bootstrap reports it and keeps going instead of blowing up."""
    missing = tmp_path / "Desktop"  # never created
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "ok.txt").write_text("x")

    added, already_known, missing_dirs = bootstrap(
        db, watched_dirs=[missing, downloads]
    )

    assert added == 1
    assert already_known == 0
    assert missing_dirs == 1
