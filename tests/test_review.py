"""Tests for review.py: pending fetcher + the loop with injected
classifier and prompter (so we don't actually hit Ollama or stdin)."""
import datetime as dt
import json
from pathlib import Path

import pytest

from cleanup_agent.db import connect, init_schema
from cleanup_agent.review import fetch_pending, review_session


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "seen.db")
    init_schema(conn)
    yield conn
    conn.close()


def _insert(conn, path, first_seen, decision):
    conn.execute(
        "INSERT INTO seen_files (path, first_seen, decision) VALUES (?, ?, ?)",
        (path, first_seen.isoformat(), decision),
    )
    conn.commit()


# --- fetch_pending ---

def test_fetch_pending_only_returns_pending_in_window(db):
    today = dt.date.today()
    _insert(db, "/a", today, "pending")
    _insert(db, "/b", today, "known")
    _insert(db, "/c", today - dt.timedelta(days=30), "pending")  # outside

    result = fetch_pending(db, window_days=14, today=today)
    assert [str(p) for p in result] == ["/a"]


def test_fetch_pending_orders_oldest_first(db):
    today = dt.date.today()
    _insert(db, "/newer", today - dt.timedelta(days=1), "pending")
    _insert(db, "/older", today - dt.timedelta(days=5), "pending")
    _insert(db, "/oldest", today - dt.timedelta(days=10), "pending")

    result = fetch_pending(db, today=today)
    assert [str(p) for p in result] == ["/oldest", "/older", "/newer"]


# --- review_session: stub out classifier and prompter ---

class _FakePrompter:
    """Replays a list of answers."""

    def __init__(self, actions, destinations=None, creates=None):
        self.actions = list(actions)
        self.destinations = list(destinations or [])
        self.creates = list(creates or [])

    def ask_action(self):
        return self.actions.pop(0)

    def ask_destination(self):
        return self.destinations.pop(0)

    def confirm_create(self, dest):
        return self.creates.pop(0)


def _make_pending(downloads, name):
    """Create a real file in `downloads` and return its Path."""
    f = downloads / name
    f.write_text("data")
    return f


def _seed_pending(conn, paths, today=None):
    today = today or dt.date.today()
    for p in paths:
        _insert(conn, str(p), today, "pending")


def _known_subfolder(conn, parent, name):
    """Create `parent/name/` and mark it 'known' in the DB. Models production,
    where destination subfolders already exist when review runs and so don't
    surface as pending themselves."""
    p = parent / name
    p.mkdir()
    _insert(conn, str(p), dt.date.today(), "known")
    return p


def test_accepting_suggestion_moves_file_and_marks_approved(db, tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    target = _known_subfolder(db, downloads, "receipts")
    item = _make_pending(downloads, "receipt.pdf")
    _seed_pending(db, [item])

    review_session(
        db, [downloads], dry_run=False, log_path=tmp_path / "undo.json",
        classifier=lambda name, dests: (target, "high"),
        prompter=_FakePrompter(actions=["y"]),
    )

    assert not item.exists()
    moved = target / "receipt.pdf"
    assert moved.read_text() == "data"
    row = db.execute(
        "SELECT path, decision FROM seen_files WHERE path = ?", (str(moved),)
    ).fetchone()
    assert row == (str(moved), "approved")


def test_rejecting_leaves_file_in_place_and_marks_rejected(db, tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    stays = _known_subfolder(db, downloads, "stays")
    item = _make_pending(downloads, "junk.tmp")
    _seed_pending(db, [item])

    review_session(
        db, [downloads], dry_run=False, log_path=tmp_path / "undo.json",
        classifier=lambda name, dests: (stays, "medium"),
        prompter=_FakePrompter(actions=["n"]),
    )

    assert item.exists()
    row = db.execute(
        "SELECT decision FROM seen_files WHERE path = ?", (str(item),)
    ).fetchone()
    assert row == ("rejected",)


def test_edit_overrides_suggestion(db, tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    suggested = _known_subfolder(db, downloads, "wrong")
    correct = _known_subfolder(db, downloads, "right")
    item = _make_pending(downloads, "file.txt")
    _seed_pending(db, [item])

    review_session(
        db, [downloads], dry_run=False, log_path=tmp_path / "undo.json",
        classifier=lambda name, dests: (suggested, "low"),
        prompter=_FakePrompter(actions=["e"], destinations=[str(correct)]),
    )

    assert (correct / "file.txt").exists()
    assert not (suggested / "file.txt").exists()


def test_edit_to_nonexistent_dir_prompts_to_create(db, tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    _known_subfolder(db, downloads, "anything")  # so destinations list isn't empty
    item = _make_pending(downloads, "file.txt")
    _seed_pending(db, [item])
    new_dest = downloads / "brand_new"

    review_session(
        db, [downloads], dry_run=False, log_path=tmp_path / "undo.json",
        classifier=lambda name, dests: (None, "low"),
        prompter=_FakePrompter(
            actions=["e"],
            destinations=[str(new_dest)],
            creates=[True],
        ),
    )

    assert new_dest.is_dir()
    assert (new_dest / "file.txt").exists()


def test_skip_leaves_decision_pending(db, tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    any_dir = _known_subfolder(db, downloads, "any")
    item = _make_pending(downloads, "file.txt")
    _seed_pending(db, [item])

    review_session(
        db, [downloads], dry_run=False, log_path=tmp_path / "undo.json",
        classifier=lambda name, dests: (any_dir, "high"),
        prompter=_FakePrompter(actions=["s"]),
    )

    assert item.exists()
    decision = db.execute(
        "SELECT decision FROM seen_files WHERE path = ?", (str(item),)
    ).fetchone()[0]
    assert decision == "pending"


def test_quit_stops_after_current_item(db, tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    anywhere = _known_subfolder(db, downloads, "anywhere")
    item1 = _make_pending(downloads, "first.txt")
    item2 = _make_pending(downloads, "second.txt")
    _seed_pending(db, [item1, item2])

    review_session(
        db, [downloads], dry_run=False, log_path=tmp_path / "undo.json",
        classifier=lambda name, dests: (anywhere, "high"),
        prompter=_FakePrompter(actions=["q"]),
    )

    # First item never got moved (we quit immediately); second item never
    # got touched. Both should still be 'pending'.
    pending_paths = {
        row[0] for row in db.execute(
            "SELECT path FROM seen_files WHERE decision = 'pending'"
        )
    }
    assert str(item1) in pending_paths
    assert str(item2) in pending_paths


def test_dry_run_does_not_move_or_update_db(db, tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    target = _known_subfolder(db, downloads, "dest")
    item = _make_pending(downloads, "file.txt")
    _seed_pending(db, [item])

    review_session(
        db, [downloads], dry_run=True, log_path=tmp_path / "undo.json",
        classifier=lambda name, dests: (target, "high"),
        prompter=_FakePrompter(actions=["y"]),
    )

    assert item.exists()
    assert not (target / "file.txt").exists()
    # Row stays 'pending' in dry-run.
    decision = db.execute(
        "SELECT decision FROM seen_files WHERE path = ?", (str(item),)
    ).fetchone()[0]
    assert decision == "pending"


def test_approved_move_writes_undo_log(db, tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    target = _known_subfolder(db, downloads, "dest")
    item = _make_pending(downloads, "file.txt")
    _seed_pending(db, [item])
    log_path = tmp_path / "undo.json"

    review_session(
        db, [downloads], dry_run=False, log_path=log_path,
        classifier=lambda name, dests: (target, "high"),
        prompter=_FakePrompter(actions=["y"]),
    )

    entries = json.loads(log_path.read_text())
    assert len(entries) == 1
    assert entries[0]["from"] == str(item)
    assert entries[0]["to"] == str(target / "file.txt")
