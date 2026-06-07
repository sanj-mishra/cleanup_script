"""Tests for the destination lister — the universe of folders the
classifier is allowed to suggest into."""
from cleanup_agent.destinations import list_destinations


def test_returns_only_existing_subfolders(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "installers").mkdir()
    (downloads / "projects").mkdir()
    (downloads / "loose_file.txt").write_text("x")  # not a dir, skipped

    dests = list_destinations([downloads])
    names = {d.name for d in dests}
    assert names == {"installers", "projects"}


def test_skips_dotfolders(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "real").mkdir()
    (downloads / ".hidden").mkdir()

    dests = list_destinations([downloads])
    assert {d.name for d in dests} == {"real"}


def test_does_not_recurse(tmp_path):
    """Only one level deep — deep nested folders aren't candidates."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    nested = downloads / "outer" / "inner"
    nested.mkdir(parents=True)

    dests = list_destinations([downloads])
    assert {d.name for d in dests} == {"outer"}


def test_missing_watched_dir_is_ignored(tmp_path):
    real = tmp_path / "Real"
    real.mkdir()
    (real / "x").mkdir()
    missing = tmp_path / "DoesNotExist"

    dests = list_destinations([missing, real])
    assert {d.name for d in dests} == {"x"}
