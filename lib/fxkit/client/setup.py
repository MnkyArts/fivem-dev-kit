"""`fxclient setup` logic: reports what's in place and what isn't, and
prints exact commands/server.cfg lines for the rest. Deliberately never
touches server.cfg or creates the deploy symlinks itself -- see
docs/fxclient.md "setup" for why (this resource's own spec says to print the
`fxserver deploy` commands rather than run them, precisely so a human
reviews every change to server.cfg before it happens).
"""
from __future__ import annotations

import socket
import subprocess
from pathlib import Path
from typing import Optional

from fxkit import config
from . import resource as resource_mod


def detect_lan_ip() -> Optional[str]:
    """Best-effort LAN IP of this machine -- what the gaming PC should use
    as the host part of -Server. Tries `ip route get` first (Linux, sends no
    packets -- it's a routing-table lookup), then a UDP "connect" (also
    sends nothing; it only makes the kernel pick a source address for that
    route)."""
    try:
        proc = subprocess.run(
            ["ip", "route", "get", "1.1.1.1"], capture_output=True, text=True, timeout=3,
        )
        if proc.returncode == 0:
            tokens = proc.stdout.split()
            for tok, nxt in zip(tokens, tokens[1:]):
                if tok == "src":
                    return nxt
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def server_port() -> Optional[int]:
    try:
        from fxkit import server as fxserver_lib
    except ImportError:
        return None
    try:
        paths = config.server_paths()
    except (KeyError, FileNotFoundError):
        return None
    cfg_path = Path(paths["server_cfg"])
    if not cfg_path.exists():
        return None
    return fxserver_lib.find_endpoint_port(cfg_path)


def fxserver_bin_exists() -> bool:
    return (config.kit_root() / "bin" / "fxserver").exists()


def plan() -> dict:
    """Everything `fxclient setup` reports, as plain data -- bin/fxclient
    does the printing, so this is also easy to unit test."""
    lan_ip = detect_lan_ip()
    port = server_port() or 30120
    server_addr = f"{lan_ip or '<LAN-IP>'}:{port}"

    return {
        "screenshot_basic_present": resource_mod.screenshot_basic_present(),
        "screenshot_basic_dir": str(resource_mod.screenshot_basic_dir()),
        "devtools_kit_dir": str(resource_mod.kit_resource_dir()),
        "devtools_deployed": resource_mod.is_deployed(),
        "fxserver_bin_exists": fxserver_bin_exists(),
        "lan_ip": lan_ip,
        "server_port": port,
        "server_addr": server_addr,
        "deploy_commands": [
            f"fxserver deploy {resource_mod.screenshot_basic_dir()}",
            f"fxserver deploy {resource_mod.kit_resource_dir()}",
        ],
        "server_cfg_lines": [
            "ensure screenshot-basic",
            "ensure fivem-devtools",
            "add_ace resource.fivem-devtools command allow",
            "add_ace group.admin fivem-devtools.use allow",
        ],
        "agent_fetch_command": (
            f"irm http://{server_addr}/fivem-devtools/agent -OutFile $env:TEMP\\fxclient-agent.ps1"
        ),
        "agent_run_command": (
            f"powershell -ExecutionPolicy Bypass -File $env:TEMP\\fxclient-agent.ps1 -Server {server_addr}"
        ),
    }
