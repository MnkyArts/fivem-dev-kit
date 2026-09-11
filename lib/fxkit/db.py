"""SQLite schema + connection helpers for fxref's data/fxref.sqlite.

Design note (deliberate deviation from a literal reading of DESIGN.md's
`natives_fts (FTS5, content=natives): name_tokens, alias_tokens, ns,
param_text, description`):

SQLite's "external content" FTS5 tables require every FTS column name to be a
*real* column on the content table. `ns` and `description` already are real
columns on `natives`, but `name_tokens` / `alias_tokens` / `param_text` are
derived at build time -- so we add them to `natives` as plain stored columns
(populated once per row, never queried directly by CLI code) purely so the
FTS5 `content='natives', content_rowid='id'` linkage is literal and the
"insert with executemany, rebuild FTS once at the end" build shape
(`INSERT INTO natives_fts(natives_fts) VALUES ('rebuild')`) works exactly as
DESIGN.md's performance section describes. `docs_fts` uses the same pattern
against `docs` (title/headings/body are already real columns there, no extra
columns needed).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE natives (
    id                  INTEGER PRIMARY KEY,
    hash                TEXT NOT NULL,
    jhash               TEXT,
    name                TEXT NOT NULL,
    lua_name            TEXT NOT NULL,
    ns                  TEXT,
    ns_alt              TEXT,
    apiset              TEXT NOT NULL,
    unofficial          INTEGER NOT NULL DEFAULT 0,
    aliases             TEXT,
    params              TEXT,
    return_type         TEXT,
    results_description TEXT,
    description         TEXT,
    comment_alloc8or    TEXT,
    examples            TEXT,
    build               TEXT,
    build_gen9          TEXT,
    in_legacy           INTEGER NOT NULL DEFAULT 0,
    in_gen9             INTEGER NOT NULL DEFAULT 0,
    unused              INTEGER NOT NULL DEFAULT 0,
    url                 TEXT,
    source              TEXT,
    c_signature         TEXT,
    lua_signature        TEXT,
    js_signature        TEXT,
    cs_signature        TEXT,
    -- derived, FTS-only columns (see module docstring)
    name_tokens         TEXT,
    alias_tokens        TEXT,
    param_text          TEXT
);

CREATE UNIQUE INDEX idx_natives_hash_apiset ON natives(hash, apiset);
CREATE INDEX idx_natives_name ON natives(name);
CREATE INDEX idx_natives_lua_name ON natives(lua_name);
CREATE INDEX idx_natives_ns ON natives(ns);
CREATE INDEX idx_natives_apiset ON natives(apiset);

-- Every name form (C name, Lua name, lowerCamel, hash, aliases in all three
-- forms) resolves to zero or more native rows. Not unique: the same Lua name
-- can point at both a client and a server row (e.g. SetEntityCoords).
CREATE TABLE native_names (
    name_form  TEXT NOT NULL,
    native_id  INTEGER NOT NULL REFERENCES natives(id)
);
CREATE INDEX idx_native_names_form ON native_names(name_form);

CREATE VIRTUAL TABLE natives_fts USING fts5(
    name_tokens, alias_tokens, ns, param_text, description,
    content='natives', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE docs (
    id        INTEGER PRIMARY KEY,
    path      TEXT UNIQUE NOT NULL,
    url       TEXT,
    title     TEXT,
    section   TEXT,
    nav_group TEXT,
    headings  TEXT,
    body      TEXT
);
CREATE INDEX idx_docs_path ON docs(path);

CREATE VIRTUAL TABLE docs_fts USING fts5(
    title, headings, body,
    content='docs', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect_rw(db_path: Path) -> sqlite3.Connection:
    """Read-write connection, used only by `fxref build`."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def connect_ro(db_path: Path) -> sqlite3.Connection:
    """Read-only connection for every other command (fast, no lock contention)."""
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def db_exists(db_path: Path) -> bool:
    return db_path.exists() and db_path.stat().st_size > 0


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO natives_fts(natives_fts) VALUES ('rebuild')")
    conn.execute("INSERT INTO docs_fts(docs_fts) VALUES ('rebuild')")


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return row[0] if not isinstance(row, sqlite3.Row) else row["value"]
