"""Safety contracts for the VPS observer; no real writer grants."""
import json
from pathlib import Path
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import subprocess
import sys

import nexus_vps_arbiter_observer as module


def good(command):
    if command[0] == "systemctl":
        return "active\n"
    if command[0] == "timedatectl":
        return "yes\n"
    if command[0] == "journalctl":
        return "Linux version 6.8.0\n"
    raise AssertionError(command)


def inspect_with(fake_run=good, ssh_status=(True, "local SSH banner"), ntp_status=(True, "per-boot sync")):
    def fake_file(self, *args, **kwargs):
        if str(self) == "/proc/uptime":
            return "450.4 900.1\n"
        return "MemTotal:    3932160 kB\n"
    with patch.object(module.os, "cpu_count", return_value=2), \
         patch.object(module.shutil, "disk_usage",
                      return_value=SimpleNamespace(total=40*1024**3, free=35*1024**3)), \
         patch.object(Path, "read_text", fake_file):
        return module.inspect(run=fake_run, ssh_probe=lambda: ssh_status, ntp_probe=lambda: ntp_status)


class TestObserver(TestCase):
    def test_good_host_still_has_no_writer_authority(self):
        data = inspect_with()
        self.assertEqual("pass", data["host_preflight"])
        self.assertEqual("DISABLED", data["writer_authority"])
        self.assertFalse(data["paper_writer_grants_enabled"])
        self.assertFalse(data["external_fencing_verified"])
        self.assertFalse(data["live_trading_authority"])

    def test_all_kernel_risks_force_hold(self):
        faults = ["BUG: soft lockup CPU#1", "rcu_preempt detected stalls",
                  "task blocked for more than 136 seconds",
                  "Buffer I/O error on dev vda", "EXT4-fs error",
                  "XFS corruption detected"]
        for msg in faults:
            with self.subTest(msg=msg):
                def run(command):
                    if command[0] == "journalctl":
                        return "Linux started\n" + msg
                    return good(command)
                data = inspect_with(run)
                self.assertEqual("hold", data["host_preflight"])
                self.assertFalse(data["checks"]["kernel"]["ok"])
                self.assertFalse(data["paper_writer_grants_enabled"])

    def test_unreadable_kernel_journal_denies_preflight(self):
        def bad(command):
            if command[0] == "journalctl":
                raise PermissionError("journal unavailable")
            return good(command)
        data=inspect_with(bad)
        self.assertEqual("hold", data["host_preflight"])
        self.assertEqual("PermissionError", data["checks"]["kernel"]["detail"])

    def test_no_ssh_or_ntp_denies_preflight(self):
        data=inspect_with(ssh_status=(False, "ssh offline"), ntp_status=(False, "ntp stale"))
        self.assertEqual("hold", data["host_preflight"])
        self.assertFalse(data["checks"]["ssh"]["ok"])
        self.assertFalse(data["checks"]["ntp"]["ok"])

    def test_bind_must_be_loopback(self):
        proc=subprocess.run(
            [sys.executable, str(Path(module.__file__)), "--serve",
             "--host", "0.0.0.0", "--port", "0"],
            capture_output=True, text=True, timeout=5,
        )
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("non-loopback", proc.stderr)

    def test_read_only_http_always_refuses_permits(self):
        server = ThreadingHTTPServer(("127.0.0.1",0), module.Handler)
        thread=Thread(target=server.serve_forever,daemon=True)
        try:
            thread.start()
            for method,path,status in [
                ("GET","/healthz",200),
                ("GET","/readyz",503),
                ("GET","/permit",503),
                ("POST","/permit",403),
                ("PUT","/healthz",403),
                ("DELETE","/writer-permit",403),
            ]:
                with self.subTest(method=method,path=path):
                    with patch.object(module,"inspect",return_value=inspect_with()):
                        con=HTTPConnection("127.0.0.1",server.server_port,timeout=3)
                        con.request(method,path,body=b"{}" if method!="GET" else None)
                        resp=con.getresponse()
                        body=json.loads(resp.read())
                        self.assertEqual(status,resp.status)
                        self.assertFalse(body["paper_writer_grants_enabled"])
                        self.assertFalse(body["live_trading_authority"])
                        con.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
