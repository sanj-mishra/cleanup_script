"""Tests for the per-session undo log."""
import json

from cleanup_agent.undo_log import UndoLog


def test_start_session_wipes_previous_entries(tmp_path):
    """Each review run gets a fresh log — you can only undo the most recent
    session. This is a deliberate simplicity tradeoff."""
    path = tmp_path / "undo.json"

    log1 = UndoLog(path)
    log1.start_session()
    log1.add("/from/a", "/to/a")
    log1.add("/from/b", "/to/b")

    log2 = UndoLog(path)
    log2.start_session()

    assert json.loads(path.read_text()) == []


def test_add_appends_and_persists(tmp_path):
    path = tmp_path / "undo.json"
    log = UndoLog(path)
    log.start_session()
    log.add("/from/a", "/to/a")
    log.add("/from/b", "/to/b")

    contents = json.loads(path.read_text())
    assert contents == [
        {"from": "/from/a", "to": "/to/a"},
        {"from": "/from/b", "to": "/to/b"},
    ]


def test_persists_across_instances(tmp_path):
    path = tmp_path / "undo.json"
    log1 = UndoLog(path)
    log1.start_session()
    log1.add("/x", "/y")

    log2 = UndoLog(path)
    # Without start_session, we should still see what was written.
    assert json.loads(path.read_text()) == [{"from": "/x", "to": "/y"}]


def test_creates_parent_dir(tmp_path):
    nested = tmp_path / "deep" / "nested" / "undo.json"
    log = UndoLog(nested)
    log.start_session()
    assert nested.exists()
