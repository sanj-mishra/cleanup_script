# cleanup-agent

A weekly Mac file organizer for `~/Downloads` and `~/Desktop`. Watches
for new files and folders, fires a system notification with a count once
a week, and lets you triage each one interactively with an
Ollama-suggested destination.

## Status

All four phases complete.

- `bootstrap.py` — one-time baseline of existing files/folders.
- `notify.py` — weekly scan + Mac notification with a count of items
  worth reviewing.
- `review.py` — interactive triage loop with Ollama classifier.
- `undo.py` — reverses the most recent review session.
- `launchd.py` — installs the weekly schedule.

## Setup

```bash
# 1. One-time baseline so future scans only flag genuine new arrivals.
python3 -m cleanup_agent.bootstrap

# 2. Make sure Ollama is running with a model pulled (for review.py):
#    ollama serve
#    ollama pull llama3:latest   # or llama3.2:latest, etc.

# 3. (Optional) Install the weekly schedule — defaults to Mondays 5pm:
python3 -m cleanup_agent.launchd install
```

The SQLite database (`seen.db`) lives at the project root. It's
gitignored because it contains your file paths.

## Usage

```bash
# Manual check (also runs every Monday 5pm via launchd if installed):
python3 -m cleanup_agent.notify

# Triage the pending queue — dry-run by default, --apply to move:
python3 -m cleanup_agent.review
python3 -m cleanup_agent.review --apply

# Reverse the most recent review session:
python3 -m cleanup_agent.undo
python3 -m cleanup_agent.undo --apply

# Test against a fake directory tree:
mkdir -p /tmp/cleanup-smoke/Downloads
touch /tmp/cleanup-smoke/Downloads/{a,b}.txt
python3 -m cleanup_agent.notify \
    --db /tmp/cleanup-smoke/test.db \
    --watch /tmp/cleanup-smoke/Downloads \
    --print-only
```

### Flags

Shared by `bootstrap`, `notify`, `review`:

- `--db <path>` — use a different SQLite DB
- `--watch <dir>` (repeatable) — override the watched directories

`notify`:

- `--days N` — window in days for counting pending items (default 14)
- `--print-only` — print the notification text instead of firing osascript

`review`:

- `--apply` — actually move files (default is dry-run)
- `--model <name>` — Ollama model tag (default: `llama3`). The script
  auto-resolves to whatever you have pulled, so the default usually
  works even if your actual model is `llama3.2:latest` or similar — you
  only need to pass this if you want to force a specific tag.
- `--log <path>` — undo log location (default: `<project>/undo_log.json`)

`undo`:

- `--apply` — actually reverse moves (default is dry-run)
- `--log <path>` — undo log to read from

`launchd`:

- `install [--weekday N --hour N --minute N]` — generate plist + load
- `uninstall` — unload + remove plist
- `status` — show install / load state

## Behavior

### What counts as an "item"

Top-level files **and folders** in `~/Downloads` / `~/Desktop`. Folders
are treated as atomic units — we never recurse into them.

### What's skipped

Dotfiles (`.foo`) and macOS system cruft (`.DS_Store`, `.localized`,
`.CFUserTextEncoding`).

### The 14-day pending window

`notify` only counts items first seen in the last 14 days. The window is
deliberately wider than the weekly cadence: if a week's run is missed,
items get a second chance to surface before they age out.

### Moving items to Trash (auto-prune)

Files or folders moved out of `~/Downloads` / `~/Desktop` (to the Trash,
or anywhere else) are automatically pruned from `seen.db` on the next
`notify` or `review` run. Without pruning, a re-download to the same
path would be silently swallowed by `INSERT OR IGNORE` and never
surface as a new item.

Pruning is scoped to the directories you're scanning. Running
`notify --watch /tmp/foo` will not prune rows for `~/Desktop`.

### Decisions

Each row in `seen_files` has a `decision`:

- `known` — was already on disk when bootstrap ran (or got marked as
  baseline later)
- `pending` — newly discovered, awaiting review
- `approved` — user OK'd a move via `review.py`
- `rejected` — user said no via `review.py`; won't surface again

A re-scan never overwrites an existing decision.

## Reviewing pending items

Items are reviewed **one at a time, sequentially**, oldest first. Each
decision commits immediately, so quitting halfway is safe — already-
decided items stay decided, and re-running picks up where you left off.

For each item, the Ollama classifier suggests a destination from your
existing subfolders. Low-confidence suggestions are flagged in red so
you know to double-check.

### Keys

- `y` — accept the suggestion and move the item.
- `n` — reject. Item stays put; row marked `'rejected'`, won't
  surface again.
- `e` — edit destination. Type a different path; if it doesn't exist,
  you'll get a "Create? [y/n]" prompt before proceeding.
- `s` — skip. Decide later; row stays `'pending'` and resurfaces next week.
- `q` — quit the session.

### Collision suffix

If a file already exists at the destination, the new file gets a
timestamp suffix instead of overwriting:
`foo.pdf` → `foo_2026-06-07_18-30-15.pdf`.

### Ollama setup

`review.py` expects Ollama running at `127.0.0.1:11434` (not `localhost`,
because macOS IPv6 fallback can be flaky). Confirm with:

```bash
curl -s http://127.0.0.1:11434/api/tags
```

The script auto-detects which `llama3`-family model you have pulled by
querying `/api/tags` at startup, so you don't have to pass the exact
tag. If you want to force a specific model anyway:

```bash
python3 -m cleanup_agent.review --model llama3.2:latest
```

## Undo

`undo.py` reverses every move from the most recent `review.py` session.
The undo log (`undo_log.json`) is wiped at the start of each review
run, so you can only undo the *latest* session — by design, to keep the
data model simple.

```bash
# Preview what would be reversed:
python3 -m cleanup_agent.undo

# Actually reverse:
python3 -m cleanup_agent.undo --apply
```

If a returned file's original location is now occupied (e.g., you
re-downloaded it), the same timestamp-suffix collision logic applies —
the redownload stays put, the restored file gets the suffix. Restored
items get their DB row flipped back to `'pending'` so they re-surface
in next week's review.

## Scheduling (launchd)

```bash
# Install — defaults to Mondays 5pm:
python3 -m cleanup_agent.launchd install

# Custom time — e.g. Tuesdays 9am:
python3 -m cleanup_agent.launchd install --weekday 2 --hour 9

# Check whether it's installed and loaded:
python3 -m cleanup_agent.launchd status

# Remove:
python3 -m cleanup_agent.launchd uninstall
```

Weekdays: 0=Sun, 1=Mon, … 6=Sat. The plist is written to
`~/Library/LaunchAgents/com.cleanup-agent.notify.plist`.

`stdout` and `stderr` from scheduled runs go to `/tmp/cleanup-agent.log`
and `/tmp/cleanup-agent.err` — check those if the weekly notification
stops appearing.

## Click-to-open (optional)

Native `osascript` notifications don't support click actions. If you
want clicking the notification to open Terminal and launch `review.py`,
install `terminal-notifier`:

```bash
brew install terminal-notifier
```

`notify.py` auto-detects it and switches to the clickable path. Without
it, you'll still see the notification — it's just informational, and
you'd run `python3 -m cleanup_agent.review` manually.

## Testing

```bash
python3 -m pytest tests/ -v
```

All tests use temporary directories via `pytest`'s `tmp_path`. They
never touch your real `~/Downloads`, `~/Desktop`, or `seen.db`. Tests
for `launchd.py` and `launch_review.py` are deliberately skipped —
both shell out to OS commands and are easier to manually smoke-test.
