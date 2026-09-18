# Codex adapter for fivem-dev-kit

This adds the existing FiveM kit to Codex CLI / IDE / app without changing the Claude Code plugin. It installs
live symlinks for seven skills, six custom agents (two coordinators + four role subagents), and the post-edit `fxlint` hook. The `fxref`
database, kit `config.json`, FiveM CLIs, and rulebook stay in this checkout.

Codex has no slash-command directory: skills are invoked with `$`-mention (`$fivem-build`) or picked up
automatically when the task matches the skill description. Subagents only spawn when explicitly asked for by
name — the `fivem-build` / `fivem-review` skills tell the main session exactly when to ask.

## Install

From the kit root:

```bash
python3 codex/install.py
python3 codex/install.py --check
```

The script links skills to `~/.agents/skills/`, subagents to `~/.codex/agents/` (or `$CODEX_HOME/agents/`), and
merges the `fxlint` hook into `~/.codex/hooks.json`. It does not replace conflicts or edit your existing
`~/.codex/config.toml`; `--uninstall` removes only its own links and hook entry. It prints three `export`
lines — add them to `~/.bashrc` (or equivalent) so Codex shells see the kit CLIs:

```bash
export FIVEM_DEV_KIT_ROOT=/path/to/fivem-dev-kit
export CLAUDE_PLUGIN_ROOT=$FIVEM_DEV_KIT_ROOT  # shared skill text also uses this name
export PATH="$FIVEM_DEV_KIT_ROOT/bin:$PATH"
```

Then restart Codex and copy `codex/AGENTS.md` into the FiveM workspace root `AGENTS.md` (append to the existing
file if there is one). Optional: copy the profiles you want from `codex/config.example.toml` into
`.codex/config.toml` (trusted workspace) or `~/.codex/config.toml`.

Check installed versions with `codex --version` (GPT-5.6 tiers need a recent CLI). This adapter uses:

| Role | Codex model | Reason for this default |
|---|---|---|
| `fivem` / `fivem-core` coordinators | `gpt-5.6-terra` (high) | Best value default; within ~2 pts of Sol on coding benchmarks at half the price. |
| `fivem-native-scout` | `gpt-5.6-luna` (medium) | Mechanical `fxref` lookups; 10–25× cheaper, largest allowance. |
| `fivem-implementer` | `gpt-5.6-terra` (high) | Bounded slices; escalate a stalled slice once to Astra (Sol fallback), then stop retrying. |
| `fivem-reviewer` | `gpt-5.6-terra` (high) | Checklist/security review; coordinator re-verifies with `fxlint`/`fxref`. |
| `fivem-deep-reviewer` (explicit only) | `gpt-6-astra` (high) | +14 pts SecPass over Sol in independent tests; smallest allowance, never routine. Sol fallback where Astra is unavailable. |

The model choices and caveats are detailed in [benchmark research](MODEL_RESEARCH.md). They are set in the
subagent files, so switching the main model does not silently change the subagent models. Unlike the OpenCode
adapter, the routine Codex roles share the GPT-5.6 family — reviewer independence comes from the separate checklist pass
plus the coordinator's own re-verification, not from model diversity.

Astra needs Codex CLI ≥ 0.153.0 and a staged-rollout grant (Enterprise: admin-enabled; Plus/Business Standard:
limited; Free/Go: none) — check `/model`. Without Astra, set `fivem-deep-reviewer` back to `gpt-5.6-sol`.

## Use

Start Codex in the FiveM workspace and invoke skills explicitly until you trust auto-triggering:

```text
$fivem-build add a lockpicking minigame for unlocking cars without keys
$fivem-review resources/my-shop
```

`$fivem-reference`, `$fivem-scripting`, `$fivem-server`, `$fivem-client`, and `$fivem-core` work the same way.
For a Sol second opinion, explicitly ask: "Have the `fivem-deep-reviewer` subagent audit resources/my-shop".
Inspect parallel subagent threads with `/agent`.

The hook adds `fxlint` findings as extra context after Codex writes or edits a `.lua`, `.js`, or `.ts` file in
a real FiveM resource (via `apply_patch`). It is non-blocking and silent for unrelated files, just like the
Claude hook. User-level hooks need no project-trust approval. The first hook run may prompt once for hook
trust — approve it.

Sandboxing: scout/reviewer subagents run `read-only`; the implementer runs `workspace-write`. `fxref`/`fxlint`
are local binaries — if Codex asks to approve them, allow `python3` + `$FIVEM_DEV_KIT_ROOT/bin/*` for the
workspace.

If `fxref` has not been built, run `fivem-dev-kit/bin/fxref build` once before using native search. See the
root [README](../README.md) for CLI requirements and server/client setup.
