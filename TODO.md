# Next steps

## Done

- **Tightened the README for first-time setup.** Reorganized
  quickstart-first (prerequisites → bootstrap → schedule → first
  notification → first review), with the reference material moved below.

- **Codebase cleanup / dead-end audit.** Audited every module. Findings:
  the suspected dead ends are actually live and justified, so nothing
  was removed except one real simplification.
  - Classifier fallback paths (no-destination, low-confidence) are
    reachable *and* covered by tests — kept.
  - `launch_review.py` is wired into the notification click action in
    `notify.py` and documented as optional — kept.
  - The `--watch` / `--db` / `--log` overrides back the documented
    smoke test, not just tests — kept.
  - **Merged `scanner.py` into `scan.py`** to remove the confusing
    `scan`-vs-`scanner` naming. The only real change.

## 1. Flip `--dry-run` from default to opt-in

`review.py` and `undo.py` currently default to dry-run, requiring
`--apply` to commit changes. After a few weeks of trusted usage the
extra flag will start feeling like friction. Flip it: bare commands
do the real work, `--dry-run` is the explicit preview.

Worth thinking about whether a "first-N-times confirmation" prompt or
some other middle ground is better than a hard flip — this was a
deliberate safety default in Phase 3.

## 2. Security review

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
