# OpenCode adapter for fivem-dev-kit

This adds the existing FiveM kit to OpenCode without changing the Claude Code plugin. It installs live symlinks
for seven skills, `fivem` and `fivem-core` primary agents, four role-specific subagents, eight slash commands, and the
post-edit `fxlint` hook. The `fxref` database, kit `config.json`, FiveM CLIs, and rulebook stay in this checkout.

## Install

From the kit root:

```bash
python3 opencode/install.py
python3 opencode/install.py --check
opencode agent list
opencode debug skill
```

Restart a running OpenCode session after installation. The script adds links to
`~/.config/opencode/{agents,commands,plugins,skills}/` (or the corresponding `XDG_CONFIG_HOME` path). It does
not replace conflicts or edit your existing `opencode.json`; `--uninstall` removes only its own links.

Authenticate OpenCode Go through OpenCode if you have not already. Check the locally available model IDs with
`opencode models opencode-go`. This adapter uses:

| Role | OpenCode Go model | Reason for this default |
|---|---|---|
| `fivem` main coordinator | `opencode-go/deepseek-v4.1-flash` (high) | Strong tool-use and a large, currently promoted Go allowance. |
| `fivem-core` primary agent | `opencode-go/glm-5.3-flash` (max) | Dedicated core-framework agent; reads the core working agreement and design contract. |
| `fivem-native-scout` | `opencode-go/deepseek-v4.1-flash` (high) | Fast lookups, mechanically verified with `fxref`. |
| `fivem-implementer` | `opencode-go/glm-5.3-flash` (max) | Strongest independently measured agentic coding result in this affordable, private-code-compatible shortlist. |
| `fivem-reviewer` | `opencode-go/deepseek-v4.1-flash` (max) | Independent model family from the implementer, with a high request allowance. |
| `fivem-deep-reviewer` (explicit only) | `opencode-go/kimi-k3` (max) | Higher-cost second opinion, not used routinely. |

The model choices and caveats are detailed in [benchmark research](MODEL_RESEARCH.md). They are set in the
agent frontmatter, so selecting a different main model in OpenCode does not silently change the subagent
models. OpenCode Go limits are estimates and can change. Muse Spark 1.3 Contributor is **not** a default
because its discounted tier permits model training on prompts and completions; see the research note.

## Use

Start OpenCode in the FiveM workspace. Select the `fivem` primary agent when you want the full kit for normal
conversation, or `fivem-core` for the core framework. The plugin selects `fivem` by default when launched
from the FiveM workspace/resources and `fivem-core` when launched from `resources/core`, unless you already
set an explicit `default_agent`. It also adds `resources/core/AGENTS.md` to OpenCode's instructions in the
workspace because OpenCode does not automatically expand `@core/AGENTS.md` in `resources/CLAUDE.md`.

All seven skills are discoverable through OpenCode's `skill` tool and have corresponding slash commands:

```text
/fivem-build add a lockpicking minigame for unlocking cars without keys
/fivem-review resources/my-shop
/fivem-deep-review resources/my-shop   # explicit Kimi K3 second opinion
/fivem-core add a new money API
/fivem-reference find the native for locking vehicle doors
/fivem-scripting review my event validation
/fivem-server status
/fivem-client status
```

The hook adds `fxlint` findings to OpenCode's tool result after `write`, `edit`, or `apply_patch` modifies a
`.lua`, `.js`, or `.ts` file in a real FiveM resource. It is non-blocking and silent for unrelated files, just
like the Claude hook. The plugin also puts `bin/` on OpenCode's Bash PATH and provides
`FIVEM_DEV_KIT_ROOT`/`CLAUDE_PLUGIN_ROOT` for the shared skill text.

If `fxref` has not been built, run `fivem-dev-kit/bin/fxref build` once before using native search. See the
root [README](../README.md) for CLI requirements and server/client setup.
