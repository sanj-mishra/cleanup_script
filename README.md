# cleanup-agent

A weekly Mac file organizer for `~/Downloads` and `~/Desktop`. Once a
week it fires a system notification with a count of new files and
folders, then lets you triage each one interactively with an
Ollama-suggested destination.

## Quickstart

Your first ten minutes, start to finish.

**1. Prerequisites.** Python 3 (no third-party packages) and Ollama with
a `llama3`-family model for the review step:

```bash
ollama serve
ollama pull llama3        # or llama3.2:latest, etc.
```

**2. Baseline what's already on disk.** Run once — records everything
currently in `~/Downloads` / `~/Desktop` as "known" so future scans only
flag new arrivals. Creates `seen.db` at the project root (gitignored —
it holds your file paths).

```bash
python3 -m cleanup_agent.bootstrap
```

**3. Install the weekly schedule.** That's the whole setup; from here it
runs itself. The steps below show the weekly cycle — trigger them by
hand to see it now.

```bash
python3 -m cleanup_agent.launchd install      # defaults to Mondays 5pm
```

**4. See the notification.** Scans for new items and fires a Mac
notification with the count:

```bash
python3 -m cleanup_agent.notify
```

**5. Review.** Walks pending items one at a time, oldest first, with an
Ollama-suggested destination for each:

```bash
python3 -m cleanup_agent.review              # review and move
python3 -m cleanup_agent.review --dry-run    # preview only, move nothing
```

Per-item keys:

- `y` — accept the suggestion and move the item
- `n` — reject; won't surface again
- `e` — edit destination; offers to create it if it doesn't exist
- `s` — skip; resurfaces next week
- `q` — quit

Nothing moves until you press `y` on that item, and each decision commits
immediately, so quitting halfway is safe. Made a mess?
`python3 -m cleanup_agent.undo` reverses the whole last session
(`--dry-run` to preview).

## Commands

```bash
python3 -m cleanup_agent.bootstrap     # one-time baseline of existing items
python3 -m cleanup_agent.notify        # scan + fire notification with a count
python3 -m cleanup_agent.review        # interactive triage (moves; --dry-run to preview)
python3 -m cleanup_agent.undo          # reverse the most recent review session
python3 -m cleanup_agent.launchd install | uninstall | status   # manage the schedule
```

Run any command with `--help` for its full flags. The most useful:
`--watch <dir>` (override the watched dirs, repeatable), `--db <path>`,
`--print-only` (notify), and `--model <name>` (review). `launchd install`
takes `--weekday N --hour N --minute N` (weekday 0=Sun … 6=Sat).

To try it safely against a throwaway tree:

```bash
mkdir -p /tmp/cleanup-smoke/Downloads
touch /tmp/cleanup-smoke/Downloads/{a,b}.txt
python3 -m cleanup_agent.notify \
    --db /tmp/cleanup-smoke/test.db --watch /tmp/cleanup-smoke/Downloads --print-only
```

## How it works

**Items.** Top-level files *and* folders in the watched dirs. Folders are
atomic — we never recurse into them. Dotfiles and macOS cruft
(`.DS_Store`, `.localized`, `.CFUserTextEncoding`) are skipped.

**The 14-day window.** `notify` only counts items first seen in the last
14 days — deliberately wider than the weekly cadence, so a missed week
still gets a second chance to surface before items age out.

**Auto-prune.** Items moved out of the watched dirs (to Trash or
anywhere) are pruned from `seen.db` on the next run. Without this, a
re-download to the same path would be silently swallowed by
`INSERT OR IGNORE` and never resurface. Pruning is scoped to the dirs
you're scanning — `notify --watch /tmp/foo` won't touch `~/Desktop` rows.

**Decisions.** Each row in `seen_files` is `known` (present at bootstrap),
`pending` (awaiting review), `approved` (moved), or `rejected` (left
put, won't resurface). A re-scan never overwrites an existing decision,
so re-running is always safe.

**Collisions.** If a file already exists at the destination, the new one
gets a timestamp suffix instead of overwriting: `foo.pdf` →
`foo_2026-06-07_18-30-15.pdf`. Undo uses the same rule on the way back.

**Undo scope.** `undo_log.json` is wiped at the start of each review run,
so only the *latest* session is reversible — by design, to keep the data
model simple.

**Ollama.** The classifier talks to `127.0.0.1:11434` (not `localhost` —
macOS IPv6 fallback can be flaky) and auto-detects which `llama3`-family
model you have pulled, so `--model` is rarely needed. Suggestions are
limited to existing subfolders of the watched dirs; low-confidence ones
are flagged in red.

**Scheduling.** The plist lives at
`~/Library/LaunchAgents/com.cleanup-agent.notify.plist`; scheduled-run
output goes to `/tmp/cleanup-agent.log` and `.err` — check those if the
weekly notification stops appearing.

**Click-to-open (optional).** `brew install terminal-notifier` makes the
notification clickable (opens Terminal and runs review). Without it the
notification is informational and you run review manually.

## Security model

The agent runs locally on your own files, so the operator is trusted —
but a few inputs are guarded as boundaries:

- **The undo log is a trust boundary.** Each entry's `from` field decides
  where a file gets written on restore, so a tampered or corrupted
  `undo_log.json` could otherwise relocate files into a sensitive
  writable dir (e.g. `~/Library/LaunchAgents`). `undo.py` resolves each
  restore path and refuses anything landing outside the watched dirs
  (`..` normalized away first), and rejects malformed / non-list logs.
- **SQL is always parameterized** (`?` placeholders), and **shell strings
  are `shlex.quote`d**. File *names* never reach a shell — only SQLite
  and `shutil.move`.
- **The `e` (edit) destination is intentionally unrestricted** — it's the
  operator choosing where their own file goes.

## Testing

```bash
python3 -m pytest tests/ -v
```

Tests use `tmp_path`, so they never touch your real `~/Downloads`,
`~/Desktop`, or `seen.db`. `launchd.py` and `launch_review.py` are
skipped — they shell out to OS commands and are easier to smoke-test by
hand.
