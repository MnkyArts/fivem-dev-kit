"""Heuristic Lua structural analysis for fxlint.

This is not a real Lua parser. It strips strings/comments (so keywords
inside string literals don't confuse anything) and then tracks block
nesting (function/if/for/while/repeat/do ... end) with a simple stack, far
enough to answer "is line N inside loop X's body" / "... inside event
handler Y's body", which is all the P0xx/S0xx/C0xx rules need.
"""
from __future__ import annotations

import re

from .model import Frame, ParsedFile, parse_suppressions

_STRING = r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""

RE_KEYWORD = re.compile(r"\b(function|if|for|while|repeat|until|do|then|else|elseif|end)\b")
RE_HANDLER_CALL = re.compile(
    r"\b(RegisterNetEvent|RegisterServerEvent|AddEventHandler|RegisterCommand)\s*\(\s*("
    + _STRING + r")\s*,\s*function\b"
)
RE_FUNC_PARAMS = re.compile(r"\(([^)]*)\)")


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] in "'\"" and s[-1] == s[0]:
        s = s[1:-1]
    return s


def strip_lua(raw_lines: list, blank_strings: bool = True) -> list:
    """Blank out comments (always) and string-literal content (when
    blank_strings is True), keeping line count and -- for non-blanked spans
    -- exact character offsets identical to the input, so positions found in
    the cleaned text line up with the raw text.

    blank_strings=True is what the block/loop tokenizer uses (a keyword
    inside a string literal must never affect nesting). blank_strings=False
    ("code_lines") keeps string contents so rules that need a literal's
    actual text (an event name, a command name...) can read it, while still
    being safe from text inside comments."""
    out = []
    state = None  # None | ('comment', level) | ('string', level)
    long_open_re = re.compile(r"\[(=*)\[")

    for line in raw_lines:
        chars = []
        i = 0
        n = len(line)

        if state is not None:
            _kind, level = state
            closer = "]" + "=" * level + "]"
            idx = line.find(closer)
            if idx == -1:
                out.append(" " * n)
                continue
            chars.append(" " * (idx + len(closer)))
            i = idx + len(closer)
            state = None

        while i < n:
            ch = line[i]
            if line.startswith("--", i):
                j = i + 2
                m = long_open_re.match(line, j)
                if m:
                    level = len(m.group(1))
                    consumed = m.end()
                    closer = "]" + "=" * level + "]"
                    idx2 = line.find(closer, consumed)
                    if idx2 == -1:
                        chars.append(" " * (n - i))
                        state = ("comment", level)
                        i = n
                        break
                    chars.append(" " * (idx2 + len(closer) - i))
                    i = idx2 + len(closer)
                    continue
                chars.append(" " * (n - i))
                i = n
                break
            if ch in ("'", '"'):
                quote = ch
                j = i + 1
                buf = [ch]
                while j < n:
                    c2 = line[j]
                    if c2 == "\\" and j + 1 < n:
                        buf.append("  " if blank_strings else line[j:j + 2])
                        j += 2
                        continue
                    if c2 == quote:
                        buf.append(quote)
                        j += 1
                        break
                    buf.append(" " if blank_strings else c2)
                    j += 1
                chars.append("".join(buf))
                i = j
                continue
            if ch == "[":
                m = long_open_re.match(line, i)
                if m:
                    level = len(m.group(1))
                    consumed = m.end()
                    closer = "]" + "=" * level + "]"
                    idx2 = line.find(closer, consumed)
                    if idx2 == -1:
                        chars.append(" " * (n - i))
                        state = ("string", level)
                        i = n
                        break
                    chars.append(" " * (idx2 + len(closer) - i))
                    i = idx2 + len(closer)
                    continue
                chars.append(ch)
                i += 1
                continue
            chars.append(ch)
            i += 1

        out.append("".join(chars))

    return out


def _tokenize_frames(clean_lines: list, raw_lines: list):
    frames: list = []
    stack: list = []
    awaiting_do: list = []  # indices (into frames) of for/while frames that haven't seen their 'do' yet
    line_stack: dict = {}

    def push(kind, line, **kw) -> int:
        idx = len(frames)
        frames.append(Frame(index=idx, kind=kind, start_line=line, parent=(stack[-1] if stack else None), **kw))
        stack.append(idx)
        return idx

    def pop(end_line):
        if stack:
            idx = stack.pop()
            frames[idx].end_line = end_line

    n = len(clean_lines)
    for i in range(n):
        line_no = i + 1
        clean = clean_lines[i]
        raw = raw_lines[i] if i < len(raw_lines) else ""
        handler_m = RE_HANDLER_CALL.search(raw)

        for m in RE_KEYWORD.finditer(clean):
            kw = m.group(1)
            if kw == "function":
                params: list = []
                pm = RE_FUNC_PARAMS.search(clean, m.end())
                if pm and pm.start() <= m.end() + 2:
                    params = [p.strip() for p in pm.group(1).split(",") if p.strip() and p.strip() != "..."]
                is_handler = bool(handler_m and handler_m.end() == m.end())
                push(
                    "function", line_no, params=params,
                    is_handler=is_handler,
                    handler_call=handler_m.group(1) if is_handler else "",
                    handler_name=_strip_quotes(handler_m.group(2)) if is_handler else None,
                    header=raw.strip(),
                )
            elif kw == "if":
                push("if", line_no, header=raw.strip())
            elif kw == "for":
                idx = push("for", line_no, header=raw.strip())
                awaiting_do.append(idx)
            elif kw == "while":
                idx = push("while", line_no, header=raw.strip())
                awaiting_do.append(idx)
            elif kw == "repeat":
                push("repeat", line_no, header=raw.strip())
            elif kw == "do":
                if awaiting_do and stack and awaiting_do[-1] == stack[-1]:
                    awaiting_do.pop()
                else:
                    push("do", line_no)
            elif kw in ("then", "else", "elseif"):
                pass
            elif kw == "until":
                if stack:
                    # repurpose header to hold the until-condition text (the
                    # 'repeat' line itself carries no condition worth keeping)
                    frames[stack[-1]].header = raw.strip()
                pop(line_no)
            elif kw == "end":
                pop(line_no)

        line_stack[line_no] = list(stack)

    while stack:
        pop(n)

    return frames, line_stack


RE_DEF_FUNCTION = re.compile(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*(?:[.:][A-Za-z_][A-Za-z0-9_]*)*)\s*\(")
RE_DEF_LOCAL_FUNCTION = re.compile(r"\blocal\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
RE_DEF_ASSIGN_FUNC = re.compile(r"(?<![.\w:])([A-Za-z_][A-Za-z0-9_]*)\s*=\s*function\s*\(")
RE_DEF_LOCAL_VARS = re.compile(r"^\s*local\s+([A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)")


def collect_defined_names(clean_lines: list) -> set:
    """All names this file defines (function or variable, local or global) --
    used to keep the native-call heuristic from flagging homegrown helpers."""
    names: set = set()
    text = "\n".join(clean_lines)
    for m in RE_DEF_FUNCTION.finditer(text):
        dotted = m.group(1)
        names.add(dotted.split(".")[0].split(":")[0])
        names.add(dotted.split(".")[-1].split(":")[-1])
    for m in RE_DEF_LOCAL_FUNCTION.finditer(text):
        names.add(m.group(1))
    for m in RE_DEF_ASSIGN_FUNC.finditer(text):
        names.add(m.group(1))
    for line in clean_lines:
        m = RE_DEF_LOCAL_VARS.match(line)
        if m:
            for part in m.group(1).split(","):
                part = part.strip()
                if part:
                    names.add(part)
    return names


def _table_depth_start(clean_lines: list) -> dict:
    """Lua {} nesting depth *at the start* of each line -- independent of the
    function/if/for/while keyword frame tracker, since table constructors
    (very commonly multi-line, e.g. Config tables) don't use 'end'."""
    depth = 0
    out = {}
    for i, line in enumerate(clean_lines, start=1):
        out[i] = depth
        for ch in line:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth = max(0, depth - 1)
    return out


def parse_lua(path: str, rel_path: str, side, source_text: str) -> ParsedFile:
    raw_lines = source_text.splitlines()
    clean_lines = strip_lua(raw_lines, blank_strings=True)
    code_lines = strip_lua(raw_lines, blank_strings=False)
    frames, line_stack = _tokenize_frames(clean_lines, raw_lines)
    disable_all_file, disabled_rules_file, disabled_next_line, disable_all_next_line = parse_suppressions(raw_lines)
    return ParsedFile(
        path=path,
        rel_path=rel_path,
        side=side,
        lang="lua",
        raw_lines=raw_lines,
        clean_lines=clean_lines,
        code_lines=code_lines,
        frames=frames,
        line_stack=line_stack,
        disabled_rules_file=disabled_rules_file,
        disable_all_file=disable_all_file,
        disabled_next_line=disabled_next_line,
        disable_all_next_line=disable_all_next_line,
        table_depth_start=_table_depth_start(clean_lines),
    )
