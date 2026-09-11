"""Heuristic JS/TS structural analysis for fxlint (mirrors luaparse.py).

Strings/comments are blanked out, then `{ ... }` nesting is tracked by depth;
a handful of regexes recognise which braces belong to a function/arrow body,
an if/for/while, or a `on(...)`/`onNet(...)`/`AddEventHandler(...)`/`setTick(...)`
callback so the same Frame/ParsedFile model as Lua can be reused by the rules.
"""
from __future__ import annotations

import re

from .model import Frame, ParsedFile, parse_suppressions


def strip_js(raw_lines: list, blank_strings: bool = True) -> list:
    """Blank comments (always) and string/template literal content (when
    blank_strings is True); same length and line count as the input so
    offsets stay comparable to the raw text. See strip_lua() for why both
    a strings-blanked ("clean") and strings-kept ("code") pass exist."""
    out = []
    state = None  # None | 'block_comment' | 'template'

    for line in raw_lines:
        chars = []
        i = 0
        n = len(line)

        if state == "block_comment":
            idx = line.find("*/")
            if idx == -1:
                out.append(" " * n)
                continue
            chars.append(" " * (idx + 2))
            i = idx + 2
            state = None
        elif state == "template":
            j = i
            closed = False
            while j < n:
                c = line[j]
                if c == "\\" and j + 1 < n:
                    j += 2
                    continue
                if c == "`":
                    closed = True
                    j += 1
                    break
                j += 1
            chars.append(" " * (j - i))
            i = j
            if not closed:
                out.append("".join(chars))
                continue
            state = None

        while i < n:
            ch = line[i]
            if line.startswith("//", i):
                chars.append(" " * (n - i))
                i = n
                break
            if line.startswith("/*", i):
                idx2 = line.find("*/", i + 2)
                if idx2 == -1:
                    chars.append(" " * (n - i))
                    state = "block_comment"
                    i = n
                    break
                chars.append(" " * (idx2 + 2 - i))
                i = idx2 + 2
                continue
            if ch in ("'", '"'):
                quote = ch
                j = i + 1
                buf = [ch]
                closed = False
                while j < n:
                    c2 = line[j]
                    if c2 == "\\" and j + 1 < n:
                        buf.append("  " if blank_strings else line[j:j + 2])
                        j += 2
                        continue
                    if c2 == quote:
                        buf.append(quote)
                        j += 1
                        closed = True
                        break
                    buf.append(" " if blank_strings else c2)
                    j += 1
                chars.append("".join(buf))
                i = j
                continue
            if ch == "`":
                j = i + 1
                buf = ["`"]
                closed = False
                while j < n:
                    c2 = line[j]
                    if c2 == "\\" and j + 1 < n:
                        buf.append("  " if blank_strings else line[j:j + 2])
                        j += 2
                        continue
                    if c2 == "`":
                        buf.append("`")
                        j += 1
                        closed = True
                        break
                    buf.append(" " if blank_strings else c2)
                    j += 1
                chars.append("".join(buf))
                i = j
                if not closed:
                    state = "template"
                    break
                continue
            chars.append(ch)
            i += 1

        out.append("".join(chars))

    return out


RE_FUNC = re.compile(r"\bfunction\s*(?:[A-Za-z_$][\w$]*)?\s*\((?P<params>[^)]*)\)\s*\{")
RE_ARROW_PARENS = re.compile(r"\((?P<params>[^)]*)\)\s*=>\s*\{")
RE_ARROW_BARE = re.compile(r"(?<![\w$.])(?P<param>[A-Za-z_$][\w$]*)\s*=>\s*\{")
RE_IF = re.compile(r"\bif\s*\([^{]*?\)\s*\{")
RE_FOR = re.compile(r"\bfor\s*\([^{]*?\)\s*\{")
RE_WHILE = re.compile(r"\bwhile\s*\([^{]*?\)\s*\{")
RE_HANDLER = re.compile(
    r"\b(?P<call>on|onNet|AddEventHandler)\s*\(\s*(?P<q>['\"`])(?P<name>.*?)(?P=q)\s*,\s*(?:async\s*)?"
    r"(?:function\s*\((?P<params1>[^)]*)\)|\((?P<params2>[^)]*)\)\s*=>|(?P<params3>[A-Za-z_$][\w$]*)\s*=>)\s*\{"
)
RE_SETTICK = re.compile(r"\bsetTick\s*\(\s*(?:async\s*)?(?:function\s*\(\s*\)|\(\s*\)\s*=>)\s*\{")


def _split_params(text: str) -> list:
    out = []
    for p in text.split(","):
        p = p.strip()
        if not p:
            continue
        p = p.split("=")[0].strip()
        p = p.lstrip(".").strip()
        if p:
            out.append(p)
    return out


def _line_triggers(line: str) -> dict:
    triggers: dict = {}
    for m in RE_HANDLER.finditer(line):
        params = _split_params(m.group("params1") or m.group("params2") or m.group("params3") or "")
        triggers[m.end() - 1] = dict(
            kind="function", is_handler=True, handler_call=m.group("call"),
            handler_name=m.group("name"), params=params, header=m.group(0),
        )
    for m in RE_SETTICK.finditer(line):
        triggers.setdefault(m.end() - 1, dict(kind="function", params=[], header=m.group(0)))
    for m in RE_FUNC.finditer(line):
        triggers.setdefault(m.end() - 1, dict(kind="function", params=_split_params(m.group("params"))))
    for m in RE_ARROW_PARENS.finditer(line):
        triggers.setdefault(m.end() - 1, dict(kind="function", params=_split_params(m.group("params"))))
    for m in RE_ARROW_BARE.finditer(line):
        triggers.setdefault(m.end() - 1, dict(kind="function", params=[m.group("param")]))
    for m in RE_IF.finditer(line):
        triggers.setdefault(m.end() - 1, dict(kind="if", header=m.group(0)))
    for m in RE_FOR.finditer(line):
        triggers.setdefault(m.end() - 1, dict(kind="for", header=m.group(0)))
    for m in RE_WHILE.finditer(line):
        triggers.setdefault(m.end() - 1, dict(kind="while", header=m.group(0)))
    return triggers


def _tokenize_frames(clean_lines: list, code_lines: list):
    """clean_lines (strings blanked) drives the brace-depth count, so a brace
    inside a string literal can never corrupt nesting; code_lines (strings
    kept) drives trigger matching, so handler/event names come out intact.
    Both are the same length with identical positions for anything outside a
    string, so positions found in one line up exactly in the other."""
    frames: list = []
    stack: list = []  # list[(frame_idx, open_depth)]
    depth = 0
    line_stack: dict = {}

    for i, line in enumerate(clean_lines):
        line_no = i + 1
        triggers = _line_triggers(code_lines[i] if i < len(code_lines) else line)
        for pos, ch in enumerate(line):
            if ch == "{":
                depth += 1
                info = triggers.get(pos)
                if info:
                    idx = len(frames)
                    frames.append(Frame(
                        index=idx, kind=info["kind"], start_line=line_no,
                        parent=(stack[-1][0] if stack else None),
                        is_handler=info.get("is_handler", False),
                        handler_call=info.get("handler_call", ""),
                        handler_name=info.get("handler_name"),
                        params=info.get("params", []),
                        header=info.get("header", ""),
                    ))
                    stack.append((idx, depth))
            elif ch == "}":
                if stack and stack[-1][1] == depth:
                    idx, _ = stack.pop()
                    frames[idx].end_line = line_no
                depth = max(0, depth - 1)
        line_stack[line_no] = [idx for idx, _ in stack]

    n = len(clean_lines)
    while stack:
        idx, _ = stack.pop()
        frames[idx].end_line = n
    return frames, line_stack


RE_DEF_FUNC_DECL = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")
RE_DEF_ASSIGN = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=")
RE_DEF_BARE_ASSIGN = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*=\s*(?:function\b|\([^)]*\)\s*=>|async\b)")


def collect_defined_names(clean_lines: list) -> set:
    names: set = set()
    text = "\n".join(clean_lines)
    for rx in (RE_DEF_FUNC_DECL, RE_DEF_ASSIGN, RE_DEF_BARE_ASSIGN):
        for m in rx.finditer(text):
            names.add(m.group(1))
    return names


def parse_js(path: str, rel_path: str, side, source_text: str, lang: str = "js") -> ParsedFile:
    raw_lines = source_text.splitlines()
    clean_lines = strip_js(raw_lines, blank_strings=True)
    code_lines = strip_js(raw_lines, blank_strings=False)
    frames, line_stack = _tokenize_frames(clean_lines, code_lines)
    disable_all_file, disabled_rules_file, disabled_next_line, disable_all_next_line = parse_suppressions(raw_lines)
    return ParsedFile(
        path=path,
        rel_path=rel_path,
        side=side,
        lang=lang,
        raw_lines=raw_lines,
        clean_lines=clean_lines,
        code_lines=code_lines,
        frames=frames,
        line_stack=line_stack,
        disabled_rules_file=disabled_rules_file,
        disable_all_file=disable_all_file,
        disabled_next_line=disabled_next_line,
        disable_all_next_line=disable_all_next_line,
    )
