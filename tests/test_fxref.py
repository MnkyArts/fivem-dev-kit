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

    print()
    print(f"{checks - failures}/{checks} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
