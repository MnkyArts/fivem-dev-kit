---
name: fivem-review
description: Review an existing FiveM/Cfx.re resource for performance, security and correctness issues against the fivem-scripting rulebook. Use when the user asks to review, audit, or check a resource or diff before shipping it.
---

# fivem-review — audit an existing resource

Runs in the **main session**. `fxlint`/`fxref` are on PATH while this plugin is enabled; absolute fallback:
`${FIVEM_DEV_KIT_ROOT}/bin/<name>`. Argument: a resource directory path.

## Steps

0. Is it a **core plugin** (manifest has `dependency 'core'` / `'@core/import.lua'`) or core itself? Then
   invoke the `fivem-core` skill first — its rules are what the review is against, on top of the rulebook.
1. Run `fxlint <resource_path> --json`. This gives the mechanical findings (P0xx/S0xx/C0xx) plus native
   verification (C007/C008) when the database is built. On a core resource the **K rules** (K001–K013, core
   conventions) run too — they must end at 0 errors / 0 warnings, and K006 (`backdrop-filter` in `ui/`) is an
   error, never a nit.
2. Extract every PascalCase-looking call identifier the resource uses (a name matching `[A-Z][A-Za-z0-9]*\(`
   that isn't a `.`/`:` method call) and batch-verify them with `fxref resolve <names...>` — a second pass that
   can catch a native fxlint's own heuristics missed (e.g. one only ever used inside a table constructor).
   On a core resource do the same for framework calls: collect every `Core.<Ns>.<fn>` and run
   `fxref core resolve <names...>`; anything MISSING is a probable hallucinated API and a finding.
3. Invoke `fivem-reviewer` via the `task` tool with: the resource path, the fxlint JSON, the resolve output(s),
   and pointers to the rulebook's §14 checklist and `reference/security-checklist.md`. It returns ranked findings. On a core
   plugin it must also check: every registration *into* core sits inside `Core.onReady` (K004) and no
   `onResourceStop` re-does core's cleanup (K005); every `Core.Net.on` carries the right `opts` in the right
   order (schema → cooldown → requireLoaded → permission → distance) and no handler re-validates *after*
   acting; money only through `Core.Money` and persistence only through `Core.DB` (never files or a second
   database); callbacks tested with `Core.Utils.isCallable`, never `type(v) == 'function'`.
4. Present the findings to the user, most severe first, one line each:
   `severity | file:line | what | why | fix`. Follow with the reviewer's short verdict (ship / fix first).
5. Offer to apply fixes. If the user agrees, invoke `fivem-implementer` via the `task` tool with the findings
   **you** judged worth acting on (not the raw review verbatim) and have it patch the resource, then re-run `fxlint` to
   confirm it's clean.

For an explicit request for a deeper second opinion, invoke `fivem-deep-reviewer` on the same target and
compare only its independently confirmed findings. Do not use the expensive Kimi K3 agent by default.

## Rules

- Never rewrite a whole file yourself, and don't ask the reviewer or implementer to either — findings and fixes
  stay targeted.
- Don't relay pure style nits that don't hide a real bug — the reviewer already skips those; if a raw fxlint
  `info` finding is purely stylistic, mention it only in passing.
- If `fxlint` is clean and the reviewer's verdict is "ship", say so plainly instead of inventing findings to
  fill space.
