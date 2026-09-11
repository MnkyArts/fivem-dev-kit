---
name: fivem-build
description: Orchestrated pipeline to design, implement, lint, review, deploy and hand off testing for a new FiveM/Cfx.re resource or feature. Use when the user asks to build, create, add, or implement a FiveM resource, script, or feature end to end.
argument-hint: <feature or resource description>
---

# fivem-build — the orchestrated pipeline

Runs in the **main session** — you plan, delegate, and verify; you never write a native call from memory.
`fxnew`/`fxlint`/`fxserver` are on PATH while this plugin is enabled; absolute fallback:
`${CLAUDE_PLUGIN_ROOT}/bin/<name>`.

## 0. Load context

Invoke the `fivem-scripting` skill (Skill tool) — it's the rulebook you and every subagent below follow. Read
`${CLAUDE_PLUGIN_ROOT}/config.json`'s `project` block for language/framework/ox_lib/author/workspace defaults.

## 1. Restate the spec

In **≤ 5 lines**: what the feature does, and the client/server split (what the client renders/decides vs. what
the server owns and validates). Ask **at most one** clarifying question — only if the answer would change the
architecture (data model, event shape, which side owns a piece of state). Otherwise state your assumptions
explicitly and move on.

## 2. Gather natives + read patterns (parallel)

- Spawn `fivem-native-scout` (haiku) with the spec. It returns a verified native list grouped client/server/
  shared, plus 3-6 relevant docs pages.
- At the same time, read whichever `skills/fivem-scripting/patterns/*.lua` shapes look relevant (e.g.
  `interaction-zone`, `validated-event`, `statebag-sync`, `callback`, `keymapping`, `model-loading`,
  `nui-bridge`, `player-lifecycle`, `resource-lifecycle`, `server-vehicle`) — that's your implementation
  reference to hand to the implementer, not the scout's job.

## 3. Write the plan — to a file

Write the plan to `<resource_dir>/PLAN.md` (create the dir if needed): files to create/edit with a one-line
purpose and a target line count each, event names (`resource:side:action`), state bags used,
`shared/config.lua` keys, which natives belong in which file (the scout's verified list, grouped per file), and
a draft in-game test checklist (shape: rulebook §13). Subagents read this file — never paste the plan or the
native list inline into a prompt; long prompts plus long outputs are exactly what blows the output window.

## 4. Scaffold

New resource: `fxnew <name> [--nui] [--framework ...] [--ox-lib]`. Existing resource: skip scaffolding, plan
which files to touch instead.

## 5. Implement — in slices, file by file

Spawn `fivem-implementer` (sonnet) with: the path to `PLAN.md`, the resource dir, and **the exact list of files
this run owns**. Keep every run small: at most ~4 files or ~600 lines of code per run. Slice by side:
run 1 = `shared/` + `server/`, run 2 = `client/`, run 3 = `html/` (NUI) if any. Runs whose files do not depend on
each other may go in parallel (one message, several Agent calls); otherwise sequentially. The implementer
writes one file per tool call, checks syntax as it goes and self-lints with `fxlint` before reporting.

If a run reports "files remaining" (it stopped near its turn budget), **resume that agent with `SendMessage`**
listing the remaining files — do not start over and do not widen the slice. Never ask an implementer for
"the whole resource in one go".

## 6. Lint + review

Run `fxlint <resource_dir>` yourself — don't just trust the implementer's self-report. Spawn `fivem-reviewer`
(opus) on the resource, giving it the lint result.

## 7. Fix findings

Send the reviewer's **confirmed** findings back to the `fivem-implementer` run that owns those files (resume it
with `SendMessage`; findings as `file:line — what — fix`, ≤ 15 per message) to fix. Fix genuinely trivial ones
yourself instead (a typo, a missing `fxlint-disable-next-line` justification) rather than round-tripping for
something that small.

## 8. Deploy

`fxserver deploy <resource_dir>` then `fxserver restart <name>`. Deploy may add an `ensure` line to
`server.cfg` (and back it up once) — say so explicitly when it happens; never print the cfg itself. If
`fxclient status` shows a dev player online, take `fxclient screenshot` after the restart and look at it.

## 9. Hand off testing

Print the in-game test checklist (rulebook §13's shape) and **stop**. Liam tests in-game — you do not.

## 10. When Liam reports back

Run `fxserver logs --errors --resource <name> --tail 200`, `fxclient logs --errors`,
`fxclient profile <name> --frames 300`, and `fxclient screenshot --resmon`. Diagnose from the log meanings in
rulebook §13, fix it (back to step 5), and repeat.

## Delegation rules (do not weaken these)

- Subagent models are fixed by role: `fivem-native-scout` = haiku, `fivem-implementer` = sonnet,
  `fivem-reviewer` = opus. **Never fable** for any subagent in this pipeline.
- The main session plans, delegates, and reviews — it never writes a native call from memory.
- Every subagent report is verified before you trust it: run `fxlint` yourself on what the implementer wrote,
  and spot-check a sample of the natives it claims to have used with `fxref show`.
