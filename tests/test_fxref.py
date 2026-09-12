#!/usr/bin/env python3
"""Smoke tests for `fxref` (DESIGN.md section 10).

Plain python3, no pytest: `python3 tests/test_fxref.py`
Drives `bin/fxref` via subprocess, prints PASS/FAIL per check, exits 1 on any
failure (0 if everything passes).

Note on the "unnamed native" test target: DESIGN.md's own example hash
(0x0B40ED49D7D6FF84 / N_0x0b40ed49d7d6ff84) turned out, against the actual
gta5-nativedb-data checked out on this machine, to now have a real alloc8or
name (REACTIVATE_ALL_WORLD_BRAINS_THAT_ARE_WAITING_TILL_OUT_OF_RANGE) -- i.e.
alloc8or has since named it, so it is genuinely not unnamed in the live
merged database any more. We use a hash verified (via direct DB query) to
still be unnamed today, to test the same code path (N_0x... lookup of an
unnamed native) against real data instead of a now-stale example.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FXREF = ROOT / "bin" / "fxref"

# Verified unnamed today: no alloc8or name, no FiveM-json name either.
UNNAMED_HASH_LUA = "N_0x36391f397731595d"

checks = 0
failures = 0


def run(*args: str, timeout: float = 90) -> tuple[int, str, str, float]:
    t0 = time.perf_counter()
    proc = subprocess.run(
        [str(FXREF), *args], capture_output=True, text=True, timeout=timeout
    )
    elapsed = time.perf_counter() - t0
    return proc.returncode, proc.stdout, proc.stderr, elapsed


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks, failures
    checks += 1
    if condition:
        print(f"PASS  {name}")
    else:
        failures += 1
        suffix = f"  -- {detail}" if detail else ""
        print(f"FAIL  {name}{suffix}")


def check_timing(name: str, elapsed: float, limit: float = 0.2) -> None:
    check(f"{name}  (<{int(limit * 1000)}ms)", elapsed < limit, f"took {elapsed * 1000:.1f}ms")


def parse_json(out: str):
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# `fxref core` -- the core framework index (DESIGN.md section 9.2)
# ---------------------------------------------------------------------------
SAMPLE_TYPES = """---@meta

---@alias CoreMoneyAccount '\"cash\"' | '\"bank\"' | string

---@alias CoreHook
---| '\"ready\"'        # core started on this side — server: () / client: ()
---| '\"moneyChanged\"' # (server) (src, account, amount, delta, reason)

---@class CoreMarkerOptions
---@field coords vector3 required world position
---@field type? integer marker type (default 1)
---@field onPick? fun(ctx: CoreInteractionContext): boolean a callback

--------------------------------------------------------------------------------
-- Core.Money (server/money.lua §4.3) — (server) only
--------------------------------------------------------------------------------

---@class Core.Money
Core.Money = {}

---(server) Adds a positive amount; false when it would pass the cap.
---@param src integer
---@param account CoreMoneyAccount
---@param amount integer > 0
---@param reason? string shows up in the audit log
---@return boolean ok
function Core.Money.add(src, account, amount, reason) end

---@class Core.UI.menu
local CoreUIMenu = {}
---(client) `open(opts)` — (server) `open(src, opts)`.
---@param opts CoreMenuOptions|integer client: the options; server: the src
---@return any value the picked item's `value`, or nil
function CoreUIMenu.open(opts) end
"""


def test_core_parser_unit():
    """The LuaLS parser is a pure function -- exercise it on a small sample."""
    sys.path.insert(0, str(ROOT / "lib"))
    from fxkit import core_build

    api = core_build.parse_types(SAMPLE_TYPES)
    by_name = {f.name: f for f in api.functions}
    check("parser: finds both function stubs", set(by_name) == {"Core.Money.add", "Core.UI.menu.open"},
          sorted(by_name))

    add = by_name.get("Core.Money.add")
    check("parser: namespace/side from the (server) marker",
          add and add.namespace == "Money" and add.side == "server", add)
    check("parser: signature", add and core_build.signature_for(add)
          == "Core.Money.add(src, account, amount, reason?) -> boolean ok",
          core_build.signature_for(add) if add else None)
    check("parser: `integer > 0` splits into type + description",
          add and add.params[2] == {"name": "amount", "optional": False, "type": "integer", "description": "> 0"},
          add.params[2] if add else None)
    check("parser: section banner -> design_ref", core_build.design_ref(add.section) == "DESIGN §4.3",
          core_build.design_ref(add.section))

    menu = by_name.get("Core.UI.menu.open")
    check("parser: `local CoreUIMenu` maps back to Core.UI.menu",
          menu and menu.namespace == "UI" and menu.sub == "menu", menu)
    check("parser: a (client)+(server) description means shared", menu and menu.side == "shared", menu.side if menu else None)

    classes = {c.name: c for c in api.classes}
    marker = classes.get("CoreMarkerOptions")
    check("parser: class fields", marker and [f["name"] for f in marker.fields] == ["coords", "type", "onPick"],
          marker.fields if marker else None)
    check("parser: optional field marked", marker and marker.fields[1]["optional"] is True)
    check("parser: `fun(...): boolean` keeps its return type",
          marker and marker.fields[2]["type"] == "fun(ctx: CoreInteractionContext): boolean",
          marker.fields[2] if marker else None)

    aliases = {a.name: a for a in api.aliases}
    money = aliases.get("CoreMoneyAccount")
    check("parser: inline alias values",
          money and [v["value"] for v in money.values] == ["cash", "bank", "string"],
          money.values if money else None)
    hooks = aliases.get("CoreHook")
    check("parser: `---|` alias values", hooks and len(hooks.values) == 2, hooks.values if hooks else None)

    rows = core_build.build_rows(api, {}, {}, sha="deadbee")
    kinds = sorted({r["kind"] for r in rows})
    check("build_rows: emits function/class/alias/hook rows",
          kinds == ["alias", "class", "function", "hook"], kinds)
    check("build_rows: Core.Money.add is a proxy (Money is not a LIB_MODULE)",
          next(r["access"] for r in rows if r["name"] == "Core.Money.add") == "proxy")
    hook_row = next(r for r in rows if r["kind"] == "hook" and r["name"] == "moneyChanged")
    check("build_rows: hook side + args",
          hook_row["side"] == "server"
          and hook_row["signature"] == "Core.on('moneyChanged', function(src, account, amount, delta, reason) end)",
          hook_row)

    libs, subs = core_build.parse_import(
        "local LIB_MODULES <const> = {\n Utils = 'utils', UI = 'ui',\n}\n"
        "local SUB_NAMESPACES <const> = {\n UI = { menu = true, input = true },\n}\n")
    check("parse_import: LIB_MODULES", libs == {"Utils": "utils", "UI": "ui"}, libs)
    check("parse_import: SUB_NAMESPACES", subs == {"UI": {"menu", "input"}}, subs)


def test_core_index():
    sys.path.insert(0, str(ROOT / "lib"))
    from fxkit import config as fxconfig
    if not fxconfig.core_paths():
        check("core configured (skipping fxref core tests)", True, "no core block in config.json")
        return

    rc, out, err, el = run("core", "build", "--json", timeout=30)
    check("core build exits 0", rc == 0, err.strip()[:300])
    check("core build < 2s", el < 2.0, f"took {el:.2f}s")
    stats = parse_json(out) or {}
    check("core build indexes ~400 functions", (stats.get("core_functions") or 0) >= 380, str(stats.get("core_functions")))
    check("core build splits lib vs proxy",
          (stats.get("core_lib") or 0) > 0 and (stats.get("core_proxy") or 0) > 0, str(stats))
    check("core build records the git sha", bool(stats.get("core_sha")), str(stats.get("core_sha")))

    # --- show Core.Money.add: the DESIGN section 9.2 quality bar -------------
    rc, out, err, el = run("core", "show", "Core.Money.add")
    check_timing("core show Core.Money.add", el)
    check("core show: signature line",
          "Core.Money.add(src, account, amount, reason?) -> boolean ok" in out, out[:400])
    check("core show: side + access", "side: server" in out and "access: proxy" in out, out[:400])
    check("core show: the coroutine/onReady rule for a proxy",
          "coroutine" in out and "Core.onReady" in out, out[:600])
    check("core show: params with types and descriptions",
          "account" in out and "CoreMoneyAccount" in out and "audit log" in out, out[:800])
    check("core show: the CoreMoneyAccount alias values inline",
          "'cash' | 'bank'" in out, out[:800])
    check("core show: source line", "types/core.lua:" in out, out[-200:])

    for ident in ("Money.add", "money.add", "Core.Money.add"):
        rc, out, err, el = run("core", "show", ident, "--json")
        rows = parse_json(out) or []
        check(f"core show accepts '{ident}'", rc == 0 and rows and rows[0]["name"] == "Core.Money.add", out[:200])

    # --- show a class --------------------------------------------------------
    rc, out, err, el = run("core", "show", "CoreInteractionOptions")
    check_timing("core show CoreInteractionOptions", el)
    for field in ("coords", "radius", "label", "onInteract", "canInteract", "cooldown", "data"):
        check(f"core show CoreInteractionOptions lists '{field}'", field in out, out[:200])

    # --- search --------------------------------------------------------------
    rc, out, err, el = run("core", "search", "interaction", "add", "--side", "client", "--limit", "3", "--json")
    check_timing("core search interaction add", el)
    top3 = [r["name"] for r in (parse_json(out) or [])]
    check("core search 'interaction add' --side client top-3 has Core.Interactions.add",
          "Core.Interactions.add" in top3, str(top3))

    rc, out, err, el = run("core", "search", "money", "--json")
    names = [r["name"] for r in (parse_json(out) or [])]
    check("core search money lists the Money functions",
          {"Core.Money.add", "Core.Money.remove", "Core.Money.get"} <= set(names), str(names))

    # --- resolve -------------------------------------------------------------
    rc, out, err, el = run("core", "resolve", "Core.Money.add", "Money.remove", "Core.Nope.x", "--json")
    check_timing("core resolve", el)
    results = parse_json(out) or []
    check("core resolve: exits 0", rc == 0, str(rc))
    check("core resolve: 2 FOUND, 1 MISSING",
          sum(1 for r in results if r["found"]) == 2 and sum(1 for r in results if not r["found"]) == 1,
          str(results))
    rc, out, err, el = run("core", "resolve", "Core.money.add", "--json")
    entry = (parse_json(out) or [{}])[0]
    check("core resolve: a wrong-case name is reported (case_exact false)",
          entry.get("found") and entry.get("case_exact") is False, str(entry))

    # --- ns / hooks / classes -------------------------------------------------
    rc, out, err, el = run("core", "ns", "--json")
    check_timing("core ns", el)
    namespaces = {e["namespace"] for e in (parse_json(out) or [])}
    check("core ns lists the big namespaces",
          {"Money", "UI", "Player", "Vehicles", "Interactions"} <= namespaces, str(sorted(namespaces))[:300])

    rc, out, err, el = run("core", "hooks", "--json")
    check_timing("core hooks", el)
    hooks = parse_json(out) or []
    check("core hooks lists >= 25 hooks", len(hooks) >= 25, str(len(hooks)))
    check("core hooks carry a side and arguments",
          all(h.get("side") for h in hooks)
          and any(h["name"] == "playerDropped" and "charId" in (h.get("param_text") or h["signature"])
                  for h in hooks),
          str(hooks[:2]))

    rc, out, err, el = run("core", "classes", "--json")
    check_timing("core classes", el)
    classes = {c["name"] for c in (parse_json(out) or [])}
    check("core classes lists the option tables",
          {"CoreInteractionOptions", "CoreMarkerOptions", "CoreMoneyAccount"} <= classes,
          str(sorted(classes))[:300])

    # --- every stub and class renders -----------------------------------------
    render_failures = []
    conn = sqlite3.connect(f"file:{(ROOT / 'data' / 'fxref.sqlite').as_posix()}?mode=ro", uri=True)
    names = [r[0] for r in conn.execute("SELECT name FROM core_api").fetchall()]
    conn.close()
    batch = subprocess.run([str(FXREF), "core", "resolve", "--json", *names],
                            capture_output=True, text=True, timeout=60)
    resolved = json.loads(batch.stdout)
    check("every indexed name resolves back", all(r["found"] for r in resolved),
          str([r["input"] for r in resolved if not r["found"]][:5]))

    # rendering: one `show` per kind is enough for the CLI path, the bulk render
    # is exercised in-process to keep the test fast.
    sys.path.insert(0, str(ROOT / "lib"))
    from fxkit import db as fxdb, render as fxrender, search as fxsearch
    conn = fxdb.connect_ro(fxconfig.db_path())
    lookup = lambda n: (fxsearch.resolve_core(conn, n) or [None])[0]  # noqa: E731
    for row in conn.execute("SELECT * FROM core_api").fetchall():
        try:
            fxrender.render_core_card(row, lookup=lookup)
            fxrender.render_core_search_line(row, False)
        except Exception as exc:  # noqa: BLE001
            render_failures.append((row["name"], repr(exc)))
    conn.close()
    check(f"all {len(names)} core rows render without exception", not render_failures,
          str(render_failures[:3]))

    # --- stats ----------------------------------------------------------------
    rc, out, err, el = run("stats", "--json")
    meta = parse_json(out) or {}
    check("stats shows core counts", (meta.get("core_functions") or 0) >= 380, str(meta.get("core_functions")))
    check("stats shows the core git sha", bool(meta.get("core_sha")), str(meta.get("core_sha")))


def main() -> int:
    if not FXREF.exists():
        print(f"FAIL  bin/fxref exists at {FXREF}")
        return 1

    # --- build -------------------------------------------------------
    rc, out, err, el = run("build", "--no-download", timeout=90)
    check("build exits 0", rc == 0, err.strip()[:300])
    check_timing("build", el, limit=60.0)

    rc, out, err, el = run("stats", "--json")
    check("stats exits 0", rc == 0, err.strip()[:300])
    stats = parse_json(out) or {}
    check("natives_total >= 7500", (stats.get("natives_total") or 0) >= 7500, str(stats.get("natives_total")))
    check("cfx_total >= 900", (stats.get("cfx_total") or 0) >= 900, str(stats.get("cfx_total")))
    check("docs_total >= 300", (stats.get("docs_total") or 0) >= 300, str(stats.get("docs_total")))

    # --- show SET_PED_INTO_VEHICLE -> client + server -----------------
    rc, out, err, el = run("show", "SET_PED_INTO_VEHICLE", "--json")
    check_timing("show SET_PED_INTO_VEHICLE", el)
    rows = parse_json(out) or []
    apisets = sorted(r.get("apiset") for r in rows)
    check("show SET_PED_INTO_VEHICLE prints client+server rows", apisets == ["client", "server"], str(apisets))

    # --- GetShapeTestResult Lua return list ---------------------------
    rc, out, err, el = run("show", "GetShapeTestResult", "--json")
    rows = parse_json(out) or []
    expected_sig = (
        "GetShapeTestResult(shapeTestHandle) -> integer retval, boolean hit, "
        "vector3 endCoords, vector3 surfaceNormal, integer entityHit"
    )
    sig = rows[0]["lua_signature"] if rows else None
    check("GetShapeTestResult Lua signature matches DESIGN.md", sig == expected_sig, str(sig))

    # --- show 0x1647F1CB -> GET_ENTITY_COORDS server -------------------
    rc, out, err, el = run("show", "0x1647F1CB", "--json")
    check_timing("show 0x1647F1CB", el)
    rows = parse_json(out) or []
    has_server_gec = any(r.get("name") == "GET_ENTITY_COORDS" and r.get("apiset") == "server" for r in rows)
    check("show 0x1647F1CB -> GET_ENTITY_COORDS server", has_server_gec, str([(r.get("name"), r.get("apiset")) for r in rows]))

    # --- show N_0x... works (unnamed native) ---------------------------
    rc, out, err, el = run("show", UNNAMED_HASH_LUA, "--json")
    check_timing(f"show {UNNAMED_HASH_LUA}", el)
    rows = parse_json(out) or []
    ok = rc == 0 and len(rows) == 1 and rows[0].get("name", "").startswith("_0x")
    check(f"show {UNNAMED_HASH_LUA} works (unnamed native)", ok, str(rows))

    # --- search "lock vehicle doors" top-3 -----------------------------
    rc, out, err, el = run("search", "lock", "vehicle", "doors", "--limit", "3", "--json")
    check_timing("search lock vehicle doors", el)
    results = parse_json(out) or []
    top3 = [r["name"] for r in results]
    check("search 'lock vehicle doors' top-3 includes SET_VEHICLE_DOORS_LOCKED", "SET_VEHICLE_DOORS_LOCKED" in top3, str(top3))

    # --- search "player invincible" -------------------------------------
    rc, out, err, el = run("search", "player", "invincible", "--json")
    check_timing("search player invincible", el)
    results = parse_json(out) or []
    names_all = [r["name"] for r in results]
    check("search 'player invincible' includes SET_PLAYER_INVINCIBLE", "SET_PLAYER_INVINCIBLE" in names_all, str(names_all))

    # --- search "car engine on" --side client ----------------------------
    rc, out, err, el = run("search", "car", "engine", "on", "--side", "client", "--json")
    check_timing("search car engine on --side client", el)
    results = parse_json(out) or []
    names_all = [r["name"] for r in results]
    check("search 'car engine on' --side client includes SET_VEHICLE_ENGINE_ON", "SET_VEHICLE_ENGINE_ON" in names_all, str(names_all))

    # --- search "state bag" --side server ---------------------------------
    rc, out, err, el = run("search", "state", "bag", "--side", "server", "--json")
    check_timing("search state bag --side server", el)
    results = parse_json(out) or []
    names_all = [r["name"] for r in results]
    check("search 'state bag' --side server includes ADD_STATE_BAG_CHANGE_HANDLER", "ADD_STATE_BAG_CHANGE_HANDLER" in names_all, str(names_all))

    # --- resolve batch ------------------------------------------------
    rc, out, err, el = run("resolve", "SetVehicleDoorsLocked", "GetEntityCoords", "NotARealNative", "--json")
    check_timing("resolve (3 names)", el)
    check("resolve exits 0", rc == 0, str(rc))
    results = parse_json(out) or []
    found_count = sum(1 for r in results if r.get("found"))
    missing_count = sum(1 for r in results if not r.get("found"))
    check("resolve: 2 found, 1 missing", found_count == 2 and missing_count == 1, str(results))
    gec = next((r for r in results if r.get("input") == "GetEntityCoords"), None)
    check(
        "resolve GetEntityCoords has client+server matches",
        bool(gec) and len(gec.get("matches", [])) == 2,
        str(gec),
    )

    # --- resolve: 200 names in < 300ms ------------------------------
    db_path = ROOT / "data" / "fxref.sqlite"
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    two_hundred = [r[0] for r in conn.execute("SELECT lua_name FROM natives LIMIT 200").fetchall()]
    conn.close()
    rc, out, err, el = run("resolve", *two_hundred, "--json", timeout=10)
    check("resolve 200 names  (<300ms)", el < 0.3, f"took {el * 1000:.1f}ms")
    check("resolve 200 names exits 0", rc == 0, str(rc))

    # --- docs search "state bags" top-3 --------------------------------
    rc, out, err, el = run("docs", "search", "state", "bags", "--limit", "3", "--json")
    check_timing("docs search state bags", el)
    results = parse_json(out) or []
    top3_ids = [r["id"] for r in results]
    check(
        "docs search 'state bags' top-3 includes the state bags page",
        "docs/scripting-manual/networking/state-bags" in top3_ids,
        str(top3_ids),
    )

    # --- docs show <id> prints its title --------------------------------
    rc, out, err, el = run("docs", "show", "docs/scripting-manual/networking/state-bags")
    check_timing("docs show state-bags", el)
    check("docs show prints title 'State Bags'", "State Bags" in out, out[:200])

    # --- a few more read-command timing spot checks --------------------
    rc, out, err, el = run("ns", "--json")
    check_timing("ns", el)
    rc, out, err, el = run("docs", "ls", "docs/scripting-manual")
    check_timing("docs ls docs/scripting-manual", el)

    test_core_parser_unit()
    test_core_index()

    print()
    print(f"{checks - failures}/{checks} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
