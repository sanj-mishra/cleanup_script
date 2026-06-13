"""Tests for undo.py: walk the undo log in reverse, restore moves, wipe log."""
import datetime as dt
import json

import pytest

from cleanup_agent.db import connect, init_schema
from cleanup_agent.undo import undo


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "seen.db")
    init_schema(conn)
    yield conn
    conn.close()


def _seed_log(path, entries):
    path.write_text(json.dumps(entries))


def _insert_approved(conn, path):
    """Mirror what review.py does on approval: row decision='approved'."""
    conn.execute(
        "INSERT INTO seen_files (path, first_seen, decision) "
        "VALUES (?, ?, 'approved')",
        (str(path), dt.date.today().isoformat()),
    )
    conn.commit()


# --- defensive cases ---

def test_no_log_file_is_safe(db, tmp_path):
    undone, skipped = undo(db, tmp_path / "missing.json", dry_run=False)
    assert undone == 0
    assert skipped == 0


def test_empty_log_is_safe(db, tmp_path):
    log = tmp_path / "undo.json"
    log.write_text("[]")
    undone, skipped = undo(db, log, dry_run=False)
    assert undone == 0
    assert skipped == 0


def test_skip_when_moved_file_no_longer_exists(db, tmp_path):
    """If the user deleted the moved file manually before running undo,
    we can't restore it — skip with a warning instead of crashing."""
    downloads = tmp_path / "Downloads"
    log = tmp_path / "undo.json"
    _seed_log(log, [{
        "from": str(downloads / "x.txt"),
        "to": str(tmp_path / "never_created.txt"),
    }])
    undone, skipped = undo(db, log, dry_run=False, watched_dirs=[downloads])
    assert undone == 0
    assert skipped == 1


# --- security: the log is a trust boundary ---

def test_refuses_restore_outside_watched_dirs(db, tmp_path):
    """A tampered log whose 'from' points outside the watched dirs (e.g.
    ~/Library/LaunchAgents for persistence) must be refused — the file is
    left where it is, not relocated to the attacker-chosen destination."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    sensitive = tmp_path / "Library" / "LaunchAgents"
    sensitive.mkdir(parents=True)
    moved = downloads / "evil.plist"
    moved.write_text("payload")

    log = tmp_path / "undo.json"
    _seed_log(log, [{
        "from": str(sensitive / "evil.plist"),  # restore destination
        "to": str(moved),
    }])

    undone, skipped = undo(db, log, dry_run=False, watched_dirs=[downloads])
    assert undone == 0
    assert skipped == 1
    assert moved.exists()                       # left untouched
    assert not (sensitive / "evil.plist").exists()  # never written there


def test_refuses_dotdot_traversal_in_from(db, tmp_path):
    """`..` segments can't escape the watched root — the path is resolved
    before the containment check."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    moved = downloads / "x.txt"
    moved.write_text("data")

    log = tmp_path / "undo.json"
    _seed_log(log, [{
        "from": str(downloads / ".." / "outside" / "x.txt"),
        "to": str(moved),
    }])

    undone, skipped = undo(db, log, dry_run=False, watched_dirs=[downloads])
    assert undone == 0
    assert skipped == 1
    assert not (outside / "x.txt").exists()


def test_skips_malformed_entry(db, tmp_path):
    """A non-dict or missing-key entry is skipped, not acted on or crashed."""
    log = tmp_path / "undo.json"
    _seed_log(log, ["not-a-dict", {"from": str(tmp_path / "Downloads" / "a")}])
    undone, skipped = undo(db, log, dry_run=False, watched_dirs=[tmp_path])
    assert undone == 0
    assert skipped == 2


def test_refuses_non_list_log(db, tmp_path):
    """A log tampered into a JSON object (not a list) is refused outright."""
    log = tmp_path / "undo.json"
    log.write_text('{"from": "/etc/x", "to": "/tmp/x"}')
    undone, skipped = undo(db, log, dry_run=False, watched_dirs=[tmp_path])
    assert undone == 0
    assert skipped == 0


def test_refuses_invalid_json_log(db, tmp_path):
    log = tmp_path / "undo.json"
    log.write_text("{not valid json")
    undone, skipped = undo(db, log, dry_run=False, watched_dirs=[tmp_path])
    assert undone == 0
    assert skipped == 0


# --- dry-run ---

def test_dry_run_does_not_move_or_update_db(db, tmp_path):
    downloads = tmp_path / "Downloads"
    dest = tmp_path / "Documents" / "receipts"
    downloads.mkdir()
    dest.mkdir(parents=True)
    moved = dest / "foo.pdf"
    moved.write_text("hi")
    _insert_approved(db, moved)

    log = tmp_path / "undo.json"
    _seed_log(log, [{
        "from": str(downloads / "foo.pdf"),
        "to": str(moved),
    }])

    undone, _ = undo(db, log, dry_run=True, watched_dirs=[downloads])

    assert undone == 1
    assert moved.exists()
    assert not (downloads / "foo.pdf").exists()
    decision = db.execute(
        "SELECT decision FROM seen_files WHERE path = ?", (str(moved),)
    ).fetchone()[0]
    assert decision == "approved"  # unchanged in dry-run


# --- apply ---

def test_apply_moves_file_back_and_updates_db(db, tmp_path):
    downloads = tmp_path / "Downloads"
    dest = tmp_path / "Documents" / "receipts"
    downloads.mkdir()
    dest.mkdir(parents=True)
    moved = dest / "foo.pdf"
    moved.write_text("hi")
    _insert_approved(db, moved)

    log = tmp_path / "undo.json"
    _seed_log(log, [{
        "from": str(downloads / "foo.pdf"),
        "to": str(moved),
    }])

    undone, _ = undo(db, log, dry_run=False, watched_dirs=[downloads])

    assert undone == 1
    assert (downloads / "foo.pdf").exists()
    assert not moved.exists()
    rows = db.execute("SELECT path, decision FROM seen_files").fetchall()
    assert rows == [(str(downloads / "foo.pdf"), "pending")]


def test_apply_wipes_log(db, tmp_path):
    """Once undone, the log is empty — you can't undo twice."""
    downloads = tmp_path / "Downloads"
    dest = tmp_path / "dest"
    downloads.mkdir()
    dest.mkdir()
    (dest / "foo.txt").write_text("x")

    log = tmp_path / "undo.json"
    _seed_log(log, [{
        "from": str(downloads / "foo.txt"),
        "to": str(dest / "foo.txt"),
    }])

    undo(db, log, dry_run=False, watched_dirs=[downloads])
    assert json.loads(log.read_text()) == []


def test_walks_reverse_order(db, tmp_path):
    """When multiple moves are in the log, the second-to-last move is
    undone before the last move's effects are reverted (the consistency
    reason for reverse-order walking)."""
    downloads = tmp_path / "Downloads"
    dest = tmp_path / "dest"
    downloads.mkdir()
    dest.mkdir()
    (dest / "a.txt").write_text("first")
    (dest / "b.txt").write_text("second")

    log = tmp_path / "undo.json"
    _seed_log(log, [
        {"from": str(downloads / "a.txt"), "to": str(dest / "a.txt")},
        {"from": str(downloads / "b.txt"), "to": str(dest / "b.txt")},
    ])

    undone, _ = undo(db, log, dry_run=False, watched_dirs=[downloads])
    assert undone == 2
    assert (downloads / "a.txt").read_text() == "first"
    assert (downloads / "b.txt").read_text() == "second"


def test_returns_to_now_occupied_path_uses_timestamp_suffix(db, tmp_path):
    """If we moved foo.pdf → dest/foo.pdf, then the user re-downloaded
    foo.pdf into Downloads, undo can't simply restore — same collision
    suffix rule as the forward move."""
    downloads = tmp_path / "Downloads"
    dest = tmp_path / "dest"
    downloads.mkdir()
    dest.mkdir()
    moved = dest / "foo.pdf"
    moved.write_text("the moved one")
    redownload = downloads / "foo.pdf"
    redownload.write_text("the new download")

    log = tmp_path / "undo.json"
    _seed_log(log, [{
        "from": str(downloads / "foo.pdf"),
        "to": str(moved),
    }])

    undone, _ = undo(db, log, dry_run=False, watched_dirs=[downloads])
    assert undone == 1
    # The redownload stays put.
    assert redownload.read_text() == "the new download"
    # The restored file got a timestamp suffix.
    returned = [
        p for p in downloads.iterdir()
        if p.name != "foo.pdf" and p.suffix == ".pdf"
    ]
    assert len(returned) == 1
    assert returned[0].read_text() == "the moved one"
    assert returned[0].name.startswith("foo_")
