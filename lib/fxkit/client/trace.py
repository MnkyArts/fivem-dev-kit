"""Analyzes a `profiler saveJSON` Chrome-trace-event JSON capture. Used by
`fxclient profile`. Format derived from
fivem/code/components/citizen-scripting-core/src/Profiler.cpp's
ConvertToJSON (see docs/fxclient.md for the full citation and
tests/fixtures/profile-sample.json for a format-faithful synthetic example).

Trace shape that matters for analysis: resource-tick and profiler-scope
events all share one tid (TRACE_THREAD_BROWSER); frame-boundary markers
(BeginFrame) use a different tid (TRACE_THREAD_MAIN). Resources are NOT
distinguished by tid -- only by event name: an ENTER_RESOURCE/EXIT_RESOURCE
pair is named "<cause> (<resourceName>)" (Profiler.cpp ConvertToJSON, the
ENTER_RESOURCE/EXIT_RESOURCE cases), while ENTER_SCOPE/EXIT_SCOPE pairs
(native calls, profiler:EnterScope annotations, ...) are named with the bare
scope string and are attributed to whichever resource span most closely
encloses them on that tid's stack.
"""
from __future__ import annotations

import math
import re
from typing import Any, Optional

_RESOURCE_NAME_RE = re.compile(r"^(?P<cause>.*) \((?P<resource>.+)\)$")


def _frame_boundaries(events: list) -> list:
    """Sorted ts of every BeginFrame instant marker -- one per recorded frame."""
    return sorted(e["ts"] for e in events if e.get("ph") == "I" and e.get("name") == "BeginFrame")


def _spans(events: list) -> tuple[list, list]:
    """Pairs every B/E event per-tid into spans, computing each span's self
    time (its own duration minus its direct children's durations -- the
    standard flame-graph definition). Returns (resource_spans, scope_spans).
    """
    ordered = sorted(
        (e for e in events if e.get("ph") in ("B", "E")),
        key=lambda e: (e.get("ts", 0), 0 if e.get("ph") == "B" else 1),
    )

    stacks: dict[Any, list] = {}
    resource_spans: list = []
    scope_spans: list = []

    for ev in ordered:
        tid = ev.get("tid")
        stack = stacks.setdefault(tid, [])
        name = ev.get("name", "")
        if ev.get("ph") == "B":
            m = _RESOURCE_NAME_RE.match(name)
            if m:
                resource = m.group("resource")
            elif stack:
                resource = stack[-1]["resource"]
            else:
                resource = None
            stack.append({
                "name": name, "ts": ev.get("ts", 0), "resource": resource,
                "is_resource": bool(m), "child_us": 0,
            })
        else:  # 'E'
            if not stack:
                continue  # unmatched close -- ignore rather than crash on odd input
            frame = stack.pop()
            duration = ev.get("ts", 0) - frame["ts"]
            self_us = duration - frame["child_us"]
            if stack:
                stack[-1]["child_us"] += duration
            span = {
                "name": frame["name"], "resource": frame["resource"],
                "duration_us": duration, "self_us": self_us,
            }
            (resource_spans if frame["is_resource"] else scope_spans).append(span)

    return resource_spans, scope_spans


def _percentile95(sorted_values: list) -> float:
    """Nearest-rank p95: 0-based index = ceil(0.95 * n) - 1, clamped to
    [0, n-1]. `sorted_values` must already be sorted ascending."""
    n = len(sorted_values)
    if n == 0:
        return 0.0
    idx = max(0, min(n - 1, math.ceil(0.95 * n) - 1))
    return sorted_values[idx]


def _resource_stats(resource_spans: list, frame_count: int, frame_period_us: Optional[float]) -> dict:
    by_resource: dict[str, list] = {}
    for span in resource_spans:
        name = span["resource"] or "(unknown)"
        by_resource.setdefault(name, []).append(span["duration_us"])

    stats = {}
    for name, durs in by_resource.items():
        durs_sorted = sorted(durs)
        total_us = sum(durs)
        avg_us = total_us / len(durs)
        stats[name] = {
            "frames": len(durs),
            "total_ms": total_us / 1000.0,
            "avg_ms": avg_us / 1000.0,
            "p95_ms": _percentile95(durs_sorted) / 1000.0,
            "max_ms": durs_sorted[-1] / 1000.0,
            "share_pct": (avg_us / frame_period_us * 100.0) if frame_period_us else None,
        }
    return stats


def _frame_period_us(boundaries: list) -> Optional[float]:
    if len(boundaries) < 2:
        return None
    deltas = [b - a for a, b in zip(boundaries, boundaries[1:])]
    return sum(deltas) / len(deltas)


def _top_scopes(scope_spans: list, focus_resource: Optional[str], limit: int = 10) -> list:
    by_name: dict[str, dict] = {}
    for span in scope_spans:
        if focus_resource is not None and span["resource"] != focus_resource:
            continue
        entry = by_name.setdefault(
            span["name"], {"name": span["name"], "resource": span["resource"], "calls": 0, "self_ms": 0.0}
        )
        entry["calls"] += 1
        entry["self_ms"] += span["self_us"] / 1000.0
    return sorted(by_name.values(), key=lambda e: e["self_ms"], reverse=True)[:limit]


def analyze(trace: dict, focus_resource: Optional[str] = None) -> dict:
    """trace: the parsed `{"traceEvents": [...]}` object (as saved by
    `profiler saveJSON`). Returns:
    {frame_count, frame_period_ms,
     resources: {name: {frames, total_ms, avg_ms, p95_ms, max_ms, share_pct}},
     top_scopes: [{name, resource, calls, self_ms}, ...]} (top_scopes is
    filtered to focus_resource's own scopes when given, else all resources').
    """
    events = trace.get("traceEvents", []) if isinstance(trace, dict) else []
    boundaries = _frame_boundaries(events)
    period_us = _frame_period_us(boundaries)
    resource_spans, scope_spans = _spans(events)

    return {
        "frame_count": len(boundaries),
        "frame_period_ms": (period_us / 1000.0) if period_us else None,
        "resources": _resource_stats(resource_spans, len(boundaries), period_us),
        "top_scopes": _top_scopes(scope_spans, focus_resource),
    }


# ---------------------------------------------------------------------
# CLI-facing formatting
# ---------------------------------------------------------------------

IDLE_TARGET_MS = 0.02
ACTIVE_TARGET_MS = 0.10


def verdict_for(stats: Optional[dict]) -> str:
    if not stats:
        return "no data for this resource in the capture -- it may not have ticked while recording"
    avg = stats["avg_ms"]
    if avg <= IDLE_TARGET_MS:
        return f"OK -- {avg:.4f} ms/frame avg is within the idle target (0.00-{IDLE_TARGET_MS:.2f} ms)"
    if avg < ACTIVE_TARGET_MS:
        return f"OK -- {avg:.4f} ms/frame avg is within the active target (< {ACTIVE_TARGET_MS:.2f} ms)"
    return f"OVER BUDGET -- {avg:.4f} ms/frame avg exceeds the active target (< {ACTIVE_TARGET_MS:.2f} ms)"


def format_table(result: dict, focus_resource: Optional[str] = None) -> str:
    lines = []
    frame_period = result["frame_period_ms"]
    if frame_period:
        period_text = f"{frame_period:.3f} ms/frame (~{1000.0 / frame_period:.0f} fps)"
    else:
        period_text = "n/a (fewer than 2 frames captured)"
    lines.append(f"frames captured: {result['frame_count']}   avg frame period: {period_text}")
    lines.append("")

    header = f"{'resource':<28}{'frames':>7}{'total ms':>10}{'avg ms':>9}{'p95 ms':>9}{'max ms':>9}{'share':>8}"
    lines.append(header)
    lines.append("-" * len(header))
    for name, s in sorted(result["resources"].items(), key=lambda kv: kv[1]["total_ms"], reverse=True):
        share = f"{s['share_pct']:.2f}%" if s.get("share_pct") is not None else "n/a"
        marker = "  *" if name == focus_resource else ""
        lines.append(
            f"{name:<28}{s['frames']:>7}{s['total_ms']:>10.3f}{s['avg_ms']:>9.4f}"
            f"{s['p95_ms']:>9.4f}{s['max_ms']:>9.4f}{share:>8}{marker}"
        )

    if result["top_scopes"]:
        lines.append("")
        label = f"top scopes for {focus_resource}" if focus_resource else "top scopes (all resources)"
        lines.append(f"{label}, by self time:")
        for i, sc in enumerate(result["top_scopes"], 1):
            lines.append(f"  {i:>2}. {sc['name']:<32} self {sc['self_ms']:>8.4f} ms  ({sc['calls']} calls)")

    if focus_resource:
        lines.append("")
        lines.append(f"verdict ({focus_resource}): {verdict_for(result['resources'].get(focus_resource))}")

    return "\n".join(lines)
