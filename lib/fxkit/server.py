"""Core logic for fxserver: deploy/undeploy/list/status/logs/rcon.

Kept separate from bin/fxserver so tests can call these functions directly
against a fake server tree (never the real one). Every function that touches
server.cfg or the log file takes an explicit `paths` dict shaped like
fxkit.config.server_paths(): {root, data_dir, local_resources, server_cfg, log_file}.

Nothing in here ever prints server.cfg's contents -- callers only get back
small structured reports (which lines were touched, not the whole file).
"""
from __future__ import annotations

import datetime
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# deploy / undeploy / list
# ---------------------------------------------------------------------------

class DeployError(Exception):
    pass


_ENSURE_RE = re.compile(r"""^\s*(?:ensure|start)\s+["']?([^"'\s]+)["']?\s*(?:#.*)?$""")


def _ensure_in_cfg(cfg_path: Path, name: str) -> tuple:
    """Insert `ensure <name>` after the last ensure/start line, unless a line
    for this exact name is already present. Writes atomically; makes
    server.cfg.fxkit.bak once (never overwritten again). Returns
    (added: bool, backup_created: bool)."""
    text = cfg_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    last_ensure_idx = None
    for i, line in enumerate(lines):
        m = _ENSURE_RE.match(line)
        if m:
            last_ensure_idx = i
            if m.group(1) == name:
                return False, False  # already present, nothing to do

    bak_path = cfg_path.with_name(cfg_path.name + ".fxkit.bak")
    backup_created = False
    if not bak_path.exists():
        shutil.copy2(cfg_path, bak_path)
        backup_created = True

    insert_at = (last_ensure_idx + 1) if last_ensure_idx is not None else len(lines)
    needs_leading_newline = insert_at > 0 and lines and not lines[insert_at - 1].endswith("\n")
    new_line = ("\n" if needs_leading_newline else "") + f"ensure {name}\n"
    lines.insert(insert_at, new_line)

    tmp_path = cfg_path.with_name(cfg_path.name + ".fxkit.tmp")
    tmp_path.write_text("".join(lines), encoding="utf-8")
    os.replace(tmp_path, cfg_path)  # atomic within the same directory/filesystem

    return True, backup_created


def deploy(resource_dir: Path, paths: dict, ensure: bool = True) -> dict:
    """Symlink resource_dir into paths['local_resources']/<name>, replacing an
    existing symlink that points elsewhere (never a real directory), and
    (unless ensure=False) add `ensure <name>` to server.cfg."""
    resource_dir = Path(resource_dir).resolve()
    if not resource_dir.is_dir():
        raise DeployError(f"not a directory: {resource_dir}")
    if not (resource_dir / "fxmanifest.lua").exists() and not (resource_dir / "__resource.lua").exists():
        raise DeployError(f"no fxmanifest.lua in {resource_dir} -- refusing to deploy a non-resource directory")

    name = resource_dir.name
    local_resources = Path(paths["local_resources"])
    local_resources.mkdir(parents=True, exist_ok=True)
    link_path = local_resources / name

    report = {
        "name": name, "resource_dir": str(resource_dir), "link": str(link_path),
        "linked": False, "relinked": False, "ensure_added": False, "backup_created": False,
    }

    if link_path.is_symlink():
        current_target = Path(os.readlink(link_path))
        if not current_target.is_absolute():
            current_target = (link_path.parent / current_target).resolve()
        if current_target != resource_dir:
            link_path.unlink()
            link_path.symlink_to(resource_dir, target_is_directory=True)
            report["relinked"] = True
    elif link_path.exists():
        raise DeployError(f"{link_path} exists and is not a symlink -- refusing to touch a real directory/file")
    else:
        link_path.symlink_to(resource_dir, target_is_directory=True)
        report["linked"] = True

    if ensure:
        added, backed_up = _ensure_in_cfg(Path(paths["server_cfg"]), name)
        report["ensure_added"] = added
        report["backup_created"] = backed_up

    return report


def undeploy(name: str, paths: dict) -> dict:
    """Remove the symlink for `name` from local_resources. Never touches
    server.cfg (the `ensure` line is left for the human to remove -- deleting
    it automatically risks silently orphaning an intentional entry)."""
    local_resources = Path(paths["local_resources"])
    link_path = local_resources / name
    report = {"name": name, "removed": False}
    if link_path.is_symlink():
        link_path.unlink()
        report["removed"] = True
    elif link_path.exists():
        raise DeployError(f"{link_path} exists and is not a symlink -- refusing to delete a real directory")
    return report


def list_deployed(paths: dict) -> list:
    local_resources = Path(paths["local_resources"])
    if not local_resources.is_dir():
        return []
    out = []
    for p in sorted(local_resources.iterdir()):
        if p.name.startswith("."):
            continue
        if p.is_symlink():
            try:
                target = str(Path(os.readlink(p)))
            except OSError:
                target = None
            out.append({"name": p.name, "type": "symlink", "target": target, "broken": not p.exists()})
        elif p.is_dir():
            out.append({"name": p.name, "type": "dir", "target": None, "broken": False})
    return out


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def is_fxserver_running() -> Optional[int]:
    """PID of a running FXServer process, or None. pgrep first, ps as a fallback."""
    try:
        proc = subprocess.run(["pgrep", "-f", "FXServer"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            for tok in proc.stdout.split():
                if tok.isdigit():
                    return int(tok)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True, timeout=5)
        for line in proc.stdout.splitlines():
            if "FXServer" in line:
                parts = line.strip().split(None, 1)
                if parts and parts[0].isdigit():
                    return int(parts[0])
    except (OSError, subprocess.SubprocessError):
        pass
    return None


_ENDPOINT_RE = re.compile(r"""^\s*endpoint_add_(?:tcp|udp)\s+["']?([^"'\s]+)["']?""")


def find_endpoint_port(cfg_path: Path) -> Optional[int]:
    try:
        text = cfg_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        m = _ENDPOINT_RE.match(line)
        if not m:
            continue
        addr = m.group(1)
        port_str = addr.rsplit(":", 1)[-1] if ":" in addr else addr
        try:
            return int(port_str)
        except ValueError:
            continue
    return None


def tcp_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def txadmin_present(paths: dict) -> bool:
    """txAdmin runs as the 'monitor' resource; look for its startup line in the
    log (see fxserver.log: '[script:monitor] [txAdmin] ... Ready.')."""
    log_path = Path(paths.get("log_file", ""))
    if not log_path.exists():
        return False
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "script:monitor" in text or "txAdmin" in text


def status(paths: dict) -> dict:
    pid = is_fxserver_running()
    cfg_path = Path(paths["server_cfg"])
    port = find_endpoint_port(cfg_path) if cfg_path.exists() else None
    reachable = tcp_port_open("127.0.0.1", port) if port else False
    return {
        "running": pid is not None,
        "pid": pid,
        "port": port,
        "port_reachable": reachable,
        "txadmin": txadmin_present(paths),
    }


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_BANNER_CHARS = "║╔╗╚╝═╠╣"

# Priority order: real script problems first, generic "error"/"warning" last
# (those two alone would also match the Cfx server-list heartbeat noise below,
# which is why that noise is stripped out *before* this list is applied).
ERROR_KEYWORDS = (
    "SCRIPT ERROR", "[script:", "stack traceback", "attempt to", "nil value",
    "not safe for net", "Couldn't find resource", "Failed to", "error", "warning",
)

# Cfx's periodic server-list heartbeat: harmless connectivity noise (the
# server can't reach the master server list), not a script/resource problem.
# Excluded from --errors by default; --all-errors puts it back.
_NOISE_PATTERNS = (
    re.compile(r"Server list query returned an error"),
    re.compile(r"server request failed for endpoint https?://[^\s]+:\d+/(?:info|dynamic|players)\.json"),
)

_TIMESTAMP_RE = re.compile(r"^\[?(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}|\d{2}:\d{2}:\d{2})\]?")


def strip_ansi(line: str) -> str:
    return _ANSI_RE.sub("", line)


def is_banner_line(line: str) -> bool:
    return any(ch in line for ch in _BANNER_CHARS)


def is_noise_line(line: str) -> bool:
    return any(p.search(line) for p in _NOISE_PATTERNS)


def dedupe_consecutive(lines: list) -> list:
    """Collapse runs of identical consecutive lines into one, suffixed ' (xN)'."""
    out = []
    i, n = 0, len(lines)
    while i < n:
        j = i + 1
        while j < n and lines[j] == lines[i]:
            j += 1
        count = j - i
        out.append(lines[i] if count == 1 else f"{lines[i]} (x{count})")
        i = j
    return out


def _resource_pattern(name: str) -> re.Pattern:
    # fxserver.log pads the bracketed label to a fixed column width, e.g.
    # "[      script:myresource]" -- allow whitespace around the name.
    esc = re.escape(name)
    return re.compile(r"\[\s*script:\s*" + esc + r"\s*\]|\bresource\s+" + esc + r"\b")


def _parse_ts(text: str) -> Optional[float]:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%H:%M:%S"):
        try:
            dt = datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt == "%H:%M:%S":
            now = datetime.datetime.now()
            dt = dt.replace(year=now.year, month=now.month, day=now.day)
        return dt.timestamp()
    return None


def read_log_lines(log_path: Path) -> list:
    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.readlines()


def filter_logs(lines: list, tail: Optional[int] = 80, errors_only: bool = False,
                 resource: Optional[str] = None, since_min: Optional[float] = None,
                 now: Optional[float] = None, all_errors: bool = False, dedupe: bool = True) -> tuple:
    """Returns (filtered_lines, notes). Strips ANSI and drops txAdmin banner
    lines unconditionally; dedupe (default on) runs after every filter but
    --tail, which is applied last of all."""
    notes: list = []
    out = [strip_ansi(raw.rstrip("\n")) for raw in lines]
    out = [l for l in out if not is_banner_line(l)]

    if since_min is not None:
        sample = out[:500]
        has_ts = any(_TIMESTAMP_RE.match(l) for l in sample)
        if not has_ts:
            notes.append("logs: --since ignored (this log has no per-line timestamps)")
        else:
            cutoff = (now if now is not None else time.time()) - since_min * 60
            kept = []
            for l in out:
                m = _TIMESTAMP_RE.match(l)
                if not m:
                    kept.append(l)  # undated continuation line -- keep it with its neighbours
                    continue
                ts = _parse_ts(m.group(1))
                if ts is None or ts >= cutoff:
                    kept.append(l)
            out = kept

    if resource:
        pat = _resource_pattern(resource)
        out = [l for l in out if pat.search(l)]

    if errors_only:
        if not all_errors:
            out = [l for l in out if not is_noise_line(l)]
        out = [l for l in out if any(k in l for k in ERROR_KEYWORDS)]

    if dedupe:
        out = dedupe_consecutive(out)

    if tail is not None and tail > 0:
        out = out[-tail:]

    return out, notes


def read_new_lines(log_path: Path, from_pos: int) -> tuple:
    """For --follow: read whatever's been appended to log_path since from_pos.
    Returns (raw_lines, new_pos). Tolerates the file having been truncated/
    rotated (rewinds to 0 in that case)."""
    size = log_path.stat().st_size
    if from_pos > size:
        from_pos = 0
    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
        fh.seek(from_pos)
        data = fh.read()
        new_pos = fh.tell()
    return data.splitlines(keepends=True), new_pos


# ---------------------------------------------------------------------------
# rcon
# ---------------------------------------------------------------------------

# Quake-style out-of-band packet: 4 bytes of 0xFF then the payload. Verified
# against the FiveM server source -- see docs/fxserver.md for exact citations
# (WithOutOfBand.h for the framing, RconOutOfBand.h for the password/command
# split and the "print " response prefix, GameServerNet.ENet.cpp for the
# 0xFFFFFFFF response prefix).
OOB_PREFIX = b"\xff\xff\xff\xff"


class RconError(Exception):
    pass


def build_rcon_packet(password: str, command: str) -> bytes:
    return OOB_PREFIX + f"rcon {password} {command}".encode("utf-8")


def parse_rcon_response(data: bytes) -> str:
    if data.startswith(OOB_PREFIX):
        data = data[len(OOB_PREFIX):]
    text = data.decode("utf-8", errors="replace")
    if text.startswith("print "):
        text = text[len("print "):]
    elif text.startswith("print"):
        text = text[len("print"):].lstrip("\n")
    return text


def rcon(host: str, port: int, password: str, command: str, timeout: float = 3.0) -> str:
    if not password:
        raise RconError(
            "no rcon password configured. Set the FXRCON_PASSWORD environment variable (or pass --password), "
            "and make sure server.cfg has a strong `rcon_password \"...\"` line -- fxserver will not add one for you."
        )
    packet = build_rcon_packet(password, command)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(packet, (host, port))
        try:
            data, _addr = sock.recvfrom(65536)
        except socket.timeout as exc:
            raise RconError(
                f"no response from {host}:{port} within {timeout}s (server not running? wrong host/port? firewalled?)"
            ) from exc
    return parse_rcon_response(data)


def restart_resource(host: str, port: int, password: str, name: str, timeout: float = 3.0) -> str:
    return rcon(host, port, password, f"restart {name}", timeout=timeout)
