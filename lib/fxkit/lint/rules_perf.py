"""P001-P007: performance rules.

See docs/fxlint.md for the human-readable catalogue; this module is the
implementation. Every check function takes a ParsedFile and returns a list
of Finding. Loop/handler scoping relies on ParsedFile.frames (built by
luaparse.py / jsparse.py) rather than re-parsing text.
"""
from __future__ import annotations

import re

from .model import Finding

RE_WAIT = re.compile(r"\b(?:Citizen\.)?Wait\s*\(\s*([^()]*)\)")
RE_DELAY = re.compile(r"\bawait\s+Delay\s*\(\s*([^()]*)\)")
RE_JUSTIFY = re.compile(r"(?:--|//)\s*per-frame:")

RE_CREATE_THREAD = re.compile(r"(?<![.\w:])CreateThread\s*\(")
RE_SET_TICK = re.compile(r"(?<![.\w:])setTick\s*\(")
RE_TIMER_OPEN = re.compile(r"\b(SetTimeout|setInterval|setTick)\s*\(")
RE_TRIGGER_CLIENT_BCAST = re.compile(r"(?<![.\w:])(TriggerClientEvent|emitNet)\s*\(\s*(" + r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"" + r")\s*,\s*-1\s*[,)]")
RE_PLAYER_PED_ID = re.compile(r"(?<![.\w:])PlayerPedId\s*\(\s*\)")

EXPENSIVE_EXACT = (
    "GetPlayers", "GetGamePool", "GetActivePlayers", "GetAllVehicles", "GetVehiclePedIsIn",
    "TriggerServerEvent", "TriggerClientEvent",
)
EXPENSIVE_PREFIX = ("GetClosest",)
RE_JSON_CODEC = re.compile(r"\bjson\.(encode|decode)\s*\(")
RE_EXPENSIVE_NATIVE = re.compile(
    r"(?<![.\w:])(" + "|".join(re.escape(n) for n in EXPENSIVE_EXACT) + r")\s*\("
)
RE_EXPENSIVE_PREFIXED = re.compile(
    r"(?<![.\w:])(" + "|".join(re.escape(p) for p in EXPENSIVE_PREFIX) + r"[A-Za-z0-9_]*)\s*\("
)


def _int_literal(text: str):
    text = text.strip()
    m = re.match(r"^-?\d+$", text)
    if not m:
        return None
    return int(text)


def direct_enclosing_loop(pf, line: int):
    """Innermost loop directly enclosing `line`, not crossing into a nested
    function/closure -- except a function frame that *starts on this same
    line* (the callback literal passed at this very call site)."""
    for f in reversed(pf.open_frames(line)):
        if f.kind == "function" and f.start_line == line:
            continue
        if f.is_loop:
            return f
        if f.kind == "function":
            return None
    return None


def direct_enclosing_timer(pf, line: int):
    for f in reversed(pf.open_frames(line)):
        if f.kind == "function" and f.start_line == line:
            continue
        if f.is_loop:
            return None
        if f.kind == "function":
            if RE_TIMER_OPEN.search(pf.clean(f.start_line)):
                return f
            return None
    return None


def _loop_end(pf, frame) -> int:
    return frame.end_line if frame.end_line > 0 else pf.line_count()


def _wait_like_calls(pf):
    """[(line, argtext)] for every Wait()/Citizen.Wait()/await Delay() call in the file."""
    calls = []
    for i, line in enumerate(pf.clean_lines, start=1):
        for m in RE_WAIT.finditer(line):
            calls.append((i, m.group(1).strip()))
        for m in RE_DELAY.finditer(line):
            calls.append((i, m.group(1).strip()))
    return calls


def _group_by_direct_loop(pf, calls):
    """{loop_frame_index: [(line, argtext), ...]}, dropping calls not directly in a loop."""
    groups: dict = {}
    for line, arg in calls:
        loop = direct_enclosing_loop(pf, line)
        if loop is not None:
            groups.setdefault(loop.index, []).append((line, arg))
    return groups


def _is_adaptive(pf, calls_in_loop) -> bool:
    distinct = {a for _, a in calls_in_loop}
    if len(distinct) < 2:
        return False
    lines = [ln for ln, _ in calls_in_loop]
    between = pf.range_text(min(lines), max(lines))
    return bool(re.search(r"\b(else|elseif)\b", between))


def _justified(pf, frame, wait_line: int) -> bool:
    if RE_JUSTIFY.search(pf.text(wait_line)):
        return True
    for ln in range(max(1, frame.start_line - 2), frame.start_line + 1):
        if RE_JUSTIFY.search(pf.text(ln)):
            return True
    return False


def _has_own_break(pf, frame) -> bool:
    """Does `frame` (a while/repeat loop) contain its own break/return, not one
    belonging to a nested loop or function? A loop that can exit on its own is
    not the "truly infinite, will freeze the server" case P001 cares about."""
    start, end = frame.start_line, _loop_end(pf, frame)
    for ln in range(start, end + 1):
        if not re.search(r"\b(break|return)\b", pf.clean(ln)):
            continue
        owner = None
        for f in reversed(pf.open_frames(ln)):
            if f.index == frame.index:
                owner = frame
                break
            if f.kind == "function" or f.is_loop:
                owner = f
                break
        if owner is not None and owner.index == frame.index:
            return True
    return False


def _condition_text(frame):
    if frame.kind == "while":
        m = re.match(r"\bwhile\s+(.*?)\s+do\b", frame.header)  # Lua: while COND do
        if m:
            return m.group(1).strip()
        m = re.match(r"\bwhile\s*\((.*)\)\s*\{?\s*$", frame.header)  # JS: while (COND) {
        if m:
            return m.group(1).strip()
        return None
    if frame.kind == "repeat":
        m = re.match(r"\buntil\s+(.*)", frame.header)  # Lua only -- JS never produces 'repeat' frames
        return m.group(1).strip() if m else None
    return None


def _norm_cond(cond: str) -> str:
    cond = cond.strip()
    while cond.startswith("(") and cond.endswith(")"):
        cond = cond[1:-1].strip()
    return cond


def check_p001(pf) -> list:
    findings = []
    for f in pf.frames:
        if f.kind not in ("while", "repeat"):
            continue
        cond = _condition_text(f)
        if cond is None:
            continue
        cond = _norm_cond(cond)
        infinite = (f.kind == "while" and cond in ("true", "1")) or (f.kind == "repeat" and cond in ("false", "0"))
        if not infinite:
            continue
        start, end = f.start_line, _loop_end(pf, f)
        body = pf.range_text(start, end)
        if RE_WAIT.search(body) or RE_DELAY.search(body):
            continue
        if _has_own_break(pf, f):
            continue
        findings.append(Finding(
            pf.rel_path, start, "P001", "error",
            "infinite loop has no Wait()/Citizen.Wait() (or await Delay()) -- freezes the whole runtime",
            "add a Wait(...) every iteration so the scheduler can yield, or a break/return if this should terminate",
        ))
    return findings


def check_p002_p003(pf) -> list:
    findings = []
    groups = _group_by_direct_loop(pf, _wait_like_calls(pf))
    for idx, calls in groups.items():
        frame = pf.frames[idx]
        adaptive = _is_adaptive(pf, calls)
        if adaptive:
            continue
        for ln, arg in calls:
            val = _int_literal(arg)
            if val is None or val < 0:
                continue
            if _justified(pf, frame, ln):
                continue
            if val <= 15:
                findings.append(Finding(
                    pf.rel_path, ln, "P002", "warn",
                    f"Wait({val}) inside a loop with no adaptive branch -- this is a per-frame loop",
                    "use an adaptive Wait (0 near / 250-1000 far), switch to an event/state bag/lib.points, "
                    "or add a '-- per-frame:' justification comment if this really must run every tick",
                ))
            elif val <= 99:
                findings.append(Finding(
                    pf.rel_path, ln, "P003", "info",
                    f"Wait({val}) inside a loop -- consider raising the interval if it doesn't need to be this tight",
                    "raise towards 100-1000ms unless this genuinely needs sub-100ms responsiveness",
                ))
    return findings


def check_p004(pf) -> list:
    findings = []
    for i, line in enumerate(pf.clean_lines, start=1):
        for rx, name in ((RE_CREATE_THREAD, "CreateThread"), (RE_SET_TICK, "setTick")):
            if not rx.search(line):
                continue
            loop = direct_enclosing_loop(pf, i)
            handler = pf.enclosing_handler(i)
            if loop is not None:
                findings.append(Finding(
                    pf.rel_path, i, "P004", "warn",
                    f"{name}(...) created inside a loop -- a new thread/tick handler is spawned every iteration",
                    f"move the {name} call outside the loop, or guard it so it only runs once",
                ))
            elif handler is not None:
                findings.append(Finding(
                    pf.rel_path, i, "P004", "warn",
                    f"{name}(...) created inside an event handler -- a new thread/tick handler is spawned every time the event fires",
                    f"move the {name} call outside the handler (run once at resource start), or track/clear the previous one",
                ))
    return findings


def check_p005(pf) -> list:
    findings = []
    groups = _group_by_direct_loop(pf, _wait_like_calls(pf))
    low_wait_loops = {
        idx for idx, calls in groups.items()
        if any((_int_literal(a) is not None and 0 <= _int_literal(a) <= 15) for _, a in calls)
    }
    if not low_wait_loops:
        return findings
    for idx in low_wait_loops:
        frame = pf.frames[idx]
        start, end = frame.start_line, _loop_end(pf, frame)
        for ln in range(start, end + 1):
            direct = direct_enclosing_loop(pf, ln)
            if direct is None or direct.index != idx:
                continue  # belongs to a loop nested inside this one -- let that one own it
            line = pf.clean(ln)
            names = set()
            for m in RE_EXPENSIVE_NATIVE.finditer(line):
                names.add(m.group(1))
            for m in RE_EXPENSIVE_PREFIXED.finditer(line):
                names.add(m.group(1))
            if RE_JSON_CODEC.search(line):
                names.add("json.encode/decode")
            for name in names:
                findings.append(Finding(
                    pf.rel_path, ln, "P005", "warn",
                    f"{name}(...) is expensive and runs every tick of this per-frame loop",
                    "call it less often (cache the result, move it outside the loop, or raise the Wait interval)",
                ))
    return findings


def check_p006(pf) -> list:
    findings = []
    for i, line in enumerate(pf.clean_lines, start=1):
        m = RE_TRIGGER_CLIENT_BCAST.search(line)
        if not m:
            continue
        loop = direct_enclosing_loop(pf, i)
        timer = direct_enclosing_timer(pf, i)
        if loop is not None or timer is not None:
            ctx = "loop" if loop is not None else "timer"
            findings.append(Finding(
                pf.rel_path, i, "P006", "warn",
                f"{m.group(1)}(..., -1, ...) broadcasts to every client from inside a {ctx} -- broadcast storm risk",
                "broadcast once (e.g. on state change) instead of repeatedly from a loop/timer, or target specific players",
            ))
    return findings


def check_p007(pf) -> list:
    findings = []
    wait_groups = _group_by_direct_loop(pf, _wait_like_calls(pf))
    low_wait_loops = {
        idx for idx, calls in wait_groups.items()
        if any((_int_literal(a) is not None and 0 <= _int_literal(a) <= 15) for _, a in calls)
    }
    groups: dict = {}
    for i, line in enumerate(pf.clean_lines, start=1):
        if not RE_PLAYER_PED_ID.search(line):
            continue
        loop = direct_enclosing_loop(pf, i)
        if loop is None or loop.index not in low_wait_loops:
            continue  # only flag inside genuinely per-frame loops
        groups.setdefault(loop.index, []).append(i)
    for idx, lines in groups.items():
        if len(lines) < 2:
            continue
        frame = pf.frames[idx]
        findings.append(Finding(
            pf.rel_path, frame.start_line, "P007", "info",
            f"PlayerPedId() is called {len(lines)} times in this per-frame loop (lines {', '.join(map(str, lines))})",
            "cache it once per iteration: local ped = PlayerPedId()",
        ))
    return findings


def run(pf) -> list:
    findings = []
    findings += check_p001(pf)
    findings += check_p002_p003(pf)
    findings += check_p004(pf)
    findings += check_p005(pf)
    findings += check_p006(pf)
    findings += check_p007(pf)
    return [f for f in findings if not pf.is_suppressed(f.line, f.rule)]
