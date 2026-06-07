"""Tests for the shared scan helper used by bootstrap, notify, and review."""
import pytest

from cleanup_agent.db import connect, init_schema
from cleanup_agent.scan import prune_missing, record_new_files


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "seen.db")
    init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def downloads(tmp_path):
    d = tmp_path / "Downloads"
    d.mkdir()
    (d / "a.txt").write_text("x")
    (d / "b.pdf").write_text("x")
    return d


def test_records_files_with_given_decision(db, downloads):
    added, _, _ = record_new_files(db, [downloads], decision="pending")
    assert added == 2
    rows = db.execute("SELECT decision FROM seen_files").fetchall()
    assert all(r[0] == "pending" for r in rows)


def test_idempotent_rerun(db, downloads):
    record_new_files(db, [downloads], decision="known")
    added, already, _ = record_new_files(db, [downloads], decision="known")
    assert added == 0
    assert already == 2


def test_existing_decision_is_never_overwritten(db, downloads):
    """The hot path that matters: bootstrap must not retroactively flip a
    'pending' row back to 'known'. INSERT OR IGNORE is what guarantees this —
    this test pins it down so a future refactor can't regress."""
    record_new_files(db, [downloads], decision="pending")
    added, already, _ = record_new_files(db, [downloads], decision="known")
    assert added == 0
    assert already == 2
    rows = db.execute("SELECT decision FROM seen_files").fetchall()
    assert all(r[0] == "pending" for r in rows)


def test_new_file_after_baseline_gets_pending(db, downloads):
    """The flow notify.py relies on: baseline the dir with 'known', then a
    new file appears and gets recorded as 'pending' on the next scan."""
    record_new_files(db, [downloads], decision="known")
    (downloads / "fresh.png").write_text("x")
    added, _, _ = record_new_files(db, [downloads], decision="pending")
    assert added == 1
    row = db.execute(
        "SELECT decision FROM seen_files WHERE path = ?",
        (str(downloads / "fresh.png"),),
    ).fetchone()
    assert row[0] == "pending"


def test_records_top_level_directories_too(db, tmp_path):
    """A folder dropped on Desktop counts as 'something to triage', same
    as a file. Recorded as an atomic unit — we never recurse into it."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "loose_file.txt").write_text("x")
    (downloads / "some_project").mkdir()
    (downloads / "some_project" / "nested.txt").write_text("x")  # NOT yielded

    added, _, _ = record_new_files(db, [downloads], decision="pending")

    assert added == 2  # loose_file.txt + some_project/, but NOT nested.txt
    paths = {row[0] for row in db.execute("SELECT path FROM seen_files")}
    assert str(downloads / "loose_file.txt") in paths
    assert str(downloads / "some_project") in paths
    assert str(downloads / "some_project" / "nested.txt") not in paths


def test_prune_removes_rows_for_paths_no_longer_on_disk(db, downloads):
    """The Trash bug: move a file out of Downloads, prune drops its row.
    Otherwise a re-download of the same path would be silently swallowed
    by INSERT OR IGNORE and never surface as a new item."""
    record_new_files(db, [downloads], decision="known")
    assert db.execute("SELECT COUNT(*) FROM seen_files").fetchone()[0] == 2

    # Simulate "moved to Trash" — file is gone from the watched dir.
    (downloads / "a.txt").unlink()

    removed = prune_missing(db, [downloads])
    assert removed == 1
    paths = {row[0] for row in db.execute("SELECT path FROM seen_files")}
    assert str(downloads / "a.txt") not in paths
    assert str(downloads / "b.pdf") in paths


def test_prune_is_scoped_to_watched_dirs(db, tmp_path):
    """A --watch override must NOT prune rows for unrelated directories.
    Pruning is scoped: only rows whose parent matches a passed-in dir
    are eligible for deletion."""
    downloads = tmp_path / "Downloads"
    desktop = tmp_path / "Desktop"
    downloads.mkdir()
    desktop.mkdir()
    (downloads / "in_scope.txt").write_text("x")
    (desktop / "out_of_scope.txt").write_text("x")
    record_new_files(db, [downloads, desktop], decision="known")

    # Both files vanish; but we only call prune on Downloads.
    (downloads / "in_scope.txt").unlink()
    (desktop / "out_of_scope.txt").unlink()

    removed = prune_missing(db, [downloads])
    assert removed == 1
    paths = {row[0] for row in db.execute("SELECT path FROM seen_files")}
    assert str(downloads / "in_scope.txt") not in paths
    # The Desktop row stays — we never asked prune to consider it.
    assert str(desktop / "out_of_scope.txt") in paths


def test_redownload_after_prune_surfaces_as_pending(db, downloads):
    """End-to-end of the bug fix: download → delete → re-download. The
    re-download should show up as 'pending', not get swallowed by a stale
    'known' row."""
    record_new_files(db, [downloads], decision="known")
    (downloads / "a.txt").unlink()
    prune_missing(db, [downloads])

    # User re-downloads the same filename later.
    (downloads / "a.txt").write_text("redownloaded")
    added, _, _ = record_new_files(db, [downloads], decision="pending")

    assert added == 1
    decision = db.execute(
        "SELECT decision FROM seen_files WHERE path = ?",
        (str(downloads / "a.txt"),),
    ).fetchone()[0]
    assert decision == "pending"


def test_missing_dir_does_not_crash(db, tmp_path):
    present = tmp_path / "Downloads"
    present.mkdir()
    (present / "ok.txt").write_text("x")
    missing = tmp_path / "Desktop"  # never created
    added, _, missing_dirs = record_new_files(
        db, [missing, present], decision="known"
    )
    assert added == 1
    assert missing_dirs == 1
