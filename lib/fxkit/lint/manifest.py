"""fxmanifest.lua parsing for fxlint.

Not a real Lua interpreter -- fxmanifest.lua is a semi-declarative file (see
resource_init.lua in the FiveM source: any bare identifier followed by a
string/table argument sets a metadata key, and a trailing 's' on the key is
stripped so `client_scripts {...}` and `client_script '...'` both populate
the same `client_script` metadata list). We just need the handful of keys
that matter for linting, so a couple of careful regexes are enough and match
the spirit of "heuristic analysis" the whole tool is built on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

MANIFEST_NAMES = ("fxmanifest.lua", "__resource.lua")

_STRING = r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""


def _key_pattern(key: str) -> re.Pattern:
    # matches `key 'x'`, `key("x")`, `key { ... }`, `key({ ... })`
    return re.compile(
        r"\b" + re.escape(key) + r"\b\s*\(?\s*(" + _STRING + r"|\{.*?\})",
        re.DOTALL,
    )


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] in "'\"" and s[-1] == s[0]:
        s = s[1:-1]
    return s.replace("\\'", "'").replace('\\"', '"')


def _extract_strings(block: str) -> list:
    if block.startswith("{"):
        return [
            _strip_quotes(m.group(0))
            for m in re.finditer(_STRING, block)
        ]
    return [_strip_quotes(block)]


def _collect(text: str, base_key: str) -> list:
    """Collect all values for `base_key`/`base_key + 's'`, in source order."""
    hits = []
    for key in (base_key, base_key + "s"):
        for m in _key_pattern(key).finditer(text):
            hits.append((m.start(), m.group(1)))
    hits.sort(key=lambda t: t[0])
    out = []
    for _, block in hits:
        out.extend(_extract_strings(block))
    return out


def _collect_scalar(text: str, base_key: str) -> Optional[str]:
    vals = _collect(text, base_key)
    return vals[0] if vals else None


def _strip_comments(text: str) -> str:
    # good enough for a manifest file: drop `--[[ ... ]]` and `-- ...` (long
    # strings in manifests are effectively never used for these keys)
    text = re.sub(r"--\[(=*)\[.*?\]\1\]", "", text, flags=re.DOTALL)
    text = re.sub(r"--[^\n]*", "", text)
    return text


@dataclass
class ManifestInfo:
    path: Optional[Path]
    text: str = ""
    fx_version: Optional[str] = None
    games: list = field(default_factory=list)
    lua54: Optional[str] = None
    use_experimental_fxv2_oal: Optional[str] = None
    client_scripts: list = field(default_factory=list)
    server_scripts: list = field(default_factory=list)
    shared_scripts: list = field(default_factory=list)
    dependencies: list = field(default_factory=list)
    exports: list = field(default_factory=list)
    server_exports: list = field(default_factory=list)
    ui_page: Optional[str] = None
    files: list = field(default_factory=list)
    # `core_ui '<dir>'` -- plain metadata, not an FXServer key: core reads it with
    # GetResourceMetadata to find a resource's own frontend (core DESIGN section 38.4).
    core_ui: Optional[str] = None

    @property
    def uses_ox_lib(self) -> bool:
        if any("ox_lib" in d for d in self.dependencies):
            return True
        return any("ox_lib" in s for s in self.shared_scripts)


def find_manifest(resource_dir: Path) -> Optional[Path]:
    for name in MANIFEST_NAMES:
        p = resource_dir / name
        if p.exists():
            return p
    return None


def parse_manifest(path: Path) -> ManifestInfo:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ManifestInfo(path=path)
    text = _strip_comments(raw)
    info = ManifestInfo(
        path=path,
        text=raw,
        fx_version=_collect_scalar(text, "fx_version"),
        games=_collect(text, "game"),
        lua54=_collect_scalar(text, "lua54"),
        use_experimental_fxv2_oal=_collect_scalar(text, "use_experimental_fxv2_oal"),
        client_scripts=_collect(text, "client_script"),
        server_scripts=_collect(text, "server_script"),
        shared_scripts=_collect(text, "shared_script"),
        dependencies=_collect(text, "dependency"),
        exports=_collect(text, "export"),
        server_exports=_collect(text, "server_export"),
        ui_page=_collect_scalar(text, "ui_page"),
        files=_collect(text, "file"),
        core_ui=_collect_scalar(text, "core_ui"),
    )
    return info


# ---------------------------------------------------------------------------
# Side resolution
# ---------------------------------------------------------------------------

def _expand_glob(resource_dir: Path, pattern: str) -> list:
    if not pattern or pattern.startswith("@") or pattern.startswith("http://") or pattern.startswith("https://"):
        return []  # dependency-resource script or remote URL, not a local file
    if "*" not in pattern and "?" not in pattern:
        p = (resource_dir / pattern)
        return [p] if p.is_file() else []
    pat = pattern
    m = re.match(r"^\*\*(\.[A-Za-z0-9]+)$", pat)
    if m:
        pat = "**/*" + m.group(1)
    try:
        return [p for p in resource_dir.glob(pat) if p.is_file()]
    except (ValueError, OSError):
        return []


def path_side_heuristic(rel_path: str) -> Optional[str]:
    rel = rel_path.replace("\\", "/")
    parts = [p for p in rel.split("/") if p]
    if not parts:
        return None
    top = parts[0].lower()
    if top in ("client",):
        return "client"
    if top in ("server",):
        return "server"
    if top in ("shared", "sh", "common"):
        return "shared"
    name = parts[-1].lower()
    stem = name.rsplit(".", 1)[0] if "." in name else name
    if name.startswith("cl_"):
        return "client"
    if name.startswith("sv_"):
        return "server"
    if name.startswith("sh_"):
        return "shared"
    if stem.endswith("_client"):
        return "client"
    if stem.endswith("_server"):
        return "server"
    if stem.endswith("_shared"):
        return "shared"
    low = rel.lower()
    if "client" in low:
        return "client"
    if "server" in low:
        return "server"
    if "shared" in low:
        return "shared"
    return None


def resolve_sides(resource_dir: Path, manifest: ManifestInfo, files: list) -> dict:
    """Map each file (Path, must be under resource_dir) to 'client'/'server'/'shared'/None."""
    sides: dict = {}
    if manifest.path is not None:
        for pattern in manifest.shared_scripts:
            for p in _expand_glob(resource_dir, pattern):
                sides[p] = "shared"
        for pattern in manifest.client_scripts:
            for p in _expand_glob(resource_dir, pattern):
                sides[p] = "client"
        for pattern in manifest.server_scripts:
            for p in _expand_glob(resource_dir, pattern):
                sides[p] = "server"
    result = {}
    for f in files:
        if f in sides:
            result[f] = sides[f]
        else:
            try:
                rel = f.relative_to(resource_dir).as_posix()
            except ValueError:
                rel = f.name
            result[f] = path_side_heuristic(rel)
    return result
