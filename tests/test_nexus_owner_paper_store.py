"""Physical WSL owner Paper store: synthetic non-trading security/integrity tests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/nexus_owner_paper_store.py"
SHA_A = "a" * 40
SHA_B = "b" * 40
pytestmark = []


@unittest.skipUnless(sys.platform == "linux", "owner state store is WSL/Linux-only")
class OwnerPaperStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / "owner-store"
        self.state = self.root / "isolated-state"
        self.state.mkdir()
        self.event_bytes = os.urandom(640_000)
        self.paper_json = {
            "paper_only": True,
            "live_trading_authority": False,
            "private_credentials_used": False,
            "real_exchange_orders": False,
            "automatic_strategy_promotion": False,
            "state_isolated_from_issue_984": True,
        }
        self.populate()

    def populate(self):
        p = self.state / "demo" / "persistent-paper-trading-loop.json"
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(self.paper_json), encoding="utf-8")
        p = self.state / "cells" / "btcusdt" / "hour4" / "events.bin"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(self.event_bytes)

    def cmd(self, action, *extra, state=None, expect=0):
        process = subprocess.run(
            [sys.executable, str(SCRIPT), action,
             "--store-root", str(self.store),
             *([] if (state is None and action == "status") else
               ["--state-root", str(state or self.state)]),
             *extra],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(process.returncode, expect, process.stderr + "\n" + process.stdout)
        return process

    def commit(self, n="100", sha=SHA_A, previous="none", state=None, expect=0):
        return self.cmd("commit", "--run-id", n, "--source-sha", sha,
                        "--expected-previous", previous, state=state, expect=expect)

    def read_receipt(self):
        return json.loads((self.store / "current.json").read_text())

    def test_large_state_roundtrip_immutable_generations_and_compare_and_swap(self):
        self.cmd("restore", state=self.root / "initial", expect=3)
        self.commit()
        one = self.read_receipt()
        self.assertGreater(one["archive_bytes"], 390_016)
        self.assertEqual(one["file_count"], 2)
        self.assertTrue((self.store / "snapshots" / one["generation"] / "paper-state.tar.xz").is_file())
        restored = self.root / "recovered"
        self.cmd("restore", state=restored)
        self.assertEqual((restored / "cells" / "btcusdt" / "hour4" / "events.bin").read_bytes(),
                         self.event_bytes)
        self.assertEqual(json.loads((restored / "demo" / "persistent-paper-trading-loop.json").read_text()),
                         self.paper_json)
        self.commit(n="101", sha=SHA_B, previous=one["generation"], state=restored)
        two = self.read_receipt()
        self.assertEqual(two["previous_archive_sha256"], one["archive_sha256"])
        self.assertTrue((self.store / "snapshots" / one["generation"] / "paper-state.tar.xz").exists())
        self.assertEqual(len(list((self.store / "snapshots").iterdir())), 2)
        self.commit(n="102", sha=SHA_B, previous=one["generation"], expect=1)
        self.assertEqual(self.read_receipt(), two)

    def test_large_realistic_state_tree_restores_all_members_without_job_outputs(self):
        for index in range(1_600):
            p = self.state / "regime_runtime_evidence" / f"event-{index:04d}.bin"
            p.parent.mkdir(exist_ok=True)
            p.write_bytes(index.to_bytes(4, "little") * 18)
        self.commit()
        receipt = self.read_receipt()
        self.assertEqual(receipt["file_count"], 1_602)
        restored = self.root / "many-files-restored"
        self.cmd("restore", state=restored)
        self.assertEqual(
            len(list((restored / "regime_runtime_evidence").iterdir())), 1_600
        )
        self.assertEqual(
            (restored / "cells/btcusdt/hour4/events.bin").read_bytes(), self.event_bytes
        )

    def test_tamper_archive_refuses_restore_and_preserves_previous(self):
        self.commit()
        receipt = self.read_receipt()
        archive = self.store / "snapshots" / receipt["generation"] / "paper-state.tar.xz"
        with archive.open("r+b") as out:
            out.seek(64)
            out.write(b"bad integrity data")
        restore = self.root / "blocked"
        self.cmd("restore", state=restore, expect=1)
        self.assertFalse(restore.exists())
        self.cmd("status", expect=1)
        self.assertTrue((self.store / "current.json").exists())

    def test_reject_partial_store_never_falls_back_to_fresh_state(self):
        (self.store / "snapshots" / "orphaned").mkdir(parents=True)
        self.cmd("restore", state=self.root / "blocked", expect=1)

    def test_reject_live_authority_and_unexpected_new_runtime_surface(self):
        self.paper_json["live_trading_authority"] = True
        self.populate()
        self.commit(expect=1)
        self.assertFalse((self.store / "current.json").exists())
        self.paper_json["live_trading_authority"] = False
        self.populate()
        (self.state / "unknown-new-runtime-state.json").write_text("{}")
        self.commit(expect=1)
        self.assertFalse((self.store / "current.json").exists())

    def test_signed_artifact_headers_excluded_from_checkpoint(self):
        (self.state / "source-artifact-redirect.headers").write_text("private signed URL not for archive")
        (self.state / "source-run-metadata.json").write_text('{"metadata":true}')
        self.commit()
        receipt = self.read_receipt()
        archive = self.store / "snapshots" / receipt["generation"] / "paper-state.tar.xz"
        with tarfile.open(archive, "r:xz") as handle:
            self.assertEqual(len(handle.getmembers()), 2)
            self.assertTrue(all("source" not in m.name for m in handle))

    def test_never_follow_symlink_inside_runtime_or_protected_store(self):
        outside = self.root / "external"
        outside.write_bytes(b"do not read or overwrite")
        (self.state / "cells" / "secret").symlink_to(outside)
        self.commit(expect=1)
        self.assertEqual(outside.read_bytes(), b"do not read or overwrite")
        (self.state / "cells" / "secret").unlink()
        self.commit()
        receipt = self.read_receipt()
        (self.store / "current.json").unlink()
        (self.store / "current.json").symlink_to(outside)
        self.cmd("status", expect=1)
        self.assertEqual(outside.read_bytes(), b"do not read or overwrite")
        self.assertEqual(receipt["run_id"], "100")

    def test_corrupt_manifest_never_promotes_as_current(self):
        self.commit()
        current = self.store / "current.json"
        value = json.loads(current.read_text())
        value["archive_sha256"] = "f" * 64
        current.write_text(json.dumps(value))
        self.cmd("restore", state=self.root / "blocked", expect=1)

    def test_restore_rejects_nonempty_destination(self):
        self.commit()
        target = self.root / "occupied"
        target.mkdir()
        (target / "journal.json").write_text("do not delete")
        self.cmd("restore", state=target, expect=1)
        self.assertEqual((target / "journal.json").read_text(), "do not delete")

    def test_missing_owner_volume_is_not_silently_accepted(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "volume-check",
            "--store-root", str(self.root / "not-e")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.root / "not-e").exists())


if __name__ == "__main__":
    unittest.main()
