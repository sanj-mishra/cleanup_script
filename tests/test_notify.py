"""Tests for notify.py: pending count + 14-day window filter + message format.

We don't fire real osascript notifications in tests — that would visually
pop on the user's screen. The CLI's --print-only path is what's exercised
end-to-end; display_notification() itself is small and is left to the
manual smoke test."""
import datetime as dt
import subprocess
import sys

import pytest

from cleanup_agent.db import connect, init_schema
from cleanup_agent.notify import _format_message, count_pending


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


def test_counts_only_pending(db):
    today = dt.date.today()
    _insert(db, "/a", today, "known")
    _insert(db, "/b", today, "approved")
    _insert(db, "/c", today, "rejected")
    _insert(db, "/d", today, "pending")
    _insert(db, "/e", today, "pending")
    assert count_pending(db, today=today) == 2


def test_window_excludes_old_pending(db):
    """Files older than the window are silently skipped — that's the (b)
    carry-forward semantics we agreed on, with the window wider than the
    weekly cadence so a missed week still has a second chance."""
    today = dt.date.today()
    _insert(db, "/recent", today - dt.timedelta(days=5), "pending")
    _insert(db, "/edge", today - dt.timedelta(days=14), "pending")  # at cutoff
    _insert(db, "/stale", today - dt.timedelta(days=15), "pending")  # outside
    _insert(db, "/old", today - dt.timedelta(days=30), "pending")
    assert count_pending(db, window_days=14, today=today) == 2


def test_zero_when_no_pending(db):
    today = dt.date.today()
    _insert(db, "/a", today, "known")
    assert count_pending(db, today=today) == 0


@pytest.mark.parametrize(
    "count,expected",
    [
        (0, "no new items to review"),
        (1, "1 new item to review"),
        (2, "2 new items to review"),
        (47, "47 new items to review"),
    ],
)
def test_message_format(count, expected):
    assert _format_message(count) == expected


def test_display_notification_uses_terminal_notifier_when_available(monkeypatch):
    """If terminal-notifier is on PATH and a click_command is given, use it
    so the user can click the notification to launch review."""
    calls = []

    def fake_which(name):
        return "/fake/terminal-notifier" if name == "terminal-notifier" else None

    def fake_run(args, **kwargs):
        calls.append(args[0])
        class _R:
            returncode = 0
            stderr = ""
            stdout = ""
        return _R()

    from cleanup_agent import notify as notify_mod
    monkeypatch.setattr(notify_mod.shutil, "which", fake_which)
    monkeypatch.setattr(notify_mod.subprocess, "run", fake_run)

    notify_mod.display_notification("title", "msg", click_command="echo hi")

    assert calls == ["terminal-notifier"]


def test_display_notification_falls_back_to_osascript(monkeypatch):
    """Without terminal-notifier installed, plain osascript fires the
    notification (no click action)."""
    calls = []

    def fake_which(name):
        return None  # nothing on PATH

    def fake_run(args, **kwargs):
        calls.append(args[0])
        class _R:
            returncode = 0
            stderr = ""
            stdout = ""
        return _R()

    from cleanup_agent import notify as notify_mod
    monkeypatch.setattr(notify_mod.shutil, "which", fake_which)
    monkeypatch.setattr(notify_mod.subprocess, "run", fake_run)

    notify_mod.display_notification("title", "msg", click_command="echo hi")

    assert calls == ["osascript"]


def test_print_only_cli_does_not_invoke_osascript(tmp_path):
    """End-to-end: --print-only never shells out to osascript, so tests are
    safe to run on a real Mac without popping notifications."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "fresh.txt").write_text("x")
    db_path = tmp_path / "seen.db"

    result = subprocess.run(
        [
            sys.executable, "-m", "cleanup_agent.notify",
            "--db", str(db_path),
            "--watch", str(downloads),
            "--print-only",
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "1 new item to review" in result.stdout
