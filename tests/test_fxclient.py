#!/usr/bin/env python3
"""Plain-python3 tests for fxclient (the fivem-devtools client-side
observability CLI). No pytest, no real network, never the real dev server --
every test that needs a "deployed resource" builds its own throwaway fake
server tree + config (mirrors tests/test_fxserver.py's pattern) and points
FXKIT_CONFIG at it; anything that depends on fxkit.config for a *specific*
fake config is run as a subprocess (fresh process = no stale config.py
module-level cache), never imported in-process against a monkeypatched
config.

Run: python3 tests/test_fxclient.py
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
FXCLIENT = KIT / "bin" / "fxclient"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
RESOURCE_DIR = KIT / "resources-dev" / "fivem-devtools"

sys.path.insert(0, str(KIT / "lib"))

_pass = 0
_fail = 0


def check(name: str, cond: bool, detail=None) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"PASS {name}")
    else:
        _fail += 1
        suffix = f" -- {detail}" if detail else ""
        print(f"FAIL {name}{suffix}")


def _close(a, b, eps: float = 1e-6) -> bool:
    return abs(a - b) < eps


# ---------------------------------------------------------------------------
# fake devtools deployment (mirrors tests/test_fxserver.py's make_fake_server)
# ---------------------------------------------------------------------------

def make_fake_devtools_env(tmp: Path, port: int = 30298, deploy: bool = True) -> dict:
    data_dir = tmp / "txData" / "base"
    local_resources = data_dir / "resources" / "[local]"
    local_resources.mkdir(parents=True)
    logs_dir = tmp / "txData" / "logs"
    logs_dir.mkdir(parents=True)
    log_path = logs_dir / "fxserver.log"
    log_path.write_text("", encoding="utf-8")

    cfg_path = data_dir / "server.cfg"
    cfg_path.write_text(
        f'sv_hostname "Test"\nendpoint_add_tcp "0.0.0.0:{port}"\nsv_licenseKey "fake-not-a-real-key"\n',
        encoding="utf-8",
    )

    devtools_dir = local_resources / "fivem-devtools"
    if deploy:
        (devtools_dir / "queue").mkdir(parents=True)
        (devtools_dir / "out").mkdir(parents=True)

    config_path = tmp / "fxkit-config.json"
    config_path.write_text(json.dumps({
        "sources": {"nativedb": "/tmp", "fivem": "/tmp", "fivem_docs": "/tmp",
                    "natives_json_url": "x", "natives_cfx_json_url": "x"},
        "server": {
            "root": str(tmp),
            "data_dir": str(data_dir),
            "local_resources_dir": "resources/[local]",
            "server_cfg": "server.cfg",
            "log_file": str(log_path),
            "game_build": 3751,
            "rcon": {"host": "127.0.0.1", "port": port + 1, "password_env": "FXRCON_PASSWORD_TESTONLY"},
        },
        "project": {"workspace": str(tmp / "resources"), "language": "lua", "framework": "standalone",
                     "ox_lib": False, "game": "gta5", "author": "test"},
    }), encoding="utf-8")

    return {
        "root": tmp, "data_dir": data_dir, "local_resources": local_resources,
        "devtools_dir": devtools_dir, "config_path": config_path,
    }


def run_fxclient(args, config_path: Path, timeout: float = 15):
    env = dict(os.environ)
    env["FXKIT_CONFIG"] = str(config_path)
    return subprocess.run(
        [sys.executable, str(FXCLIENT), *args], capture_output=True, text=True, env=env, timeout=timeout,
    )


# ---------------------------------------------------------------------------
# queue.py (pure file I/O, no fxkit.config involved -- safe in-process)
# ---------------------------------------------------------------------------

def test_queue_enqueue_and_read_roundtrip():
    from fxkit.client import queue as queue_lib

    tmp = Path(tempfile.mkdtemp(prefix="fxclient-queue-"))
    try:
        qpath = tmp / "queue" / "commands.json"
        id1 = queue_lib.enqueue(qpath, "screenshot", {"resmon": True})
        id2 = queue_lib.enqueue(qpath, "info", {})
        check("queue: ids are sequential starting at 1", id1 == 1 and id2 == 2)

        data = queue_lib.read_queue(qpath)
        check("queue: next_id advances past both entries", data["next_id"] == 3)
        check(
            "queue: both commands persisted with correct cmd/args",
            data["commands"][0]["cmd"] == "screenshot" and data["commands"][0]["args"]["resmon"] is True
            and data["commands"][1]["cmd"] == "info",
        )
        check("queue: each entry has an integer ts", all(isinstance(c["ts"], int) for c in data["commands"]))
        check("queue: read_queue on a missing file returns the empty default",
              queue_lib.read_queue(tmp / "nope.json") == {"next_id": 1, "commands": []})

        out_dir = tmp / "out"
        out_dir.mkdir()
        (out_dir / "1.json").write_text(json.dumps({
            "id": 1, "cmd": "screenshot", "status": "ok", "message": "uploaded", "artifact": "out/shot-1.png",
        }), encoding="utf-8")
        result = queue_lib.read_result(out_dir, 1)
        check("queue: read_result parses a written result file", result is not None and result["status"] == "ok")
        check("queue: read_result returns None for a missing id", queue_lib.read_result(out_dir, 999) is None)

        got = queue_lib.wait_for_result(out_dir, 1, timeout=5, sleep=lambda s: None)
        check("queue: wait_for_result returns immediately when already resolved", got["status"] == "ok")

        fake_time = [0.0]
        try:
            queue_lib.wait_for_result(
                out_dir, 42, timeout=2, poll_interval=0.5,
                sleep=lambda s: fake_time.__setitem__(0, fake_time[0] + s),
                now=lambda: fake_time[0],
            )
            check("queue: wait_for_result raises on timeout for a missing id", False)
        except queue_lib.TimeoutWaitingForResult as exc:
            check("queue: wait_for_result raises TimeoutWaitingForResult on timeout", exc.command_id == 42)
            check("queue: timeout message points at `fxclient status`", "fxclient status" in str(exc), str(exc))

        for _ in range(queue_lib.MAX_KEPT_COMMANDS + 20):
            queue_lib.enqueue(qpath, "info", {})
        pruned = queue_lib.read_queue(qpath)
        check("queue: commands list is pruned to MAX_KEPT_COMMANDS",
              len(pruned["commands"]) == queue_lib.MAX_KEPT_COMMANDS, len(pruned["commands"]))
        check("queue: next_id keeps counting up even while pruning",
              pruned["next_id"] == id2 + 1 + queue_lib.MAX_KEPT_COMMANDS + 20)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# multipart.py (pure, no fxkit.config -- safe in-process). Mirrors
# tests/fixtures/lua_multipart_test.lua's cases for cross-language parity.
# ---------------------------------------------------------------------------

def test_multipart_python_mirror():
    from fxkit.client import multipart as mp_lib

    boundary = b"TestBoundary123"
    file_bytes = b"BINARY\x00\x01\x02\xffDATA"
    body = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="shot.png"\r\n'
        b"Content-Type: image/png\r\n"
        b"\r\n" + file_bytes + b"\r\n"
        b"--" + boundary + b"--\r\n"
    )

    data, info = mp_lib.parse_multipart(body, boundary)
    check("multipart(py): exact byte-for-byte payload (incl. NUL and 0xFF)", data == file_bytes)
    check("multipart(py): filename parsed from headers", info.filename == "shot.png")
    check("multipart(py): content-type parsed from headers", info.content_type == "image/png")

    try:
        mp_lib.parse_multipart(body, b"NotTheBoundary")
        check("multipart(py): unknown boundary raises", False)
    except mp_lib.MultipartError as exc:
        check("multipart(py): unknown boundary raises MultipartError('boundary not found')",
              str(exc) == "boundary not found")

    truncated = b"--" + boundary + b"\r\nContent-Type: image/png\r\n\r\nnoclosingboundary"
    try:
        mp_lib.parse_multipart(truncated, boundary)
        check("multipart(py): missing closing boundary raises", False)
    except mp_lib.MultipartError as exc:
        check("multipart(py): missing closing boundary raises MultipartError('closing boundary not found')",
              str(exc) == "closing boundary not found")

    check("multipart(py): parse_boundary, unquoted",
          mp_lib.parse_boundary("multipart/form-data; boundary=abc123") == "abc123")
    check("multipart(py): parse_boundary, quoted with a space",
          mp_lib.parse_boundary('multipart/form-data; boundary="abc 123"') == "abc 123")
    check("multipart(py): parse_boundary, no boundary present -> None",
          mp_lib.parse_boundary("text/plain") is None)


# ---------------------------------------------------------------------------
# trace.py (pure, no fxkit.config -- safe in-process)
# ---------------------------------------------------------------------------

def _expected_stats(durs_us: list) -> dict:
    n = len(durs_us)
    total = sum(durs_us)
    s = sorted(durs_us)
    idx = max(0, min(n - 1, math.ceil(0.95 * n) - 1))
    return {
        "frames": n,
        "total_ms": total / 1000.0,
        "avg_ms": (total / n) / 1000.0,
        "p95_ms": s[idx] / 1000.0,
        "max_ms": s[-1] / 1000.0,
    }


def test_trace_analyzer_on_fixture():
    from fxkit.client import trace as trace_lib

    trace = json.loads((FIXTURES / "profile-sample.json").read_text(encoding="utf-8"))
    result = trace_lib.analyze(trace, focus_resource="fivem-devtools")

    check("trace: frame_count matches the 50 recorded frames", result["frame_count"] == 50)
    check(
        "trace: frame_period_ms is ~16.667ms (the fixture's synthetic 60fps)",
        result["frame_period_ms"] is not None and _close(result["frame_period_ms"], 16.667, eps=0.001),
    )

    # Same duration formulas as the fixture generator: resource A has a
    # deterministic cyclic 40-58us pattern with one 200us spike on the last
    # frame; resource B is a plain 15-24us cycle with no spike.
    dur_a = [40 + (i % 10) * 2 for i in range(50)]
    dur_a[49] = 200
    dur_b = [15 + (i % 10) for i in range(50)]
    exp_a, exp_b = _expected_stats(dur_a), _expected_stats(dur_b)

    got_a = result["resources"].get("fivem-devtools")
    got_b = result["resources"].get("chat")
    check("trace: both fixture resources are present", got_a is not None and got_b is not None)

    if got_a and got_b:
        for key in ("frames", "total_ms", "avg_ms", "p95_ms", "max_ms"):
            check(f"trace: fivem-devtools.{key} matches the independently-computed expectation",
                  _close(got_a[key], exp_a[key]), f"got={got_a[key]} exp={exp_a[key]}")
            check(f"trace: chat.{key} matches the independently-computed expectation",
                  _close(got_b[key], exp_b[key]), f"got={got_b[key]} exp={exp_b[key]}")
        check("trace: fivem-devtools' max (the 0.2ms spike) exceeds its p95",
              got_a["max_ms"] > got_a["p95_ms"])
        check("trace: chat has no spike, so its p95 equals its max",
              _close(got_b["p95_ms"], got_b["max_ms"]))

    top = result["top_scopes"]
    check("trace: top_scopes filtered to fivem-devtools has exactly its one scope (queue:poll)",
          len(top) == 1 and top[0]["name"] == "queue:poll", top)
    if top:
        check("trace: queue:poll self_ms equals fivem-devtools' total_ms (no nested children in the fixture)",
              _close(top[0]["self_ms"], exp_a["total_ms"]))
        check("trace: queue:poll was captured once per frame", top[0]["calls"] == 50)

    all_scopes = trace_lib.analyze(trace)["top_scopes"]
    check("trace: unfiltered top_scopes includes both scopes, busiest (by self time) first",
          [s["name"] for s in all_scopes] == ["queue:poll", "chat:onMessage"], all_scopes)

    verdict = trace_lib.verdict_for(got_a) if got_a else ""
    check("trace: verdict is driven by avg (not the one-off max spike)", verdict.startswith("OK"), verdict)

    table = trace_lib.format_table(result, focus_resource="fivem-devtools")
    check("trace: format_table mentions both resources and prints a verdict line",
          "fivem-devtools" in table and "chat" in table and "verdict" in table)


def test_trace_analyzer_self_time_nesting():
    from fxkit.client import trace as trace_lib

    # One resource span (0-1000us) containing 'outer' (100-900us, 800us)
    # which itself contains 'inner' (300-500us, 200us). Expected self time:
    # inner = 200us (no children of its own), outer = 800-200 = 600us.
    events = [
        {"ph": "I", "name": "BeginFrame", "ts": 0, "tid": 1},
        {"ph": "I", "name": "BeginFrame", "ts": 20000, "tid": 1},
        {"ph": "B", "name": "tick (myresource)", "ts": 0, "tid": 2},
        {"ph": "B", "name": "outer", "ts": 100, "tid": 2},
        {"ph": "B", "name": "inner", "ts": 300, "tid": 2},
        {"ph": "E", "name": "inner", "ts": 500, "tid": 2},
        {"ph": "E", "name": "outer", "ts": 900, "tid": 2},
        {"ph": "E", "name": "tick (myresource)", "ts": 1000, "tid": 2},
    ]
    result = trace_lib.analyze({"traceEvents": events}, focus_resource="myresource")

    res = result["resources"].get("myresource")
    check("trace nesting: resource span duration is 1000us -> 1.0ms total", res is not None and _close(res["total_ms"], 1.0))

    scopes = {s["name"]: s for s in result["top_scopes"]}
    check("trace nesting: both scopes attributed to myresource", set(scopes) == {"outer", "inner"}, scopes)
    if scopes:
        check("trace nesting: inner's self time equals its own full duration (0.2ms)",
              _close(scopes["inner"]["self_ms"], 0.2))
        check("trace nesting: outer's self time excludes inner's duration (0.8-0.2=0.6ms)",
              _close(scopes["outer"]["self_ms"], 0.6))


# ---------------------------------------------------------------------------
# logs.py (pure, no fxkit.config -- safe in-process)
# ---------------------------------------------------------------------------

def test_logs_filtering():
    from fxkit.client import logs as logs_lib

    lines = [
        "[       100] [  citizen-scripting] Thread/ starting up",
        "[       200] [  citizen-scripting] Thread/ SCRIPT ERROR: attempt to call a nil value (global 'Foo')",
        "[       200] [  citizen-scripting] Thread/ stack traceback:",
        "[       300] [        myresource] Thread/ hello from myresource",
        "[       400] [  citizen-scripting] Thread/ all good here",
    ]
    errors = logs_lib.filter_lines(lines, errors_only=True)
    check("logs: --errors keeps SCRIPT ERROR and stack traceback lines",
          len(errors) == 2 and "SCRIPT ERROR" in errors[0], errors)

    by_resource = logs_lib.filter_lines(lines, resource="myresource")
    check("logs: --resource keeps only lines mentioning the resource name", by_resource == [lines[3]], by_resource)

    tailed = logs_lib.filter_lines(lines, tail=2)
    check("logs: --tail keeps only the last N lines", tailed == lines[-2:])

    check("logs: read_log on a missing file returns an empty list",
          logs_lib.read_log(Path("/nonexistent/client.log")) == [])

    gated_lines = lines + ["[  500] [cmd] Command profiler is disabled in production mode. See ^2https://aka.cfx.re/prod-console^7 for further information."]
    hit = logs_lib.find_production_gate_warning(gated_lines)
    check("logs: find_production_gate_warning finds the production-mode denial message",
          hit is not None and "disabled in production mode" in hit)
    check("logs: find_production_gate_warning is None when nothing matches",
          logs_lib.find_production_gate_warning(lines) is None)


# ---------------------------------------------------------------------------
# setup.py plan() against the REAL config (read-only, never writes anything)
# ---------------------------------------------------------------------------

def test_setup_plan_data():
    from fxkit.client import setup as setup_lib

    plan = setup_lib.plan()
    check("setup: plan() includes both deploy commands", len(plan["deploy_commands"]) == 2, plan["deploy_commands"])
    check("setup: plan() includes all 4 required server.cfg lines", plan["server_cfg_lines"] == [
        "ensure screenshot-basic",
        "ensure fivem-devtools",
        "add_ace resource.fivem-devtools command allow",
        "add_ace group.admin fivem-devtools.use allow",
    ])
    check("setup: agent fetch/run commands target the /fivem-devtools/agent endpoint",
          "/fivem-devtools/agent" in plan["agent_fetch_command"] and "-Server" in plan["agent_run_command"])
    check("setup: screenshot-basic clone is actually detected on this machine (cloned earlier in this task)",
          plan["screenshot_basic_present"] is True, plan["screenshot_basic_dir"])


# ---------------------------------------------------------------------------
# bin/fxclient end-to-end via subprocess (fresh process per fake config)
# ---------------------------------------------------------------------------

def test_cli_status_not_deployed_falls_back_to_kit_copy():
    tmp = Path(tempfile.mkdtemp(prefix="fxclient-cli-notdeployed-"))
    try:
        env = make_fake_devtools_env(tmp, deploy=False)
        proc = run_fxclient(["status", "--json"], env["config_path"])
        check("cli status: exits 0 even when nothing is deployed", proc.returncode == 0, proc.stderr)
        try:
            status = json.loads(proc.stdout)
        except ValueError:
            status = {}
        check("cli status: devtools_deployed is false", status.get("devtools_deployed") is False, proc.stdout)
        check("cli status: falls back to the kit's own resource copy",
              status.get("devtools_dir") == str(RESOURCE_DIR), status.get("devtools_dir"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_screenshot_timeout_is_clean_and_actionable():
    tmp = Path(tempfile.mkdtemp(prefix="fxclient-cli-timeout-"))
    try:
        env = make_fake_devtools_env(tmp)
        proc = run_fxclient(["screenshot", "--timeout", "1"], env["config_path"], timeout=10)
        check("cli screenshot: exits 1 on timeout (nothing is polling the queue in this test)",
              proc.returncode == 1, proc.stdout + proc.stderr)
        check("cli screenshot: timeout message points at `fxclient status`",
              "fxclient status" in proc.stderr, proc.stderr)

        queue_path = env["devtools_dir"] / "queue" / "commands.json"
        queued = json.loads(queue_path.read_text(encoding="utf-8"))
        check("cli screenshot: the command was queued before the CLI started waiting",
              queued["commands"][0]["cmd"] == "screenshot" and queued["commands"][0]["args"]["encoding"] == "png")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_screenshot_success_via_concurrent_result_write():
    tmp = Path(tempfile.mkdtemp(prefix="fxclient-cli-shot-"))
    try:
        env = make_fake_devtools_env(tmp)
        out_dir = env["devtools_dir"] / "out"

        proc = subprocess.Popen(
            [sys.executable, str(FXCLIENT), "screenshot", "--jpg", "--timeout", "8"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, "FXKIT_CONFIG": str(env["config_path"])},
        )
        try:
            time.sleep(0.3)  # let the CLI enqueue command id 1 and start polling
            (out_dir / "shot-1.jpg").write_bytes(b"\xff\xd8\xff fake jpg bytes")
            (out_dir / "1.json").write_text(json.dumps({
                "id": 1, "cmd": "screenshot", "status": "ok", "message": "uploaded",
                "artifact": "out/shot-1.jpg",
            }), encoding="utf-8")
            stdout, stderr = proc.communicate(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()

        check("cli screenshot: exits 0 once the result file appears mid-poll", proc.returncode == 0, stderr)
        expected_path = str((out_dir / "shot-1.jpg").resolve())
        last_line = stdout.strip().splitlines()[-1] if stdout.strip() else ""
        check("cli screenshot: last stdout line is the absolute artifact path", last_line == expected_path, repr(stdout))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_exec_reports_error_status():
    tmp = Path(tempfile.mkdtemp(prefix="fxclient-cli-exec-"))
    try:
        env = make_fake_devtools_env(tmp)
        out_dir = env["devtools_dir"] / "out"
        (out_dir / "1.json").write_text(json.dumps({
            "id": 1, "cmd": "serverexec", "status": "error", "message": "ExecuteCommand failed: bad command",
        }), encoding="utf-8")

        proc = run_fxclient(["exec", "--server", "not-a-real-command", "--timeout", "5"], env["config_path"])
        check("cli exec: exits 1 on an error-status result", proc.returncode == 1, proc.stdout + proc.stderr)
        check("cli exec: prints the reported error message", "ExecuteCommand failed: bad command" in proc.stdout, proc.stdout)

        proc2 = run_fxclient(["exec"], env["config_path"])
        check("cli exec: requires exactly one of --client/--server (argparse mutually-exclusive, required)",
              proc2.returncode != 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Lua: syntax check every file in the resource, then the pure-logic unit
# harness (see tests/fixtures/lua_multipart_test.lua).
# ---------------------------------------------------------------------------

def test_lua_syntax_all_resource_files():
    lua_files = sorted(RESOURCE_DIR.rglob("*.lua"))
    check("lua syntax: at least one .lua file found in the resource", len(lua_files) > 0)

    luac = shutil.which("luac") or shutil.which("luac5.4") or shutil.which("luac5.5")
    if not luac:
        check("lua syntax: a `luac` binary is available to check with", False, "luac not found on PATH")
        return
    for f in lua_files:
        proc = subprocess.run([luac, "-p", str(f)], capture_output=True, text=True)
        check(f"lua syntax: {f.relative_to(KIT)} parses cleanly (luac -p)", proc.returncode == 0, proc.stderr)


def test_lua_pure_unit_harness():
    lua = shutil.which("lua") or shutil.which("lua5.4") or shutil.which("lua5.5")
    if not lua:
        check("lua pure-unit harness: a `lua` interpreter is available", False, "lua not found on PATH")
        return

    harness = FIXTURES / "lua_multipart_test.lua"
    proc = subprocess.run([lua, str(harness), str(RESOURCE_DIR)], capture_output=True, text=True, timeout=15)
    check("lua pure-unit harness: exits 0 (every pure-Lua assertion passed)",
          proc.returncode == 0, proc.stdout + proc.stderr)
    summary_lines = [l for l in proc.stdout.splitlines() if l.strip().endswith("failed")]
    check("lua pure-unit harness: prints a 'N passed, 0 failed' summary line",
          bool(summary_lines) and summary_lines[-1].strip().endswith("0 failed"), proc.stdout)


# ---------------------------------------------------------------------------
# fxlint, if the linting engineer's bin/fxlint has landed
# ---------------------------------------------------------------------------

def test_fxlint_if_available():
    fxlint = KIT / "bin" / "fxlint"
    if not fxlint.exists():
        check("fxlint: skipped -- bin/fxlint not present in this checkout", True)
        return

    proc = subprocess.run(
        [sys.executable, str(fxlint), str(RESOURCE_DIR), "--json"],
        capture_output=True, text=True, timeout=30,
    )
    try:
        report = json.loads(proc.stdout)
    except ValueError:
        check("fxlint: produced parseable --json output", False, proc.stdout + proc.stderr)
        return

    summary = report.get("summary", {})
    check("fxlint: 0 errors on the fivem-devtools resource", summary.get("errors", -1) == 0, json.dumps(report, indent=2))


# ---------------------------------------------------------------------------

def main() -> int:
    test_queue_enqueue_and_read_roundtrip()
    test_multipart_python_mirror()
    test_trace_analyzer_on_fixture()
    test_trace_analyzer_self_time_nesting()
    test_logs_filtering()
    test_setup_plan_data()
    test_cli_status_not_deployed_falls_back_to_kit_copy()
    test_cli_screenshot_timeout_is_clean_and_actionable()
    test_cli_screenshot_success_via_concurrent_result_write()
    test_cli_exec_reports_error_status()
    test_lua_syntax_all_resource_files()
    test_lua_pure_unit_harness()
    test_fxlint_if_available()

    print(f"\n{_pass} passed, {_fail} failed")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
