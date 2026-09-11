"""Command queue: enqueue a command for the fivem-devtools FiveM resource to
pick up, and wait for its result. bin/fxclient and the resource share the
same files on disk -- both run on this Linux box (see docs/fxclient.md) --
so there is no network call in this module at all; it is plain file I/O.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from fxkit import util

# Keep queue/commands.json small so the server's LoadResourceFile poll stays
# cheap every PollIntervalMs (see $KIT/DESIGN.md). Only ever trims commands
# old enough that the server has certainly already processed them -- this
# bound wasn't spelled out in the original spec text; without it the file
# would grow without limit over a long dev session. See docs/fxclient.md.
MAX_KEPT_COMMANDS = 200


class TimeoutWaitingForResult(Exception):
    def __init__(self, command_id: int, message: str):
        super().__init__(message)
        self.command_id = command_id


def read_queue(queue_path: Path) -> dict:
    if not queue_path.exists():
        return {"next_id": 1, "commands": []}
    try:
        data = json.loads(queue_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"next_id": 1, "commands": []}
    if not isinstance(data, dict):
        return {"next_id": 1, "commands": []}
    next_id = data.get("next_id")
    if not isinstance(next_id, int) or next_id < 1:
        next_id = 1
    commands = data.get("commands")
    if not isinstance(commands, list):
        commands = []
    return {"next_id": next_id, "commands": commands}


def _write_queue(queue_path: Path, data: dict) -> None:
    text = json.dumps(data, indent=1)
    util.atomic_write_bytes(queue_path, text.encode("utf-8"))


def enqueue(queue_path: Path, cmd: str, args: Optional[dict] = None) -> int:
    """Appends {id, cmd, args, ts} to queue_path, returns the new id."""
    data = read_queue(queue_path)
    next_id = data["next_id"]

    entry = {"id": next_id, "cmd": cmd, "args": args or {}, "ts": int(time.time())}
    commands = data["commands"]
    commands.append(entry)
    if len(commands) > MAX_KEPT_COMMANDS:
        commands = commands[-MAX_KEPT_COMMANDS:]

    _write_queue(queue_path, {"next_id": next_id + 1, "commands": commands})
    return next_id


def read_result(out_dir: Path, command_id: int) -> Optional[dict]:
    p = out_dir / f"{command_id}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def wait_for_result(
    out_dir: Path,
    command_id: int,
    timeout: float,
    poll_interval: float = 0.5,
    sleep: Callable[[float], Any] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> dict:
    """Polls out/<id>.json every poll_interval seconds until its status is
    'ok' or 'error' (not 'pending', not missing), or timeout seconds have
    elapsed. Raises TimeoutWaitingForResult on timeout. `sleep`/`now` are
    injectable so tests never actually sleep."""
    deadline = now() + timeout
    last: Optional[dict] = None
    while True:
        result = read_result(out_dir, command_id)
        if result is not None:
            last = result
            if result.get("status") in ("ok", "error"):
                return result
        if now() >= deadline:
            break
        sleep(poll_interval)

    if last is not None:
        raise TimeoutWaitingForResult(
            command_id,
            f"command {command_id} is still '{last.get('status')}' after {timeout:.0f}s -- "
            "is the fivem-devtools resource deployed and running (`fxclient status`)?",
        )
    raise TimeoutWaitingForResult(
        command_id,
        f"no result for command {command_id} after {timeout:.0f}s "
        f"({out_dir / (str(command_id) + '.json')} never appeared) -- is the fivem-devtools "
        "resource deployed, ensured, and is a dev player online? try `fxclient status`.",
    )
