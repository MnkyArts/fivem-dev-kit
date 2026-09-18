---
name: fivem-build
description: Orchestrated pipeline to design, implement, lint, review, deploy and hand off testing for a new FiveM/Cfx.re resource or feature. Use when the user asks to build, create, add, or implement a FiveM resource, script, or feature end to end.
---

# fivem-build — the orchestrated pipeline

Runs in the **main session** — you plan, delegate, and verify; you never write a native call from memory.
`fxnew`/`fxlint`/`fxserver` are on PATH while this plugin is enabled; absolute fallback:
`${FIVEM_DEV_KIT_ROOT}/bin/<name>`.

## 0. Load context + detect the framework

Invoke the `fivem-scripting` skill (Skill tool) — it's the rulebook you and every subagent below follow. Read
`${FIVEM_DEV_KIT_ROOT}/config.json`'s `project` block for language/framework/ox_lib/author/workspace defaults.

**Framework detection** (do it before anything else): `project.framework` in `config.json`, or — when you are
extending an existing resource — its `fxmanifest.lua` (`dependency 'core'` / `'@core/import.lua'` ⇒ core;
`es_extended`/`qb-core`/`qbx_core`/`ox_core` ⇒ that one). When the answer is **core**, also invoke the
`fivem-core` skill now: core plugins have their own rules (the `Core.onReady` rule, `Core.Net.on` validation,
money via `Core.Money`, persistence via `Core.DB`, pages compiled into core's shell) and the rest of this
pipeline changes with them. `resources/core_example` is the reference plugin.

## 1. Restate the spec

In **≤ 5 lines**: what the feature does, and the client/server split (what the client renders/decides vs. what
the server owns and validates). Ask **at most one** clarifying question — only if the answer would change the
architecture (data model, event shape, which side owns a piece of state). Otherwise state your assumptions
explicitly and move on.

## 2. Gather natives + read patterns

- Invoke `fivem-native-scout` via the `task` tool with the spec **and the detected framework**. It returns a verified
  native list grouped client/server/shared, plus 3-6 relevant docs pages. On a core project it also returns a
  **separate `Core APIs` list** — every `Core.<Ns>.<fn>` the feature needs, each one confirmed with
  `fxref core show` and tagged `server`/`client` + `lib`/`proxy`. Core APIs are never mixed into the native
  list, and a `Core.*` function that does not resolve is reported as MISSING, never invented.
- At the same time, read whichever `skills/fivem-scripting/patterns/*.lua` shapes look relevant (e.g.
  `interaction-zone`, `validated-event`, `statebag-sync`, `callback`, `keymapping`, `model-loading`,
  `nui-bridge`, `player-lifecycle`, `resource-lifecycle`, `server-vehicle`) — that's your implementation
  reference to hand to the implementer, not the scout's job.

## 3. Write the plan — to a file

Write the plan to `<resource_dir>/PLAN.md` (create the dir if needed): files to create/edit with a one-line
purpose and a target line count each, event names (`resource:side:action`), state bags used,
`shared/config.lua` keys, which natives belong in which file (the scout's verified list, grouped per file), and
a draft in-game test checklist (shape: rulebook §13). On a **core** project add two more lines:
**`Core APIs used`** — one row per call, `namespace.fn → side/access` (from the scout's Core list) — and
**`UI page: yes/no`** (if yes: the page id, which side opens it, and that `core/ui` must be rebuilt).
Subagents read this file — never paste the plan or the native list inline into a prompt; long prompts plus
long outputs are exactly what blows the output window.

## 4. Scaffold

New resource: `fxnew <name>`. With `project.framework == core` that scaffolds a **core plugin** by default
(copy of `core/templates/plugin`, placeholders rewritten, self-linted with the K rules) — add `--no-ui` when
the plan says "UI page: no" (it deletes `ui/`), `--nui` to keep it. `--framework standalone` gets the old
non-core scaffold; `[--ox-lib]` as before. Existing resource: skip scaffolding, plan which files to touch.

## 5. Implement — in slices, file by file

Invoke `fivem-implementer` via the `task` tool with: the path to `PLAN.md`, the resource dir, and **the exact
list of files this run owns**. Keep every run small: at most ~4 files or ~600 lines of code per run. Slice by side:
run 1 = `shared/` + `server/`, run 2 = `client/`, run 3 = `html/` (NUI) if any. Runs whose files do not depend on
each other may go in parallel (one message, several `task` calls); otherwise sequentially. The implementer
writes one file per tool call, checks syntax as it goes and self-lints with `fxlint` before reporting.

If a run reports "files remaining", invoke a new `task` call for only those files. Pass the plan path and
exact remaining file list again; do not assume the old task session is resumable or widen the slice. Never
ask an implementer for "the whole resource in one go".

## 6. Lint + review

Run `fxlint <resource_dir>` yourself — don't just trust the implementer's self-report. Invoke
`fivem-reviewer` via the `task` tool on the resource, giving it the lint result. On a core plugin the **K rules** (core conventions) run too
and must end at **0 errors / 0 warnings**; `fxlint` on `resources/core` itself must stay clean as well.
`fivem-implementer` and `fivem-reviewer` must load `fivem-core` with the `skill` tool, so don't re-explain
core to them — point at `PLAN.md`.

## 7. Fix findings

Send the reviewer's **confirmed** findings to `fivem-implementer` using a new `task` call for the same files
(findings as `file:line — what — fix`, ≤ 15 per message) to fix. Fix genuinely trivial ones yourself instead
(a typo, a missing `fxlint-disable-next-line` justification) rather than round-tripping for something small.

## 8. Deploy

`fxserver deploy <resource_dir>` then `fxserver restart <name>`. Deploy may add an `ensure` line to
`server.cfg` (and back it up once) — say so explicitly when it happens; never print the cfg itself. If
`fxclient status` shows a dev player online, take `fxclient screenshot` after the restart and look at it.

**Core plugins** use the deploy dance instead (`fivem-core` §9): `fxserver deploy <dir>` →
`fxclient exec --server "refresh"` → `ensure <plugin>`. When a **page was added/changed or the manifest was
edited**: rebuild the shell first (`cd <core>/ui && npm run build` — `npm install` at `resources/` once), then
`refresh`, `restart core`, `ensure <plugin>` (restarting core stops every dependant, so re-`ensure` each one).
A page always gets an `fxclient screenshot` afterwards — open it in-game via the command/key first, then look
at the image; a page that never opens usually means the UI was not rebuilt or the ids do not match.

## 9. Hand off testing

Print the in-game test checklist (rulebook §13's shape) and **stop**. Liam tests in-game — you do not. On a
core plugin add the core items (`fivem-core` §10): interaction prompt appears in range and is gone out of
range; the page opens and closes with `ESC` (cursor released); money/notify/stat effects land exactly once
with the server's numbers; `restart <plugin>` removes every marker, label, blip, interaction, key hint and
page with no `onResourceStop` code; `restart core` while online replays the `Core.onReady` registrations; a
second client cannot trigger the event from ~10 m away and spamming it hits the cooldown; `resmon` idle
0.00–0.02 ms.

## 10. When Liam reports back

Run `fxserver logs --errors --resource <name> --tail 200`, `fxclient logs --errors`,
`fxclient profile <name> --frames 300`, and `fxclient screenshot --resmon`. Diagnose from the log meanings in
rulebook §13, fix it (back to step 5), and repeat.

## Delegation rules (do not weaken these)

- Subagent models are set in the OpenCode agent files: scout = DeepSeek V4.1 Flash, implementer =
  GLM-5.3-Flash, reviewer = DeepSeek V4.1 Flash. Do not override them in task calls. Use the optional
  Kimi K3 `fivem-deep-reviewer` only on explicit request; its quota is much smaller.
- The main session plans, delegates, and reviews — it never writes a native call from memory.
- Every subagent report is verified before you trust it: run `fxlint` yourself on what the implementer wrote,
  and spot-check a sample of the natives it claims to have used with `fxref show` — plus the `Core.*` calls
  with `fxref core show` on a core project.
