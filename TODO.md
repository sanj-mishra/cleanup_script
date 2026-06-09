# Next steps

Captured at the end of Phase 4. Not yet started.

## 1. Tighten the README for first-time setup

The current README documents behavior in depth but reads more like a
reference than a "first 10 minutes" walkthrough. Reorganize so a brand-new
user can clone → install deps → bootstrap → install schedule → see their
first notification → run their first review, without scrolling past
historical context. The behavior reference can move further down.

## 2. Flip `--dry-run` from default to opt-in

`review.py` and `undo.py` currently default to dry-run, requiring
`--apply` to commit changes. After a few weeks of trusted usage the
extra flag will start feeling like friction. Flip it: bare commands
do the real work, `--dry-run` is the explicit preview.

Worth thinking about whether a "first-N-times confirmation" prompt or
some other middle ground is better than a hard flip — this was a
deliberate safety default in Phase 3.

## 3. Codebase cleanup: kill dead ends

Audit every module for unused imports, unreachable branches, fall-back
paths that never get hit, and helpers added for hypothetical needs that
never materialized. Especially worth scanning:

- The classifier fallback paths (no-destination, low-confidence cascade).
- `launch_review.py` — only useful if `terminal-notifier` is reinstalled.
  Worth either deleting or documenting clearly that it's optional.
- The `--watch` / `--db` / `--log` overrides — do any of these actually
  get used outside tests?

## 4. Security review

Focused security pass before this gets reused / shared:

- **Path traversal.** Can `--watch` or destination paths (especially via
  the `e` edit flow) be crafted to read or write outside intended
  locations? `Path` arithmetic doesn't sanitize `..`.
- **Subprocess and shell construction.** `notify.py` and
  `launch_review.py` build shell commands that get passed to
  `terminal-notifier`'s `-execute` and to `osascript`. Verify robustness
  against paths and filenames with quotes, backticks, `$`, etc.
- **SQLite parameter binding.** All queries should use `?` placeholders;
  worth confirming none drifted into f-string-built SQL.
- **Undo log integrity.** `undo_log.json` is plain text. Could a
  malicious or corrupted entry make `undo.py` move files outside the
  watched dirs? The destination is derived from the entry's `from`
  field — that's a trust boundary.
