"""Shared data model for fxlint: findings and the per-file parsed representation.

Both luaparse.py and jsparse.py build a ParsedFile using the same Frame/Finding
shapes so rules_perf.py / rules_sec.py / rules_style.py can stay language-agnostic
where possible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

LEVELS = ("error", "warn", "info")


@dataclass
class Finding:
    path: str
    line: int
    rule: str
    level: str  # 'error' | 'warn' | 'info'
    msg: str
    hint: str = ""

    def to_json(self) -> dict:
        return {"line": self.line, "rule": self.rule, "level": self.level, "msg": self.msg, "hint": self.hint}


# ---------------------------------------------------------------------------
# Structural model shared by the Lua and JS analysers
# ---------------------------------------------------------------------------

# Frame kinds
LOOP_KINDS = ("for", "while", "repeat")
BLOCK_KINDS = ("function", "if", "do") + LOOP_KINDS


@dataclass
class Frame:
    index: int
    kind: str  # 'function' | 'if' | 'for' | 'while' | 'repeat' | 'do'
    start_line: int
    end_line: int = -1
    parent: Optional[int] = None
    is_handler: bool = False
    handler_call: str = ""          # RegisterNetEvent / AddEventHandler / RegisterCommand / on / onNet / setTick ...
    handler_name: Optional[str] = None  # literal event/command name if the string literal was static
    params: list = field(default_factory=list)  # parameter names, only meaningful for 'function' frames
    header: str = ""  # raw header text of the construct (loop condition, etc.)

    @property
    def is_loop(self) -> bool:
        return self.kind in LOOP_KINDS


@dataclass
class ParsedFile:
    path: str            # absolute path
    rel_path: str         # path relative to resource root (posix separators)
    side: Optional[str]   # 'client' | 'server' | 'shared' | None (undetermined)
    lang: str              # 'lua' | 'js' | 'ts'
    raw_lines: list        # original source lines (no trailing newline), 1-indexed via [line-1]
    clean_lines: list      # comments AND string contents blanked out -- safe for structural/keyword regexes
    frames: list            # list[Frame], in creation order
    line_stack: dict        # line number -> list[int] (open frame indices at end of that line)
    disabled_rules_file: set    # rules disabled for the whole file (empty set disables nothing; None sentinel unused)
    code_lines: list = field(default_factory=list)  # comments blanked, strings kept intact -- use when you need a literal's text
    disable_all_file: bool = False
    # per-line suppression: line number -> set of rule ids suppressed on that line (via *-disable-next-line)
    disabled_next_line: dict = field(default_factory=dict)
    disable_all_next_line: set = field(default_factory=set)  # set of line numbers where *all* rules are suppressed
    table_depth_start: dict = field(default_factory=dict)  # line -> Lua {} nesting depth at the *start* of that line
    parse_error: Optional[str] = None

    def line_count(self) -> int:
        return len(self.raw_lines)

    def text(self, line: int) -> str:
        if 1 <= line <= len(self.raw_lines):
            return self.raw_lines[line - 1]
        return ""

    def clean(self, line: int) -> str:
        if 1 <= line <= len(self.clean_lines):
            return self.clean_lines[line - 1]
        return ""

    def code(self, line: int) -> str:
        """Like clean(), but string literal contents are preserved -- use this
        whenever a regex needs to read an actual string value (event names,
        command names, resource names), not just match code structure."""
        if 1 <= line <= len(self.code_lines):
            return self.code_lines[line - 1]
        return self.clean(line)

    def open_frames(self, line: int) -> list:
        idxs = self.line_stack.get(line, [])
        return [self.frames[i] for i in idxs]

    def enclosing_loop(self, line: int) -> Optional[Frame]:
        for f in reversed(self.open_frames(line)):
            if f.is_loop:
                return f
        return None

    def in_loop(self, line: int) -> bool:
        return self.enclosing_loop(line) is not None

    def enclosing_handler(self, line: int) -> Optional[Frame]:
        for f in reversed(self.open_frames(line)):
            if f.is_handler:
                return f
        return None

    def range_text(self, start: int, end: int, clean: bool = True) -> str:
        lines = self.clean_lines if clean else self.raw_lines
        if end < 0:
            end = len(lines)
        start = max(1, start)
        end = min(len(lines), end)
        return "\n".join(lines[start - 1:end])

    def is_suppressed(self, line: int, rule: str) -> bool:
        if self.disable_all_file or rule in self.disabled_rules_file:
            return True
        if line in self.disable_all_next_line:
            return True
        rules = self.disabled_next_line.get(line)
        if rules and rule in rules:
            return True
        return False


# ---------------------------------------------------------------------------
# Suppression-comment scanning (shared between Lua "--" and JS/TS "//")
# ---------------------------------------------------------------------------

import re as _re

_SUPPRESS_RE = _re.compile(
    r"fxlint-disable(?P<next>-next-line)?\b[:\s]*(?P<rules>[A-Za-z0-9_,\s]*)"
)


def parse_suppressions(raw_lines: list):
    """Scan raw source lines for fxlint-disable[-next-line] comments.

    Works for both '--' (Lua) and '//' (JS/TS) comment styles since we just
    search for the marker text anywhere on the line -- real fxlint directives
    are always written inside a comment in practice, and matching the bare
    marker text keeps this simple and dependency-free.

    Returns (disable_all_file, disabled_rules_file, disabled_next_line, disable_all_next_line).
    """
    disable_all_file = False
    disabled_rules_file: set = set()
    disabled_next_line: dict = {}
    disable_all_next_line: set = set()

    for i, line in enumerate(raw_lines, start=1):
        if "fxlint-disable" not in line:
            continue
        m = _SUPPRESS_RE.search(line)
        if not m:
            continue
        rule_ids = {r.strip().upper() for r in m.group("rules").split(",") if r.strip()}
        if m.group("next"):
            target = i + 1
            if rule_ids:
                disabled_next_line.setdefault(target, set()).update(rule_ids)
            else:
                disable_all_next_line.add(target)
        else:
            if rule_ids:
                disabled_rules_file.update(rule_ids)
            else:
                disable_all_file = True

    return disable_all_file, disabled_rules_file, disabled_next_line, disable_all_next_line
