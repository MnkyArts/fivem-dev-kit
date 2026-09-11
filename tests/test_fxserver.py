#!/usr/bin/env python3
"""Plain-python3 tests for fxserver. No pytest, no network, never the real
dev server -- every test builds its own throwaway fake server tree + config
and points FXKIT_CONFIG at it.

Run: python3 tests/test_fxserver.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
FXSERVER = KIT / "bin" / "fxserver"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

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


# ---------------------------------------------------------------------------
# fake server tree
# ---------------------------------------------------------------------------

FAKE_LICENSE_KEY = "fake-not-a-real-license-key-ZZZ999"

SERVER_CFG_TEMPLATE = """\
# fake server.cfg for fxserver tests -- not a real secret
sv_hostname "Test"
endpoint_add_tcp "0.0.0.0:{port}"
endpoint_add_udp "0.0.0.0:{port}"
sv_licenseKey "{key}"

ensure mapmanager
ensure chat
"""

LOG_FIXTURE = (
    "\x1b[32m[           resources] Scanning resources.\x1b[0m\n"
    "║             TXADMIN║ ================================================================\n"
    "║             TXADMIN║ ======== [1] FXServer Starting - 1/1/2026, 12:00:00 PM      \n"
    "[           resources] Started resource mapmanager\n"
    "[      script:myresource] SCRIPT ERROR: attempt to call a nil value (global 'Foo')\n"
    "[      script:myresource] stack traceback:\n"
    "[           resources] Started resource myresource\n"
    "[    c-scripting-core] some unrelated info line\n"
    "[      script:monitor] [txAdmin] Ready.\n"
)

LOG_FIXTURE_WITH_TIMESTAMPS = (
    "2020-01-01 00:00:00 [script:old] this line is ancient\n"
    "2099-01-01 00:00:00 [script:new] this line is from the future\n"
)

_HEARTBEAT_LINE = (
    "[ citizen-server-impl] Server list query returned an error: server request failed: "
    "server request failed for endpoint https://217.236.33.82:30120/info.json "
    '(Get "https://217.236.33.82:30120/info.json": context deadline exceeded)\n'
)
LOG_FIXTURE_WITH_HEARTBEAT_NOISE = (
    _HEARTBEAT_LINE * 3
    + "[      script:myresource] SCRIPT ERROR: attempt to call a nil value (global 'Foo')\n"
    + "[      script:myresource] stack traceback:\n"
    + _HEARTBEAT_LINE * 2
)


def make_fake_server(tmp: Path, port: int = 30199) -> dict:
    data_dir = tmp / "txData" / "base"
    (data_dir / "resources" / "[local]").mkdir(parents=True)
    logs_dir = tmp / "txData" / "logs"
    logs_dir.mkdir(parents=True)

    cfg_path = data_dir / "server.cfg"
    cfg_path.write_text(SERVER_CFG_TEMPLATE.format(port=port, key=FAKE_LICENSE_KEY), encoding="utf-8")

    log_path = logs_dir / "fxserver.log"
    log_path.write_text(LOG_FIXTURE, encoding="utf-8")

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
            "rcon": {"host": "127.0.0.1", "port": 30201, "password_env": "FXRCON_PASSWORD_TESTONLY"},
        },
        "project": {"workspace": str(tmp), "language": "lua", "lua54": True, "framework": "standalone",
                     "ox_lib": False, "game": "gta5", "author": "test"},
    }), encoding="utf-8")

    return {"root": tmp, "data_dir": data_dir, "cfg_path": cfg_path, "log_path": log_path, "config_path": config_path}


def run_fxserver(args, config_path: Path, env_extra: dict = None):
    env = dict(os.environ)
    env["FXKIT_CONFIG"] = str(config_path)
    env.pop("FXRCON_PASSWORD_TESTONLY", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, str(FXSERVER), *args], capture_output=True, text=True, env=env)


def make_fake_resource(tmp: Path, name: str = "myresource", with_manifest: bool = True) -> Path:
    d = tmp / "resources" / name
    d.mkdir(parents=True)
    if with_manifest:
        (d / "fxmanifest.lua").write_text("fx_version 'cerulean'\ngame 'gta5'\n", encoding="utf-8")
    return d


# ---------------------------------------------------------------------------

def test_deploy_creates_symlink_and_ensure_line():
    tmp = Path(tempfile.mkdtemp(prefix="fxserver-deploy-"))
    try:
        fake = make_fake_server(tmp)
        resource = make_fake_resource(tmp)
        original_cfg = fake["cfg_path"].read_text(encoding="utf-8")

        proc = run_fxserver(["deploy", str(resource)], fake["config_path"])
        check("deploy: exits 0", proc.returncode == 0, proc.stdout + proc.stderr)

        link = fake["data_dir"] / "resources" / "[local]" / "myresource"
        check("deploy: symlink created", link.is_symlink())
        check("deploy: symlink points at the resource dir", Path(os.readlink(link)) == resource.resolve())

        new_cfg = fake["cfg_path"].read_text(encoding="utf-8")
        check("deploy: server.cfg gained exactly one new line (the ensure line)",
              new_cfg.count("\n") == original_cfg.count("\n") + 1,
              f"before={original_cfg.count(chr(10))} after={new_cfg.count(chr(10))}")
        check("deploy: 'ensure myresource' was added", "ensure myresource" in new_cfg)
        check("deploy: it was added after the last existing ensure line",
              new_cfg.index("ensure myresource") > new_cfg.rindex("ensure chat"))
        check("deploy: every other line is untouched",
              new_cfg.replace("ensure myresource\n", "") == original_cfg)

        bak = fake["cfg_path"].with_name("server.cfg.fxkit.bak")
        check("deploy: server.cfg.fxkit.bak was created", bak.exists())
        check("deploy: the backup matches the pre-deploy server.cfg exactly", bak.read_text(encoding="utf-8") == original_cfg)

        check("deploy: never prints server.cfg's contents (no license key on stdout)",
              FAKE_LICENSE_KEY not in proc.stdout and FAKE_LICENSE_KEY not in proc.stderr)
        check("deploy: does print what it did", "ensure myresource" in proc.stdout or "myresource" in proc.stdout)

        # second deploy: idempotent, no second backup, no duplicate ensure line
        proc2 = run_fxserver(["deploy", str(resource)], fake["config_path"])
        check("deploy (again): exits 0", proc2.returncode == 0, proc2.stdout + proc2.stderr)
        cfg_after_second = fake["cfg_path"].read_text(encoding="utf-8")
        check("deploy (again): server.cfg unchanged", cfg_after_second == new_cfg)
        bak_mtime_1 = bak.stat().st_mtime_ns
        check("deploy (again): backup file not re-created/overwritten", bak.stat().st_mtime_ns == bak_mtime_1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_deploy_refuses_non_resource_dir():
    tmp = Path(tempfile.mkdtemp(prefix="fxserver-refuse-"))
    try:
        fake = make_fake_server(tmp)
        not_a_resource = tmp / "resources" / "not-a-resource"
        not_a_resource.mkdir(parents=True)
        (not_a_resource / "readme.txt").write_text("nothing here", encoding="utf-8")

        proc = run_fxserver(["deploy", str(not_a_resource)], fake["config_path"])
        check("deploy: refuses a directory with no fxmanifest.lua", proc.returncode != 0)
        check("deploy: explains why", "fxmanifest" in proc.stderr.lower())
        link = fake["data_dir"] / "resources" / "[local]" / "not-a-resource"
        check("deploy: no symlink created for the refused directory", not link.exists())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_deploy_relinks_but_never_deletes_a_real_directory():
    tmp = Path(tempfile.mkdtemp(prefix="fxserver-relink-"))
    try:
        fake = make_fake_server(tmp)
        resource_a = make_fake_resource(tmp, "moved")
        local = fake["data_dir"] / "resources" / "[local]"

        # a real (non-symlink) directory already occupying the target name must never be deleted
        real_dir = local / "moved"
        real_dir.mkdir(parents=True)
        (real_dir / "keepme.txt").write_text("do not delete", encoding="utf-8")
        proc = run_fxserver(["deploy", str(resource_a)], fake["config_path"])
        check("deploy: refuses to replace a real directory with a symlink", proc.returncode != 0)
        check("deploy: the real directory and its contents survive", (real_dir / "keepme.txt").exists())
        shutil.rmtree(real_dir)

        # a symlink pointing elsewhere gets relinked, not left stale
        elsewhere = tmp / "elsewhere"
        elsewhere.mkdir()
        (local / "moved").symlink_to(elsewhere, target_is_directory=True)
        proc2 = run_fxserver(["deploy", str(resource_a)], fake["config_path"])
        check("deploy: re-links a symlink that pointed elsewhere", proc2.returncode == 0, proc2.stdout + proc2.stderr)
        check("deploy: the symlink now points at the new resource",
              Path(os.readlink(local / "moved")) == resource_a.resolve())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_undeploy_and_list():
    tmp = Path(tempfile.mkdtemp(prefix="fxserver-undeploy-"))
    try:
        fake = make_fake_server(tmp)
        resource = make_fake_resource(tmp)
        run_fxserver(["deploy", str(resource)], fake["config_path"])

        listed = run_fxserver(["list", "--json"], fake["config_path"])
        items = json.loads(listed.stdout)
        check("list: shows the deployed resource", any(it["name"] == "myresource" for it in items), items)

        proc = run_fxserver(["undeploy", "myresource"], fake["config_path"])
        check("undeploy: exits 0", proc.returncode == 0, proc.stdout + proc.stderr)
        link = fake["data_dir"] / "resources" / "[local]" / "myresource"
        check("undeploy: symlink removed", not link.exists())

        cfg_text = fake["cfg_path"].read_text(encoding="utf-8")
        check("undeploy: leaves the ensure line in server.cfg alone", "ensure myresource" in cfg_text)

        listed2 = run_fxserver(["list", "--json"], fake["config_path"])
        items2 = json.loads(listed2.stdout)
        check("list (after undeploy): resource no longer listed", not any(it["name"] == "myresource" for it in items2), items2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_logs_filtering():
    tmp = Path(tempfile.mkdtemp(prefix="fxserver-logs-"))
    try:
        fake = make_fake_server(tmp)

        proc = run_fxserver(["logs", "--json", "--tail", "100"], fake["config_path"])
        data = json.loads(proc.stdout)
        lines = data["lines"]
        check("logs: ANSI escape codes stripped", not any("\x1b" in l for l in lines), lines)
        check("logs: txAdmin banner lines (║) dropped", not any("║" in l for l in lines), lines)
        check("logs: ordinary lines survive", any("Started resource mapmanager" in l for l in lines), lines)

        errs = json.loads(run_fxserver(["logs", "--json", "--errors"], fake["config_path"]).stdout)["lines"]
        check("logs --errors: keeps the SCRIPT ERROR line", any("SCRIPT ERROR" in l for l in errs), errs)
        check("logs --errors: keeps the stack traceback line", any("stack traceback" in l for l in errs), errs)
        check("logs --errors: drops the unrelated info line", not any("unrelated info line" in l for l in errs), errs)

        by_resource = json.loads(run_fxserver(["logs", "--json", "--resource", "myresource"], fake["config_path"]).stdout)["lines"]
        check("logs --resource: keeps only lines mentioning that resource",
              len(by_resource) >= 2 and all("myresource" in l for l in by_resource), by_resource)
        check("logs --resource: excludes the unrelated resource line",
              not any("mapmanager" in l for l in by_resource), by_resource)

        tailed = json.loads(run_fxserver(["logs", "--json", "--tail", "2"], fake["config_path"]).stdout)["lines"]
        check("logs --tail 2: returns exactly 2 lines", len(tailed) == 2, tailed)

        no_ts = json.loads(run_fxserver(["logs", "--json", "--since", "5"], fake["config_path"]).stdout)
        check("logs --since on a log with no timestamps: ignored with a note, doesn't crash",
              any("ignored" in n for n in no_ts["notes"]), no_ts["notes"])
        check("logs --since (no timestamps): still returns the log's lines", len(no_ts["lines"]) > 0)

        fake["log_path"].write_text(LOG_FIXTURE_WITH_TIMESTAMPS, encoding="utf-8")
        recent = json.loads(run_fxserver(["logs", "--json", "--since", "5", "--tail", "100"], fake["config_path"]).stdout)
        check("logs --since on a log WITH timestamps: old line dropped",
              not any("this line is ancient" in l for l in recent["lines"]), recent["lines"])
        check("logs --since on a log WITH timestamps: recent (future, for this fixture) line kept",
              any("this line is from the future" in l for l in recent["lines"]), recent["lines"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_logs_errors_excludes_heartbeat_noise_and_dedupes():
    """Real fxserver.log is mostly Cfx server-list heartbeat noise ("Server
    list query returned an error ... info.json/dynamic.json ... context
    deadline exceeded"). --errors should surface the one real script error,
    not three pages of that -- and repeated lines should collapse."""
    tmp = Path(tempfile.mkdtemp(prefix="fxserver-heartbeat-"))
    try:
        fake = make_fake_server(tmp)
        fake["log_path"].write_text(LOG_FIXTURE_WITH_HEARTBEAT_NOISE, encoding="utf-8")

        default = json.loads(run_fxserver(["logs", "--json", "--errors", "--tail", "100"], fake["config_path"]).stdout)
        lines = default["lines"]
        check("logs --errors (default): heartbeat noise is excluded",
              not any("Server list query returned an error" in l for l in lines), lines)
        check("logs --errors (default): the real SCRIPT ERROR survives", any("SCRIPT ERROR" in l for l in lines), lines)
        check("logs --errors (default): the stack traceback line survives", any("stack traceback" in l for l in lines), lines)
        check("logs --errors (default): only the two real script lines remain", len(lines) == 2, lines)

        all_errs = json.loads(
            run_fxserver(["logs", "--json", "--errors", "--all-errors", "--tail", "100", "--no-dedupe"], fake["config_path"]).stdout
        )["lines"]
        check("logs --errors --all-errors: heartbeat noise is included",
              any("Server list query returned an error" in l for l in all_errs), all_errs)
        check("logs --errors --all-errors --no-dedupe: all 5 heartbeat occurrences present individually",
              sum("Server list query returned an error" in l for l in all_errs) == 5, all_errs)

        deduped = json.loads(
            run_fxserver(["logs", "--json", "--errors", "--all-errors", "--tail", "100"], fake["config_path"]).stdout
        )["lines"]
        check("logs --errors --all-errors (dedupe on by default): consecutive noise collapses to one '(x3)' line",
              any(l.endswith("(x3)") and "Server list query returned an error" in l for l in deduped), deduped)
        check("logs --errors --all-errors (dedupe on by default): the later run of 2 collapses to '(x2)'",
              any(l.endswith("(x2)") and "Server list query returned an error" in l for l in deduped), deduped)
        check("logs --errors --all-errors (dedupe on): total line count shrinks (5 noise -> 2 groups + 2 script lines)",
              len(deduped) == 4, deduped)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_status_reports_port_and_txadmin():
    tmp = Path(tempfile.mkdtemp(prefix="fxserver-status-"))
    try:
        fake = make_fake_server(tmp, port=30199)
        proc = run_fxserver(["status", "--json"], fake["config_path"])
        check("status: exits 0", proc.returncode == 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        check("status: reads the endpoint port from server.cfg", data["port"] == 30199, data)
        check("status: 'running' is a bool", isinstance(data["running"], bool), data)
        check("status: detects the monitor/txAdmin line in the log", data["txadmin"] is True, data)
        check("status: never prints server.cfg's contents", FAKE_LICENSE_KEY not in proc.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_rcon_missing_password_is_explained():
    tmp = Path(tempfile.mkdtemp(prefix="fxserver-rcon-nopass-"))
    try:
        fake = make_fake_server(tmp)
        proc = run_fxserver(["rcon", "status"], fake["config_path"])
        check("rcon without a password fails", proc.returncode != 0)
        check("rcon without a password explains how to set rcon_password",
              "rcon_password" in proc.stderr and "FXRCON_PASSWORD_TESTONLY" in proc.stderr, proc.stderr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_rcon_packet_builder_no_network():
    """Per the task spec: only the packet builder/parser are tested here, no
    actual socket traffic (verified separately against the real FiveM source
    -- see docs/fxserver.md)."""
    from fxkit import server as srv

    packet = srv.build_rcon_packet("hunter2", "status")
    check("rcon packet: starts with the 4-byte 0xFFFFFFFF OOB prefix", packet.startswith(b"\xff\xff\xff\xff"))
    check("rcon packet: 'rcon <password> <command>' after the prefix",
          packet[4:] == b"rcon hunter2 status", packet)

    ok_response = b"\xff\xff\xff\xffprint hello world\n"
    check("rcon response parsing: strips the OOB prefix and 'print ' marker",
          srv.parse_rcon_response(ok_response) == "hello world\n")

    no_password_response = b"\xff\xff\xff\xffprint The server must set rcon_password to be able to use this command.\n"
    check("rcon response parsing: the 'must set rcon_password' server response comes through readably",
          "rcon_password" in srv.parse_rcon_response(no_password_response))

    multi_word = srv.build_rcon_packet("p", "say hello there general kenobi")
    check("rcon packet: multi-word commands stay space-joined, not re-escaped",
          multi_word == b"\xff\xff\xff\xffrcon p say hello there general kenobi")


def test_never_prints_cfg_on_any_command():
    tmp = Path(tempfile.mkdtemp(prefix="fxserver-secrecy-"))
    try:
        fake = make_fake_server(tmp)
        resource = make_fake_resource(tmp)
        run_fxserver(["deploy", str(resource)], fake["config_path"])
        for args in (["status"], ["status", "--json"], ["list"], ["list", "--json"],
                     ["logs"], ["undeploy", "myresource"]):
            proc = run_fxserver(args, fake["config_path"])
            check(f"'fxserver {' '.join(args)}' never leaks the license key",
                  FAKE_LICENSE_KEY not in proc.stdout and FAKE_LICENSE_KEY not in proc.stderr,
                  f"stdout={proc.stdout!r}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    test_deploy_creates_symlink_and_ensure_line()
    test_deploy_refuses_non_resource_dir()
    test_deploy_relinks_but_never_deletes_a_real_directory()
    test_undeploy_and_list()
    test_logs_filtering()
    test_logs_errors_excludes_heartbeat_noise_and_dedupes()
    test_status_reports_port_and_txadmin()
    test_rcon_missing_password_is_explained()
    test_rcon_packet_builder_no_network()
    test_never_prints_cfg_on_any_command()

    print(f"\n{_pass} passed, {_fail} failed")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
