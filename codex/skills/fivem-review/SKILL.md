---
name: fivem-review
description: Review an existing FiveM/Cfx.re resource for performance, security and correctness issues against the fivem-scripting rulebook. Use when the user asks to review, audit, or check a resource or diff before shipping it.
---

# fivem-review — audit an existing resource

Runs in the **main session**. `fxlint`/`fxref` are on PATH once `bin/` is added (see the Codex adapter README);
absolute fallback: `${FIVEM_DEV_KIT_ROOT}/bin/<name>`. Argument: a resource directory path.

Codex has no `task` tool: to delegate, explicitly ask for the named custom agent
(e.g. "Have the `fivem-reviewer` subagent audit this target: ..."). Subagents are defined in
`~/.codex/agents/` by the adapter installer with fixed models per role.

## Steps

0. Is it a **core plugin** (manifest has `dependency 'core'` / `'@core/import.lua'`) or core itself? Then
   invoke the `fivem-core` skill first — its rules are what the review is against, on top of the rulebook.
1. Run `fxlint <resource_path> --json`. This gives the mechanical findings (P0xx/S0xx/C0xx) plus native
   verification (C007/C008) when the database is built. On a core resource the **K rules** (K001–K017, core
   conventions) run too — they must end at 0 errors / 0 warnings. K006 (`backdrop-filter` in `ui/`) is an
   error, never a nit; so are K014 (a `core_ui` folder no `files {}` entry packs), K015 (a `ui/dist` core's own
   validator would reject) and K016 (`registerPage { script/style }`, removed with core DESIGN §38).
2. Extract every PascalCase-looking call identifier the resource uses (a name matching `[A-Z][A-Za-z0-9]*\(`
   that isn't a `.`/`:` method call) and batch-verify them with `fxref resolve <names...>` — a second pass that
   can catch a native fxlint's own heuristics missed (e.g. one only ever used inside a table constructor).
   On a core resource do the same for framework calls: collect every `Core.<Ns>.<fn>` and run
   `fxref core resolve <names...>`; anything MISSING is a probable hallucinated API and a finding.
3. Ask the `fivem-reviewer` subagent to audit the target with: the resource path, the fxlint JSON, the resolve output(s),
   and pointers to the rulebook's §14 checklist and `reference/security-checklist.md`. It returns ranked findings. On a core
   plugin it must also check: every registration *into* core sits inside `Core.onReady` (K004, `registerPage`
   and `onRequest` included) and no `onResourceStop` re-does core's cleanup (K005); every `Core.Net.on` carries
   the right `opts` in the right
   order (schema → cooldown → requireLoaded → permission → distance) and no handler re-validates *after*
   acting; money only through `Core.Money` and persistence only through `Core.DB` (never files or a second
   database); callbacks tested with `Core.Utils.isCallable`, never `type(v) == 'function'`. On a **UI plugin**
   (core DESIGN §38) add: no side effect at module scope in `ui/src/index.ts` — listeners, timers and store
   subscriptions belong in `setup(ctx)` and must be tied to `ctx.scope`, or a `restart` leaves a second one
   behind; no `ui_page`/`SetNuiFocus`/`SendNUIMessage`/`RegisterNuiCallback` anywhere in the plugin; `core_ui`
   and the `files { '<dir>/**' }` entry agree, the committed `ui/dist` is current, and no `client_scripts` glob
   reaches into it; no unscoped global selector in the plugin's CSS; `Core.UI.patch` paths are Lua's view
   (**1-based**, `items.1` is the first element) and id-keyed collections use string keys; every `request`
   has a timeout and a handler on the other side; and a page must survive its plugin restarting — Lua owns
   whether it is open, so `onOpen`/`setup` may run again at any time.
4. Present the findings to the user, most severe first, one line each:
   `severity | file:line | what | why | fix`. Follow with the reviewer's short verdict (ship / fix first).
5. Offer to apply fixes. If the user agrees, ask the `fivem-implementer` subagent to patch the resource with the findings
   **you** judged worth acting on (not the raw review verbatim), then re-run `fxlint` to
   confirm it's clean.

For an explicit request for a deeper second opinion, ask the `fivem-deep-reviewer` (`gpt-6-astra`,
`gpt-5.6-sol` fallback where Astra is unavailable) subagent to
audit the same target and compare only its independently confirmed findings. Do not use the expensive Astra/Sol agent
by default.

## Rules

- Never rewrite a whole file yourself, and don't ask the reviewer or implementer to either — findings and fixes
  stay targeted.
- Don't relay pure style nits that don't hide a real bug — the reviewer already skips those; if a raw fxlint
  `info` finding is purely stylistic, mention it only in passing.
- If `fxlint` is clean and the reviewer's verdict is "ship", say so plainly instead of inventing findings to
  fill space.
