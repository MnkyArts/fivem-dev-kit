"""`fxref core ...` -- the `core` framework API index (DESIGN.md section 9.2).

Every command here degrades politely when `core` is not configured (no `core`
block in config.json, or its path is gone) or when the index has not been
built: it prints a one-line hint on stderr and exits 2, so the fxlint rule that
shells out to `fxref core resolve` can tell "no index" from "missing API".
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from fxkit import config, core_build, db, render, search, util


def git_sha(path: Path | str) -> str:
    """`git -C <core> rev-parse --short HEAD`. Read-only; '' when unavailable."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def build_core_index(conn: sqlite3.Connection) -> dict:
    """(Re)build `core_api` from the configured core checkout.

    Returns a stats dict; `{'core_configured': False}` when there is no core to
    index (which is not an error -- the kit works fine without one).
    """
    paths = config.core_paths()
    if not paths:
        return {"core_configured": False}
    types_path = paths["types"]
    if not types_path.is_file():
        return {"core_configured": False, "core_warning": f"types file not found: {types_path}"}
    sha = git_sha(paths["path"])
    rows, stats = core_build.build_core_rows(paths["path"], types_path, sha=sha)
    db.ensure_core_schema(conn)
    db.insert_core_rows(conn, rows)
    stats["core_configured"] = True
    stats["core_path"] = str(paths["path"])
    stats["core_types"] = str(types_path)
    return stats


def cmd_core_build(args: argparse.Namespace) -> int:
    paths = config.core_paths()
    if not paths:
        print("fxref: no `core` framework configured (config.json -> core.path)", file=sys.stderr)
        return 2
    db_path = config.db_path()
    with util.Timer() as timer:
        if not db.db_exists(db_path):
            conn = db.connect_rw(db_path)
            db.create_schema(conn)
        else:
            conn = db.connect_rw(db_path)
        stats = build_core_index(conn)
        conn.commit()
        conn.close()
    stats["elapsed_seconds"] = round(timer.seconds, 3)
    _persist_core_meta(db_path, stats)
    if args.json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return 0
    if not stats.get("core_configured"):
        print(f"fxref core: {stats.get('core_warning', 'core not configured')}", file=sys.stderr)
        return 2
    print(f"fxref core build complete in {stats['elapsed_seconds']:.2f}s  (core@{stats.get('core_sha') or '?'})")
    print(
        f"  functions: {stats['core_functions']} "
        f"(lib {stats['core_lib']}, proxy {stats['core_proxy']}) in {stats['core_namespaces']} namespaces"
    )
    print(f"  classes: {stats['core_classes']}   aliases: {stats['core_aliases']}   hooks: {stats['core_hooks']}")
    return 0


CORE_META_KEYS = (
    "core_configured", "core_functions", "core_classes", "core_aliases", "core_hooks",
    "core_lib", "core_proxy", "core_namespaces", "core_sha", "core_path",
)


def _persist_core_meta(db_path: Path, stats: dict) -> None:
    try:
        conn = db.connect_rw(db_path)
        for key in CORE_META_KEYS:
            if key in stats:
                value = stats[key]
                db.set_meta(conn, key, value if isinstance(value, str) else json.dumps(value))
        conn.commit()
        conn.close()
    except sqlite3.Error:
        pass


# ---------------------------------------------------------------------------
# read commands
# ---------------------------------------------------------------------------
def _open_index() -> sqlite3.Connection:
    """Read-only connection with a populated core index, or exit 2."""
    db_path = config.db_path()
    if not db.db_exists(db_path):
        print("fxref: database not built -- run: fxref build", file=sys.stderr)
        sys.exit(2)
    conn = db.connect_ro(db_path)
    if not db.has_core_index(conn):
        print("fxref: no core index -- configure `core` in config.json and run: fxref core build",
              file=sys.stderr)
        sys.exit(2)
    return conn


def _lookup_factory(conn: sqlite3.Connection):
    def lookup(name: str):
        rows = search.resolve_core(conn, name)
        return rows[0] if rows else None
    return lookup


def _types_rel() -> str:
    paths = config.core_paths()
    if not paths:
        return "types/core.lua"
    try:
        return str(paths["types"].relative_to(paths["path"]))
    except ValueError:
        return paths["types"].name


def cmd_core_search(args: argparse.Namespace) -> int:
    conn = _open_index()
    results = search.search_core(
        conn, args.query, side=args.side, ns=args.ns, kind=args.kind,
        limit=args.limit, show_all=args.all,
    )
    if args.json:
        out = []
        for e in results:
            d = render.core_row_to_dict(e["row"])
            d["exact"] = e["exact"]
            out.append(d)
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        if not results:
            print("(no matches)")
        for e in results:
            print(render.render_core_search_line(e["row"], e["exact"]))
    return 0


def cmd_core_show(args: argparse.Namespace) -> int:
    conn = _open_index()
    rows = search.resolve_core(conn, args.identifier)
    if not rows:
        print(f"fxref core: nothing named '{args.identifier}' in the core API index "
              f"(try: fxref core search {args.identifier})", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([render.core_row_to_dict(r) for r in rows], indent=2, ensure_ascii=False))
        return 0
    lookup = _lookup_factory(conn)
    rel = _types_rel()
    print("\n\n".join(render.render_core_card(r, lookup=lookup, types_rel=rel) for r in rows))
    return 0


def cmd_core_resolve(args: argparse.Namespace) -> int:
    conn = _open_index()
    out = []
    for identifier in args.names:
        rows = search.resolve_core(conn, identifier)
        out.append((identifier, rows, search.core_case_exact(identifier, rows)))
    if args.json:
        print(json.dumps(
            [render.core_resolve_to_json(i, r, c) for i, r, c in out], indent=2, ensure_ascii=False))
    else:
        for identifier, rows, case_exact in out:
            print(render.render_core_resolve_line(identifier, rows, case_exact))
    return 0


def cmd_core_ns(args: argparse.Namespace) -> int:
    conn = _open_index()
    rows = conn.execute(
        "SELECT namespace, side, access, sub FROM core_api WHERE kind='function'"
    ).fetchall()
    agg: dict[str, dict] = {}
    for r in rows:
        e = agg.setdefault(r["namespace"] or "?", {"count": 0, "sides": {}, "access": {}, "subs": set()})
        e["count"] += 1
        e["sides"][r["side"]] = e["sides"].get(r["side"], 0) + 1
        e["access"][r["access"]] = e["access"].get(r["access"], 0) + 1
        if r["sub"]:
            e["subs"].add(r["sub"])
    items = sorted(agg.items())
    if args.json:
        print(json.dumps([
            {"namespace": n, "count": e["count"], "sides": e["sides"],
             "access": e["access"], "sub_namespaces": sorted(e["subs"])}
            for n, e in items
        ], indent=2, ensure_ascii=False))
        return 0
    for n, e in items:
        sides = " ".join(f"{k}:{v}" for k, v in sorted(e["sides"].items()))
        access = " ".join(f"{k}:{v}" for k, v in sorted(e["access"].items()))
        subs = ("  subs: " + ", ".join(sorted(e["subs"]))) if e["subs"] else ""
        print(f"{n:<14} {e['count']:>3}  [{sides}]  [{access}]{subs}")
    return 0


def cmd_core_hooks(args: argparse.Namespace) -> int:
    conn = _open_index()
    rows = conn.execute("SELECT * FROM core_api WHERE kind='hook' ORDER BY id").fetchall()
    if args.json:
        print(json.dumps([render.core_row_to_dict(r) for r in rows], indent=2, ensure_ascii=False))
        return 0
    for r in rows:
        params = json.loads(r["params"] or "[]")
        args_txt = "(" + ", ".join(p["name"] for p in params) + ")"
        desc = util.first_sentence(r["description"], 80)
        print(f"{r['name']:<20} [{r['side']:<6}] {args_txt:<28} {desc}")
    print(f"\n{len(rows)} hooks -- subscribe with Core.on('<hook>', fn), fire with Core.emitHook('<hook>', ...)")
    return 0


def cmd_core_classes(args: argparse.Namespace) -> int:
    conn = _open_index()
    prefix = (args.prefix or "").lower()
    rows = conn.execute(
        "SELECT * FROM core_api WHERE kind IN ('class','alias') ORDER BY kind DESC, name"
    ).fetchall()
    rows = [r for r in rows if r["name"].lower().startswith(prefix)]
    if args.json:
        print(json.dumps([render.core_row_to_dict(r) for r in rows], indent=2, ensure_ascii=False))
        return 0
    for r in rows:
        if r["kind"] == "class":
            fields = json.loads(r["fields"] or "[]")
            required = [f["name"] for f in fields if not f.get("optional")]
            req = f"  required: {', '.join(required)}" if required else ""
            print(f"{r['name']:<28} class  {len(fields):>2} fields{req}")
        else:
            print(f"{r['name']:<28} alias  {r['signature']}")
    return 0


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------
def add_parser(sub) -> None:
    c = sub.add_parser("core", help="the `core` framework API index (DESIGN.md section 9)")
    csub = c.add_subparsers(dest="core_command", required=True)

    b = csub.add_parser("build", help="(re)build only the core_api index")
    b.add_argument("--json", action="store_true")
    b.set_defaults(func=cmd_core_build)

    s = csub.add_parser("search", help="search core functions/classes/aliases/hooks")
    s.add_argument("query", nargs="+")
    s.add_argument("--side", choices=["server", "client", "any"], default="any")
    s.add_argument("--ns", help="restrict to one namespace (Money, UI, Interactions, ...)")
    s.add_argument("--kind", choices=["function", "class", "alias", "hook"])
    s.add_argument("--limit", type=int, default=15)
    s.add_argument("--all", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_core_search)

    sh = csub.add_parser("show", help="full card for one core API")
    sh.add_argument("identifier", help="Core.Money.add | Money.add | CoreInteractionOptions | playerLoaded")
    sh.add_argument("--json", action="store_true")
    sh.set_defaults(func=cmd_core_show)

    r = csub.add_parser("resolve", help="batch FOUND/MISSING check (used by fxlint K013)")
    r.add_argument("names", nargs="+")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_core_resolve)

    n = csub.add_parser("ns", help="namespaces with counts, side mix and lib/proxy split")
    n.add_argument("--json", action="store_true")
    n.set_defaults(func=cmd_core_ns)

    h = csub.add_parser("hooks", help="the CoreHook list with sides and handler arguments")
    h.add_argument("--json", action="store_true")
    h.set_defaults(func=cmd_core_hooks)

    cl = csub.add_parser("classes", help="option/record tables and enum aliases")
    cl.add_argument("prefix", nargs="?", default="")
    cl.add_argument("--json", action="store_true")
    cl.set_defaults(func=cmd_core_classes)
