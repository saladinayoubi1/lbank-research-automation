"""Synthetic only; no market data, credentials, or order access."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from nexus_fx_research_batch import ResearchJob, VerifiedReceipt, run_research_batch


def sample(name, config=None):
    scenario = name if config is None else config
    return ResearchJob(name, "a" * 64, "b" * 64,
                       hashlib.sha256(scenario.encode("utf-8")).hexdigest())


def verified_worker(job, root):
    path = Path(root) / (job.job_id + ".json")
    payload = json.dumps({"test": job.job_id, "fingerprint": job.fingerprint},
                         sort_keys=True).encode("utf-8")
    path.write_bytes(payload)
    return VerifiedReceipt(job.job_id, job.fingerprint, hashlib.sha256(payload).hexdigest())


def isolated_failure_worker(job, root):
    if job.job_id == "fail":
        raise RuntimeError("synthetic failure")
    return verified_worker(job, root)


class BoundedBatchTests(unittest.TestCase):
    def test_two_workers_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            jobs = [sample("first"), sample("second")]
            r = run_research_batch(jobs, verified_worker, output_root=folder,
                                   max_workers=2, memory_probe=lambda: 2048)
            self.assertEqual(sorted(r["verified"]), ["first", "second"])
            self.assertFalse(r["failed"] or r["blocked_memory"])
            r2 = run_research_batch(jobs, verified_worker, output_root=folder,
                                    memory_probe=lambda: 2048)
            self.assertEqual(sorted(r2["skipped"]), ["first", "second"])
            self.assertFalse(r2["verified"])

    def test_failure_does_not_block_other_job(self):
        with tempfile.TemporaryDirectory() as folder:
            r = run_research_batch([sample("fail"), sample("ok")],
                                   isolated_failure_worker, output_root=folder,
                                   memory_probe=lambda: 2048)
            self.assertEqual(r["verified"], ["ok"])
            self.assertEqual(r["failed"], [{"job_id": "fail", "type": "RuntimeError"}])
            self.assertFalse(r["blocked_memory"])

    def test_memory_guard_blocks_before_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            r = run_research_batch([sample("idle")], verified_worker,
                                   output_root=folder, memory_probe=lambda: 400)
            self.assertEqual(r["blocked_memory"], ["idle"])
            self.assertFalse((Path(folder) / "idle.json").exists())

    def test_corrupt_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            job = sample("original")
            run_research_batch([job], verified_worker, output_root=folder,
                               memory_probe=lambda: 2048)
            (Path(folder) / "original.json").write_text("tampered", encoding="utf-8")
            with self.assertRaises(ValueError):
                run_research_batch([job], verified_worker, output_root=folder,
                                   memory_probe=lambda: 2048)

    def test_changed_config_does_not_reuse_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            run_research_batch([sample("one")], verified_worker, output_root=folder,
                               memory_probe=lambda: 2048)
            with self.assertRaises(ValueError):
                run_research_batch([sample("one", "d")], verified_worker,
                                   output_root=folder, memory_probe=lambda: 2048)

    def test_duplicate_and_invalid_jobs_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                run_research_batch([sample("one"), sample("one")], verified_worker,
                                   output_root=folder)
            with self.assertRaises(ValueError):
                run_research_batch([sample("one"), sample("ONE")], verified_worker,
                                   output_root=folder)
            with self.assertRaises(ValueError):
                run_research_batch([sample("one", "same"), sample("two", "same")],
                                   verified_worker, output_root=folder)
            with self.assertRaises(ValueError):
                run_research_batch([sample("one")], verified_worker,
                                   output_root=folder, max_workers=3)
            with self.assertRaises(ValueError):
                ResearchJob("../unsafe", "a" * 64, "b" * 64, "c" * 64)

    def test_orphan_artifact_blocks_reexecution(self):
        with tempfile.TemporaryDirectory() as folder:
            job = sample("orphan")
            (Path(folder) / "orphan.json").write_text("partial", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unreceipted artifact"):
                run_research_batch([job], verified_worker,
                                   output_root=folder, memory_probe=lambda: 2048)
            self.assertFalse((Path(folder) / ".receipts" / "orphan.json").exists())

    def test_output_root_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "actual"
            target.mkdir()
            alias = Path(folder) / "linked"
            try:
                alias.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(ValueError, "symlink output"):
                run_research_batch([sample("linked")], verified_worker,
                                   output_root=alias, memory_probe=lambda: 2048)
            self.assertFalse((target / "linked.json").exists())

    def test_dangling_receipt_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            receipts = Path(folder) / ".receipts"
            receipts.mkdir()
            path = receipts / "one.json"
            try:
                path.symlink_to(receipts / "missing.json")
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(ValueError, "unsafe checkpoint"):
                run_research_batch([sample("one")], verified_worker,
                                   output_root=folder, memory_probe=lambda: 2048)

    def test_active_lease_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / ".fx-research-batch.lock"
            lock.write_text("other process", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                run_research_batch([sample("one")], verified_worker,
                                   output_root=folder, memory_probe=lambda: 2048)
            self.assertEqual(lock.read_text(encoding="utf-8"), "other process")


if __name__ == "__main__":
    unittest.main()
