# cleanup-agent

A weekly Mac file organizer for `~/Downloads` and `~/Desktop`. Watches for
new files and folders, fires a system notification with a count once a
week, and (Phase 3+) lets you triage each one interactively.

## Status

Phases 1 & 2 complete:
- `bootstrap.py` — one-time baseline of existing files/folders.
- `notify.py` — scans + sends a Mac notification with a count of items
  worth reviewing.

Phase 3 (Ollama-based classifier + interactive review) and Phase 4 (undo,
launchd scheduler, Terminal-on-click) are not built yet.

## Setup

```bash
# Run once after cloning, to establish what's already on your Desktop /
# Downloads (so future scans only flag genuine new arrivals):
python3 -m cleanup_agent.bootstrap
```

The SQLite database (`seen.db`) lives at the project root. It's gitignored
because it contains your file paths — not something to push to GitHub.

## Usage

```bash
# Check for new items and fire a notification:
python3 -m cleanup_agent.notify

# Test against a fake directory tree without touching your real DB:
mkdir -p /tmp/cleanup-smoke/Downloads
touch /tmp/cleanup-smoke/Downloads/{a,b}.txt
python3 -m cleanup_agent.notify \
    --db /tmp/cleanup-smoke/test.db \
    --watch /tmp/cleanup-smoke/Downloads \
    --print-only
```

Flags (apply to `bootstrap` and `notify`):
- `--db <path>` — use a different SQLite DB
- `--watch <dir>` (repeatable) — override the watched directories

Flags specific to `notify`:
- `--days N` — window in days for counting pending items (default 14)
- `--print-only` — print the notification text instead of firing osascript

## Behavior

### What counts as an "item"
Top-level files **and folders** in `~/Downloads` / `~/Desktop`. Folders
are treated as atomic units — we never recurse into them.

### What's skipped
Dotfiles (`.foo`) and macOS system cruft (`.DS_Store`, `.localized`,
`.CFUserTextEncoding`).

### The 14-day pending window
`notify` only counts items first seen in the last 14 days. The window is
deliberately wider than the weekly launchd cadence: if a week's run is
missed, items get a second chance to surface before they age out.

### Moving items to Trash (auto-prune)
Files or folders moved out of `~/Downloads` / `~/Desktop` (to the Trash,
or anywhere else) are automatically pruned from `seen.db` on the next
`notify` run. This matters: without pruning, a re-download to the same
path would be silently swallowed by `INSERT OR IGNORE` and never surface
as a new item.

Pruning is scoped to the directories you're scanning. Running
`notify --watch /tmp/foo` will not prune rows for `~/Desktop`.

### Decisions
Each row in `seen_files` has a `decision`:
- `known` — was already on disk when bootstrap ran (or got marked as
  baseline later)
- `pending` — newly discovered, awaiting review (Phase 3)
- `approved` — user OK'd a move (Phase 3)
- `rejected` — user said no (Phase 3)

A re-scan never overwrites an existing decision — `INSERT OR IGNORE`
guarantees a `'pending'` row never gets demoted back to `'known'` by a
later bootstrap.

## Phase 3 (planned): interactive review

Coming next: `python3 -m cleanup_agent.review` for triaging the pending
queue.

### How it works

Items are reviewed **one at a time, sequentially**, oldest first. Each
decision is committed immediately, so quitting halfway is safe — already-
decided items stay decided, and re-running picks up where you left off.

For each item, an Ollama classifier (`llama3` by default, expected at
`localhost:11434`) suggests a destination based on the existing
subfolders of `~/Downloads` and `~/Desktop`. Suggestions tagged
"low confidence" are highlighted so you know to double-check.

### Keys

- `y` — accept the suggestion and move the item.

- `n` — reject. Item stays put; row marked `'rejected'` and won't
  surface again.

- `e` — edit destination. Type a different path; if it doesn't exist,
  you'll get a "Create? [y/n]" prompt before proceeding.

- `s` — skip. Decide later; row stays `'pending'` and resurfaces next week.

- `q` — quit the session.

### Defaults and safety

`review.py` runs in **dry-run mode by default**. Add `--apply` to
actually move files. This inverts the safety default — the dangerous
mode is always opt-in.

If a file already exists at the destination, the new file gets a
timestamp suffix instead of overwriting:
`foo.pdf` → `foo_2026-06-06_18-30-15.pdf`.

Approved moves write to `undo_log.json` so a Phase 4 `undo.py` can
reverse the most recent session.

`review.py` also calls `prune_missing` at startup, so files moved to
Trash between weekly cycles disappear from the DB cleanly before the
review loop begins.

## Testing

```bash
python3 -m pytest tests/ -v
```

All tests use temporary directories via `pytest`'s `tmp_path`. They never
read or write your real `~/Downloads`, `~/Desktop`, or `seen.db`.
