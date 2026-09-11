# Claude Code plugin reference (verified against docs + Claude Code 2.1.268 on 2026-09-11)

Source of truth: https://code.claude.com/docs/en/{plugins, plugins-reference, plugin-marketplaces, skills, sub-agents, hooks}.md

## Plugin layout (plugin root = this repo)

```
<plugin-root>/
├── .claude-plugin/plugin.json   # ONLY plugin.json in here; `name` is the only required field
├── skills/<name>/SKILL.md       # preferred (commands/*.md is legacy but still works)
├── agents/*.md
├── hooks/hooks.json
├── bin/                         # added to the Bash tool's PATH while the plugin is enabled
└── (anything else: lib/, data/, docs/, tests/ are ordinary files)
```

Never nest skills/agents/hooks inside `.claude-plugin/`.

plugin.json optional fields: description, version, author {name,email}, displayName, homepage, repository, license, keywords,
skills/commands/agents/hooks (override default locations), userConfig, dependencies.

## Skills-dir plugin (how this kit is installed)

Any folder under `~/.claude/skills/` that contains `.claude-plugin/plugin.json` is loaded as plugin `<name>@skills-dir`
in every project, discovered in place (no copy). A SYMLINK `~/.claude/skills/<name> -> /elsewhere` works (tested on this
machine with 2.1.268). Editing SKILL.md takes effect immediately; editing hooks/agents needs `/reload-plugins` or a restart.
Disable: `claude plugin disable <name>@skills-dir`. Validate: `claude plugin validate <path>`.
Details: `claude plugin details <name>@skills-dir`.

## SKILL.md front matter

| Field | Meaning |
|---|---|
| name | display label; for plugin skills sets the command segment (`/<plugin>:<name>`, also bare `/<name>` if unclaimed) |
| description | what + when; drives auto-invocation. description + when_to_use truncated at 1536 chars in listings |
| when_to_use | extra trigger phrases |
| argument-hint | e.g. `"<description>"` |
| arguments | named args for `$name` substitution |
| disable-model-invocation | true = only manual `/name` |
| user-invocable | false = hidden from `/` menu, model only |
| allowed-tools / disallowed-tools | e.g. `Bash(${CLAUDE_PLUGIN_ROOT}/bin/fxref *)` |
| model / effort | override for the turn (`haiku`, `sonnet`, `opus`, `inherit`; effort low..max) |
| context: fork | run the skill in an isolated subagent; `agent:` picks the subagent type (general-purpose, Explore, Plan, or an `agents/` name); `background: false` blocks |
| hooks | hooks active while the skill is active |
| paths | globs restricting auto-activation |

Body substitutions: `$ARGUMENTS`, `$0`/`$1` (`$ARGUMENTS[N]`), `$name`. Escape `\$`.
Shell preprocessing: `` !`cmd` `` inline or a ```! fenced block runs before Claude sees the skill (2 min timeout; nonzero exit aborts).
Path variables (prose, shell blocks, allowed-tools): `${CLAUDE_SKILL_DIR}` (dir of this SKILL.md), `${CLAUDE_PLUGIN_ROOT}`
(plugin root, plugin skills only), `${CLAUDE_PLUGIN_DATA}` (persistent data dir), `${CLAUDE_PROJECT_DIR}`.

## agents/*.md front matter

Required: `name` (lowercase-hyphen), `description`. Optional: `tools` (list or comma string, e.g. `Read, Grep, Glob, Bash`),
`disallowedTools`, `model` (`haiku` | `sonnet` | `opus` | `inherit` | full id), `maxTurns`, `skills` (list — PRELOADS the full
skill content into the subagent), `memory` (user|project|local), `background`, `effort`, `isolation: worktree`, `color`.
`permissionMode`, `mcpServers`, `hooks` are ignored for plugin subagents.

## hooks/hooks.json

```json
{
  "description": "...",
  "hooks": {
    "PostToolUse": [
      { "matcher": "Write|Edit|MultiEdit",
        "hooks": [ { "type": "command", "command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/hooks-handlers/x.py"], "timeout": 30 } ] }
    ]
  }
}
```

stdin JSON: `{session_id, transcript_path, cwd, permission_mode, hook_event_name, tool_name, tool_input:{file_path,...}, tool_response, tool_use_id}`.
Exit 0 + stdout JSON `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "..."}}` feeds text back to Claude
(PostToolUse cannot block). Exit 2 blocks (PreToolUse only). Other exit codes = non-blocking error notice. Keep hooks fast and silent on failure.
