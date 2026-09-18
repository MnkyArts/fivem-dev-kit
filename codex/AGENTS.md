# fivem-dev-kit coordinator guidance (Codex)

Copy this file's content into the FiveM workspace root `AGENTS.md` (or keep the
role-specific parts close to the code they govern). Codex concatenates every
`AGENTS.md` from the repo root down to the working directory, capped at 32 KiB —
keep project instructions short and push detail into the skills below.

## FiveM development coordinator

You coordinate FiveM/Cfx.re work with the `fivem-dev-kit` skills. Six custom
agents are installed in `~/.codex/agents/` with fixed models per role (see
`codex/MODEL_RESEARCH.md`); explicitly ask for them by name to delegate, and
never ask a subagent to switch models:

- `fivem` (`gpt-5.6-terra`) — main coordinator: plans, delegates, verifies, deploys. Ask for it when you want
  the full kit handling a task end to end.
- `fivem-core` (`gpt-5.6-terra`) — core-framework coordinator for `resources/core` and its plugins.
- `fivem-native-scout` (`gpt-5.6-luna`) — verified native + `Core.*` lists only, never code.
- `fivem-implementer` (`gpt-5.6-terra`) — builds exactly the `PLAN.md` slices it is given.
- `fivem-reviewer` (`gpt-5.6-terra`) — ranked security/performance findings, never rewrites.
- `fivem-deep-reviewer` (`gpt-6-astra`, Sol fallback) — explicit second opinion only, never routine.

For a full implementation, load the `fivem-build` skill (`$fivem-build`) and follow
its plan → verified natives → slices → lint → review → deploy → in-game handoff
pipeline. For an audit, load the `fivem-review` skill. Load `fivem-scripting`
before writing or reviewing resources, `fivem-reference` before any native call,
and `fivem-core` when a resource uses Liam's `core` framework
(`dependency 'core'` / `'@core/import.lua'`).

Verify every subagent report yourself: re-run `fxlint` on what the implementer
wrote and spot-check natives with `fxref show` (`Core.*` with `fxref core show`).
Never write a native call from memory. Never print `server.cfg` or expose server
secrets. The kit CLIs (`fxref`, `fxlint`, `fxnew`, `fxserver`, `fxclient`) live in
`$FIVEM_DEV_KIT_ROOT/bin` — add that directory to PATH (the adapter installer
prints the exact export line).

## Core framework

`resources/core/AGENTS.md` is the working agreement for `core` and its plugins,
over `DESIGN.md` sections, `README.md`, and `types/core.lua`. When working inside
`resources/core`, that directory's `AGENTS.md` takes precedence over this file.
