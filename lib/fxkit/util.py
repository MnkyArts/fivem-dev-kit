"""Small stdlib-only helpers shared across fxkit modules."""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def joaat(name: str) -> int:
    """Jenkins one-at-a-time hash, lowercased first -- what Cfx.re calls
    'joaat'. Verified against GET_ENTITY_COORDS -> 0x1647F1CB and others.
    """
    h = 0
    for c in name.lower().encode("utf-8"):
        h = (h + c) & 0xFFFFFFFF
        h = (h + ((h << 10) & 0xFFFFFFFF)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + ((h << 3) & 0xFFFFFFFF)) & 0xFFFFFFFF
    h ^= h >> 11
    h = (h + ((h << 15) & 0xFFFFFFFF)) & 0xFFFFFFFF
    return h & 0xFFFFFFFF


def norm_hash(s: str, width: int = 0) -> str:
    """Normalize a hex hash string to '0xUPPERCASE', optionally zero-padded
    to `width` hex digits (8 for 32-bit CFX/joaat hashes, 16 for 64-bit GTA
    hashes). Accepts with/without '0x' prefix, any case.
    """
    s = s.strip()
    if s.lower().startswith("0x"):
        s = s[2:]
    v = int(s, 16)
    if width:
        return f"0x{v:0{width}X}"
    return f"0x{v:X}"


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def cache_is_fresh(path: Path, max_age_days: int) -> bool:
    if not path.exists():
        return False
    age_s = time.time() - path.stat().st_mtime
    return age_s < max_age_days * 86400


def fetch_json(
    url: str,
    dest: Path,
    *,
    force: bool = False,
    no_download: bool = False,
    max_age_days: int = 7,
    timeout: int = 60,
) -> tuple[Any | None, str | None]:
    """Fetch JSON from `url`, caching atomically at `dest`.

    Returns (data, warning). `data` is None only when nothing usable (no
    network data, no cache) could be obtained; `warning` is a human string to
    surface to the user when we fell back to cache or failed outright.
    """
    if no_download:
        if dest.exists():
            try:
                return json.loads(dest.read_text(encoding="utf-8")), None
            except (OSError, ValueError) as e:
                return None, f"--no-download set and cache at {dest} is unreadable ({e})"
        return None, f"--no-download set and no cache at {dest}"

    if not force and cache_is_fresh(dest, max_age_days):
        try:
            return json.loads(dest.read_text(encoding="utf-8")), None
        except (OSError, ValueError):
            pass  # fall through and try to (re)download

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "fxref/1.0 (+fivem-dev-kit)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        atomic_write_bytes(dest, raw)
        return data, None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        if dest.exists():
            try:
                return json.loads(dest.read_text(encoding="utf-8")), f"download failed ({e}); using cached {dest.name}"
            except (OSError, ValueError) as e2:
                return None, f"download failed ({e}) and cache unreadable ({e2})"
        return None, f"download failed ({e}) and no cache available at {dest}"


_WS_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"(.*?[.!?])(\s|$)")


def first_sentence(text: str | None, max_len: int = 110) -> str:
    if not text:
        return ""
    flat = _WS_RE.sub(" ", text).strip()
    m = _SENTENCE_RE.search(flat)
    s = m.group(1) if m else flat
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    return s


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class Timer:
    """`with Timer() as t: ...` then `t.seconds`."""

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        self.seconds = 0.0
        return self

    def __exit__(self, *exc: Any) -> None:
        self.seconds = time.perf_counter() - self._start
