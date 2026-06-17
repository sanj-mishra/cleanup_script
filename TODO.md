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

- **Let classification learn over time (few-shot memory, not
  fine-tuning).** Today `classify()` is stateless — same prompt every
  call, no memory of past decisions — and the DB throws away the key
  signal: it stores the final `decision` but not *what the model
  suggested vs. what the user actually picked*. So overrides (the `e`
  flow) are lost.

  Idea: capture `filename → suggested_dest → chosen_dest → confidence`
  per decision, then inject the most-similar past choices into the
  prompt as examples ("you previously moved invoice_acme.pdf →
  ~/Documents/Invoices"). The model improves because the *context*
  improves, not the weights — no GPU, no training loop, adapts the
  moment you correct it.

  - Retrieval can start dumb: match on extension + shared filename
    tokens. Reach for embeddings only if that's not precise enough.
  - Pair it with a learned-rule fast-path for stable repeats
    (`*.pdf invoice → Invoices`) that skips the LLM entirely.
  - **Why not fine-tuning:** needs hundreds of examples, a tuning
    pipeline, and an Ollama Modelfile/adapter; feedback is slow
    (periodic retrain, not instant). Wrong altitude for a personal
    tool.
  - **Why not just hardcoding rules in the prompt:** hardcoded rules
    are *authored* — static, frozen until you next edit them, and only
    cover cases you anticipated. Few-shot memory is *accumulated* —
    self-updating from real behavior, covers the long tail you can't
    enumerate, and self-corrects when you reorganize folders. The axis
    that matters is static-authored vs. live-from-data, which is what
    "learn over time" actually requires.

  Mostly additive: a decisions table, a `recent_examples()` query, and
  a few lines in `_build_prompt`. Worth a sandbox smoke test before it
  touches the real `~/Downloads`.
