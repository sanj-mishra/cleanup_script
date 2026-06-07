"""Tests for the move helper: dry-run, collision-suffix, file vs folder."""
import datetime as dt

import pytest

from cleanup_agent.mover import perform_move


@pytest.fixture
def setup(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    return src_dir, dst_dir


def test_dry_run_does_not_touch_filesystem(setup):
    src_dir, dst_dir = setup
    src = src_dir / "foo.txt"
    src.write_text("hi")

    result = perform_move(src, dst_dir, dry_run=True)

    assert result == dst_dir / "foo.txt"
    assert src.exists()
    assert not (dst_dir / "foo.txt").exists()


def test_real_move_relocates_file(setup):
    src_dir, dst_dir = setup
    src = src_dir / "foo.txt"
    src.write_text("hello")

    result = perform_move(src, dst_dir, dry_run=False)

    assert result == dst_dir / "foo.txt"
    assert not src.exists()
    assert result.read_text() == "hello"


def test_collision_adds_timestamp_with_underscores(setup):
    """The user-visible format requirement: foo.pdf collides →
    foo_2026-06-06_18-30-15.pdf. Underscores between stem and timestamp."""
    src_dir, dst_dir = setup
    src = src_dir / "foo.pdf"
    src.write_text("new")
    (dst_dir / "foo.pdf").write_text("preexisting")

    fake_now = dt.datetime(2026, 6, 6, 18, 30, 15)
    result = perform_move(src, dst_dir, dry_run=False, now=fake_now)

    assert result.name == "foo_2026-06-06_18-30-15.pdf"
    assert result.read_text() == "new"
    assert (dst_dir / "foo.pdf").read_text() == "preexisting"  # untouched


def test_collision_for_folder_appends_to_full_name(setup):
    """For folders there's no extension to split at, so the timestamp
    appends to the whole name: `project` → `project_2026-06-06_18-30-15`."""
    src_dir, dst_dir = setup
    src = src_dir / "project"
    src.mkdir()
    (src / "inside.txt").write_text("x")
    (dst_dir / "project").mkdir()

    fake_now = dt.datetime(2026, 6, 6, 18, 30, 15)
    result = perform_move(src, dst_dir, dry_run=False, now=fake_now)

    assert result.name == "project_2026-06-06_18-30-15"
    assert (result / "inside.txt").read_text() == "x"


def test_double_collision_appends_counter(setup):
    """If even the timestamped name exists (two moves in the same second),
    fall through to `_1`, `_2`, etc."""
    src_dir, dst_dir = setup
    src = src_dir / "foo.txt"
    src.write_text("new")
    (dst_dir / "foo.txt").write_text("first")
    fake_now = dt.datetime(2026, 6, 6, 18, 30, 15)
    (dst_dir / f"foo_2026-06-06_18-30-15.txt").write_text("second")

    result = perform_move(src, dst_dir, dry_run=False, now=fake_now)

    assert result.name == "foo_2026-06-06_18-30-15_1.txt"
    assert result.read_text() == "new"


def test_no_collision_uses_original_name(setup):
    src_dir, dst_dir = setup
    src = src_dir / "fresh.csv"
    src.write_text("data")

    result = perform_move(src, dst_dir, dry_run=False)

    assert result == dst_dir / "fresh.csv"
    assert result.read_text() == "data"
