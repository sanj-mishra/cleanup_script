# Next steps

All four original follow-ups are done. Nothing outstanding.

## Done

- **Tightened the README for first-time setup.** Reorganized
  quickstart-first (prerequisites → bootstrap → schedule → first
  notification → first review), with the reference material moved below.

- **Codebase cleanup / dead-end audit.** Audited every module. The
  suspected dead ends were actually live and justified, so nothing was
  removed except one real simplification: **merged `scanner.py` into
  `scan.py`** to kill the confusing `scan`-vs-`scanner` naming.

- **Flipped `--dry-run` from default to opt-in.** `review.py` and
  `undo.py` now do the real work by bare command; `--dry-run` is the
  explicit preview. `review` still prompts per item, so every move
  needs an explicit `y` keypress — the flip only changes whether `y`
  moves or previews.

- **Security review.** Findings and fixes:
  - **Undo log trust boundary (fixed).** `undo.py` now refuses to
    restore a file outside the watched dirs (`..` normalized away) and
    rejects malformed / non-list logs. A tampered `undo_log.json` can no
    longer relocate files into a sensitive writable dir.
  - **Subprocess hardening (fixed).** The notification click action and
    the Terminal launcher now `shlex.quote` the project path before
    embedding it in shell / AppleScript. File names never reach a shell.
  - **SQL (verified clean).** Every query uses `?` placeholders; nothing
    string-formats into SQL.
  - **Edit-flow destination (by design).** The `e` prompt stays
    unrestricted — it's the live operator choosing where their own file
    goes. Documented in the README's "Security model" section.

## Possible future ideas

Not planned, just parked:

- A config file for the watched dirs / schedule, instead of constants +
  flags.
- Broaden destinations beyond existing subfolders (Documents/Pictures),
  which was deliberately out of scope in Phase 3.
