"""Resolves the fivem-devtools resource directory bin/fxclient should read
and write, and a couple of related paths (screenshot-basic's clone).

Mirrors the "symlink or dev copy" rule from $KIT/DESIGN.md and the
architecture doc: once `fxserver deploy` has symlinked the resource into the
server's local resources, that symlink and the kit's own copy point at the
exact same files on disk -- either way bin/fxclient and the FXServer
resource are reading/writing the same queue/ and out/ directories.
"""
from __future__ import annotations

from pathlib import Path

from fxkit import config

RESOURCE_NAME = "fivem-devtools"
SCREENSHOT_BASIC_NAME = "screenshot-basic"


def kit_resource_dir() -> Path:
    """The canonical, git-tracked copy inside the kit itself."""
    return config.kit_root() / "resources-dev" / RESOURCE_NAME


def _local_resources_dir() -> Path | None:
    try:
        paths = config.server_paths()
    except (KeyError, FileNotFoundError):
        return None
    return Path(paths["local_resources"])


def is_deployed() -> bool:
    """True if <server local_resources>/fivem-devtools exists (as a symlink
    or otherwise) -- i.e. `fxserver deploy` has been run for it."""
    local_resources = _local_resources_dir()
    if local_resources is None:
        return False
    return (local_resources / RESOURCE_NAME).exists()


def deployed_resource_dir() -> Path:
    """Where queue/commands.json and out/*.json actually live on disk right
    now: the deployed symlink target if deployed, else the kit's own copy
    (so `fxclient` still works -- against the kit copy only -- before the
    resource has ever been deployed; `fxclient status` reports which case
    you're in)."""
    local_resources = _local_resources_dir()
    if local_resources is not None:
        deployed = local_resources / RESOURCE_NAME
        if deployed.exists():
            return deployed
    return kit_resource_dir()


def queue_path() -> Path:
    return deployed_resource_dir() / "queue" / "commands.json"


def out_dir() -> Path:
    return deployed_resource_dir() / "out"


def result_path(command_id: int) -> Path:
    return out_dir() / f"{command_id}.json"


def agent_status_path() -> Path:
    return out_dir() / "agent-status.json"


def client_log_path() -> Path:
    return out_dir() / "client.log"


def screenshot_basic_dir() -> Path:
    workspace = config.get("project", "workspace")
    if not workspace:
        workspace = config.kit_root().parent / "resources"
    return Path(workspace).expanduser() / SCREENSHOT_BASIC_NAME


def screenshot_basic_present() -> bool:
    return (screenshot_basic_dir() / "fxmanifest.lua").exists()
