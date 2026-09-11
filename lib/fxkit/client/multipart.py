"""Pure-Python mirror of server/main.lua's parseMultipart, kept in lock-step
with it so tests/test_fxclient.py can verify the parsing *algorithm* against
known multipart bytes without needing to run FXServer's Lua runtime (the
Lua original is separately syntax-checked and unit-tested with a real Lua
interpreter -- see tests/fixtures/lua_multipart_test.lua). Not used by
bin/fxclient at runtime: the resource parses uploads in Lua, on the server.

Algorithm (see server/main.lua's parseMultipart for the authoritative
version and full comments): find the first `--boundary`, skip its trailing
CRLF, find the blank line ending that part's headers, take everything
between there and the next `\\r\\n--boundary` as the file's raw bytes.
Operates on bytes throughout -- multipart bodies are binary.
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional

_FILENAME_RE = re.compile(rb'filename="([^"]*)"')
_CONTENT_TYPE_RE = re.compile(rb"[Cc]ontent-[Tt]ype:\s*([^\r\n]+)")


class MultipartError(Exception):
    pass


class PartInfo(NamedTuple):
    filename: Optional[str]
    content_type: Optional[str]


def parse_multipart(body: bytes, boundary: bytes) -> tuple[bytes, PartInfo]:
    """Returns (data, info). Raises MultipartError on failure (mirrors
    parseMultipart's `nil, errorMessage` return in Lua)."""
    if not isinstance(body, (bytes, bytearray)) or not isinstance(boundary, (bytes, bytearray)) or not boundary:
        raise MultipartError("invalid arguments")
    body = bytes(body)
    boundary = bytes(boundary)

    delim = b"--" + boundary
    idx = body.find(delim)
    if idx == -1:
        raise MultipartError("boundary not found")

    header_start = idx + len(delim)
    if body[header_start:header_start + 2] == b"\r\n":
        header_start += 2

    header_end = body.find(b"\r\n\r\n", header_start)
    if header_end == -1:
        raise MultipartError("part headers not terminated")

    headers = body[header_start:header_end]
    data_start = header_end + 4

    next_boundary = body.find(b"\r\n--" + boundary, data_start)
    if next_boundary == -1:
        raise MultipartError("closing boundary not found")

    data = body[data_start:next_boundary]

    filename_match = _FILENAME_RE.search(headers)
    filename = filename_match.group(1).decode("utf-8", errors="replace") if filename_match else None

    ct_match = _CONTENT_TYPE_RE.search(headers)
    content_type = ct_match.group(1).decode("utf-8", errors="replace").strip() if ct_match else None

    return data, PartInfo(filename=filename, content_type=content_type)


def parse_boundary(content_type: Optional[str]) -> Optional[str]:
    """Mirrors server/main.lua's parseBoundary: 'multipart/form-data;
    boundary=X' or a quoted boundary."""
    if not content_type:
        return None
    m = re.search(r'boundary="([^"]+)"', content_type) or re.search(r"boundary=([^;\s]+)", content_type)
    return m.group(1) if m else None
