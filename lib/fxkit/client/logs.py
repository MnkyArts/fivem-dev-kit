"""out/client.log reading + filtering for `fxclient logs`.

out/client.log is written by server/main.lua's handleClientLogUpload,
appending each upload from fxclient-agent.ps1 and truncating to
Config.MaxLogBytes -- see docs/fxclient.md. Lines keep the client's own
format: `[tick] [processName] threadName/ message` (see
fivem/code/client/launcher/Console.Logging.cpp).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

# Matches $KIT/DESIGN.md's fxserver ERROR_KEYWORDS list style, but using the
# exact word list from this task's spec for the client log specifically.
ERROR_KEYWORDS = (
    "SCRIPT ERROR", "error", "warning", "attempt to", "nil value",
    "stack traceback", "Failed", "Error loading",
)

# The client's production-build console whitelist can silently block
# `profiler`/`resmon`/`netgraph` etc. Two different messages can show up in
# CitizenFX_log depending on which principal issued the command -- see
# docs/fxclient.md "Troubleshooting" for the exact source citations
# (ProductionWhitelist.h, ConsoleHostGui.cpp IsNonProduction/AccessDeniedEvent,
# Console.Commands.cpp's generic access-denied print).
PRODUCTION_GATE_MARKERS = (
    "is disabled in production mode",
    "Access denied for command",
)


def read_log(path: Path) -> list:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.splitlines()


def filter_lines(
    lines: list,
    tail: Optional[int] = None,
    errors_only: bool = False,
    resource: Optional[str] = None,
) -> list:
    out = lines
    if resource:
        # The client log has no fxserver-log-style "[script:name]" tag --
        # this is a best-effort substring match (script error tracebacks and
        # `@resource/path` references commonly include the resource name
        # somewhere on the line). See docs/fxclient.md "limitations".
        out = [l for l in out if resource in l]
    if errors_only:
        out = [l for l in out if any(k in l for k in ERROR_KEYWORDS)]
    if tail is not None and tail > 0:
        out = out[-tail:]
    return out


def find_production_gate_warning(lines: list) -> Optional[str]:
    """Returns the first line matching PRODUCTION_GATE_MARKERS, or None.
    Used by `fxclient info`/`status`/`profile` to proactively surface a
    likely `+set moo 31337` fix instead of leaving the developer to notice a
    silently-blocked `profiler`/`resmon` command on their own."""
    for line in lines:
        if any(marker in line for marker in PRODUCTION_GATE_MARKERS):
            return line
    return None
