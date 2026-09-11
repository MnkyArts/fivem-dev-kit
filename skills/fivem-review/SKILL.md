---
name: fivem-review
description: Review an existing FiveM/Cfx.re resource for performance, security and correctness issues against the fivem-scripting rulebook. Use when the user asks to review, audit, or check a resource or diff before shipping it.
argument-hint: <resource path>
---

# fivem-review — audit an existing resource

Runs in the **main session**. `fxlint`/`fxref` are on PATH while this plugin is enabled; absolute fallback:
`${CLAUDE_PLUGIN_ROOT}/bin/<name>`. Argument: a resource directory path.

## Steps

1. Run `fxlint <resource_path> --json`. This gives the mechanical findings (P0xx/S0xx/C0xx) plus native
   verification (C007/C008) when the database is built.
2. Extract every PascalCase-looking call identifier the resource uses (a name matching `[A-Z][A-Za-z0-9]*\(`
   that isn't a `.`/`:` method call) and batch-verify them with `fxref resolve <names...>` — a second pass that
   can catch a native fxlint's own heuristics missed (e.g. one only ever used inside a table constructor).
3. Spawn `fivem-reviewer` (opus) with: the resource path, the fxlint JSON, the resolve output, and pointers to
   the rulebook's §14 checklist and `reference/security-checklist.md`. It returns ranked findings.
4. Present the findings to the user, most severe first, one line each:
   `severity | file:line | what | why | fix`. Follow with the reviewer's short verdict (ship / fix first).
5. Offer to apply fixes. If the user agrees, spawn `fivem-implementer` (sonnet) with the findings **you**
   judged worth acting on (not the raw review verbatim) and have it patch the resource, then re-run `fxlint` to
   confirm it's clean.

## Rules

- Never rewrite a whole file yourself, and don't ask the reviewer or implementer to either — findings and fixes
  stay targeted.
- Don't relay pure style nits that don't hide a real bug — the reviewer already skips those; if a raw fxlint
  `info` finding is purely stylistic, mention it only in passing.
- If `fxlint` is clean and the reviewer's verdict is "ship", say so plainly instead of inventing findings to
  fill space.
