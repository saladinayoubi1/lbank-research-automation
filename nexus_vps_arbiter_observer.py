"""NEXUS VPS read-only preflight observer: NEVER issues Paper writer permits."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time

SCHEMA = "nexus.vps-arbiter-observer.v1"
DANGER = re.compile(r"soft\s+lockup|rcu.{0,80}stall|blocked\s+for\s+more\s+than|(?:buffer\s+)?i/o\s+error|ext4-fs\s+error|xfs.*corrupt", re.I)


def _run(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=10)
    if p.returncode:
        raise RuntimeError(f"{args[0]} exited {p.returncode}")
    return p.stdout


def _ssh_probe():
    """Read-only local handshake rather than systemd D-Bus from a DynamicUser."""
    with socket.create_connection(("127.0.0.1", 22), timeout=3) as stream:
        stream.settimeout(3)
        banner = stream.recv(80)
    return banner.startswith(b"SSH-"), "localhost_ssh_banner_valid=" + str(banner.startswith(b"SSH-"))


def _ntp_probe():
    """systemd-timesyncd creates this per-boot marker after a successful sync."""
    marker = Path("/run/systemd/timesync/synchronized")
    age = time.time() - marker.stat().st_mtime
    return 0 <= age <= 24 * 3600, f"last_sync_age_seconds={int(age)}"


def inspect(*, run=_run, mem_path=Path("/proc/meminfo"), disk_path="/",
            ssh_probe=_ssh_probe, ntp_probe=_ntp_probe):
    checks = {}
    def test(name, action):
        try:
            ok, detail = action()
            checks[name] = {"ok": bool(ok), "detail": str(detail)[:240]}
        except Exception as exc:
            checks[name] = {"ok": False, "detail": type(exc).__name__}

    test("cpu", lambda: (os.cpu_count() is not None and os.cpu_count() >= 2, str(os.cpu_count())))
    def memory():
        m = re.search(r"^MemTotal:\s+(\d+)\s+kB$", mem_path.read_text(), re.M)
        if m is None:
            raise ValueError("MemTotal missing")
        n = int(m[1]) * 1024
        return n >= 2 * 1024**3, str(n)
    test("memory", memory)
    def disk():
        d = shutil.disk_usage(disk_path)
        return d.total >= 20 * 1024**3 and d.free >= 5 * 1024**3, f"total={d.total},free={d.free}"
    test("disk", disk)
    def uptime():
        secs = float(Path("/proc/uptime").read_text().split()[0])
        return secs >= 60, str(int(secs))
    test("uptime", uptime)
    test("ssh", ssh_probe)
    test("ntp", ntp_probe)
    def kernel():
        log = run(["journalctl","-k","-b","--no-pager","--output=cat"])
        matches = [x for x in log.splitlines() if DANGER.search(x)]
        return not matches, f"danger_matches={len(matches)}" + (f";first={matches[0][:150]}" if matches else "")
    test("kernel", kernel)
    return {
        "schema": SCHEMA,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "host_preflight": "pass" if all(c["ok"] for c in checks.values()) else "hold",
        "checks": checks,
        "writer_authority": "DISABLED",
        "paper_writer_grants_enabled": False,
        "external_fencing_verified": False,
        "live_trading_authority": False,
    }


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, obj):
        data=json.dumps(obj,sort_keys=True).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/healthz":
            data = inspect()
            self.reply(200 if data["host_preflight"] == "pass" else 503, data)
        elif self.path in ("/readyz", "/permit", "/writer-permit"):
            self.reply(503, {"status":"HOLD","paper_writer_grants_enabled":False,"live_trading_authority":False})
        else:
            self.reply(404, {"error":"not found"})

    def do_POST(self):
        self.reply(403, {"error":"observer cannot issue authority","paper_writer_grants_enabled":False,"live_trading_authority":False})
    do_PUT=do_POST
    do_DELETE=do_POST

    def log_message(self, *args):
        pass


def main(argv=None):
    p=argparse.ArgumentParser()
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once",action="store_true")
    mode.add_argument("--serve",action="store_true")
    p.add_argument("--host",default="127.0.0.1")
    p.add_argument("--port",type=int,default=8765)
    args=p.parse_args(argv)
    try:
        ip=ipaddress.ip_address(args.host)
    except ValueError:
        p.error("host must be literal loopback IP")
    if not ip.is_loopback:
        p.error("non-loopback bind prohibited")
    if args.port < 0 or args.port > 65535:
        p.error("invalid port")
    if args.once:
        report=inspect()
        print(json.dumps(report,indent=2,sort_keys=True))
        return 0 if report["host_preflight"] == "pass" else 2
    if ip.version != 4:
        p.error("IPv4 loopback only")
    with ThreadingHTTPServer((args.host,args.port),Handler) as server:
        server.daemon_threads=True
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
