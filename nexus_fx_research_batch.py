"""Optional bounded, local-only FX research batch executor.

Not a scheduler, data fetcher, trading adapter or Paper writer. Workers are
explicit caller-supplied top-level Python callables and run in separate
processes. Every accepted result is bound to one job fingerprint and an
existing, content-hashed private artifact. No retry or auto-promotion.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import ctypes
import json
import os
import re


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _digest_file(path):
    h = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class ResearchJob:
    job_id: str
    source_sha256: str
    code_sha256: str
    config_sha256: str

    def __post_init__(self):
        if not isinstance(self.job_id, str) or not _ID.fullmatch(self.job_id):
            raise ValueError("invalid private research job ID")
        for name in ("source_sha256", "code_sha256", "config_sha256"):
            if not isinstance(getattr(self, name), str) or not _SHA.fullmatch(getattr(self, name)):
                raise ValueError("missing or invalid " + name)

    @property
    def fingerprint(self):
        data = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return sha256(data.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VerifiedReceipt:
    job_id: str
    fingerprint: str
    artifact_sha256: str


def _available_memory_mib():
    if os.name == "nt":
        from ctypes import wintypes

        class Status(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "total", "available", "page_total", "page_avail",
                    "virtual_total", "virtual_avail", "extended"
                )
            ]

        value = Status()
        value.length = ctypes.sizeof(value)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            raise RuntimeError("free memory unavailable")
        return value.available // 1048576
    path = Path("/proc/meminfo")
    if path.is_file():
        for line in path.read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    raise RuntimeError("free physical memory unavailable")


def _validate_receipt(receipt, job, root):
    if type(receipt) is not VerifiedReceipt:
        raise ValueError("worker did not provide a verified receipt")
    if receipt.job_id != job.job_id or receipt.fingerprint != job.fingerprint:
        raise ValueError("receipt/job binding mismatch")
    if type(receipt.artifact_sha256) is not str or not _SHA.fullmatch(receipt.artifact_sha256):
        raise ValueError("invalid artifact digest")
    artifact = root / (job.job_id + ".json")
    if artifact.is_symlink() or not artifact.is_file() or artifact.resolve().parent != root:
        raise ValueError("private result artifact unavailable")
    if _digest_file(artifact) != receipt.artifact_sha256:
        raise ValueError("artifact/receipt content mismatch")
    return receipt


def run_research_batch(jobs, worker, *, output_root, max_workers=2,
                       min_free_mib=512, memory_probe=None):
    """Run disjoint jobs, verify outputs and persist small resumable receipts.

    No implicit retries. Other jobs continue after an individual worker failure.
    Locked output root rejects a second simultaneous dispatcher; an orphan lock
    requires operator investigation, never automatic forced deletion.
    """
    if type(max_workers) is not int or max_workers not in (1, 2):
        raise ValueError("only measured one/two-worker research concurrency allowed")
    if type(min_free_mib) is not int or not 512 <= min_free_mib <= 32768:
        raise ValueError("invalid memory safety threshold")
    if not callable(worker):
        raise ValueError("explicit worker callable required")
    tasks = tuple(jobs)
    if not 1 <= len(tasks) <= 64 or any(type(t) is not ResearchJob for t in tasks):
        raise ValueError("bounded validated job list required")
    ids = [t.job_id.casefold() for t in tasks]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate research job key (case-insensitive filesystem)")
    inputs = [(t.source_sha256, t.code_sha256, t.config_sha256) for t in tasks]
    if len(set(inputs)) != len(inputs):
        raise ValueError("duplicate research input fingerprint")
    raw_root = Path(output_root)
    if raw_root.is_symlink():
        raise ValueError("symlink output directory not allowed")
    root = raw_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("existing private output directory required")
    probe = _available_memory_mib if memory_probe is None else memory_probe
    if not callable(probe):
        raise ValueError("memory probe required")
    lock = root / ".fx-research-batch.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        receipts = root / ".receipts"
        if receipts.is_symlink():
            raise ValueError("unsafe receipt directory")
        receipts.mkdir(exist_ok=True)
        outcome = {"verified": [], "skipped": [], "failed": [],
                   "blocked_memory": [], "blocked_integrity": []}
        pending = []
        for job in tasks:
            path = receipts / (job.job_id + ".json")
            try:
                tmp = receipts / (job.job_id + ".tmp")
                if tmp.is_symlink() or tmp.exists():
                    raise ValueError("uncommitted receipt requires operator review")
                if path.is_symlink():
                    raise ValueError("unsafe checkpoint")
                if path.exists():
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    _validate_receipt(VerifiedReceipt(**raw), job, root)
                    outcome["skipped"].append(job.job_id)
                else:
                    # An artifact without a receipt may be an interrupted run.
                    # Never silently rerun, overwrite or infer that it is valid.
                    artifact = root / (job.job_id + ".json")
                    if artifact.is_symlink() or artifact.exists():
                        raise ValueError("unreceipted artifact requires operator review")
                    pending.append(job)
            except (ValueError, TypeError, OSError) as exc:
                # A corrupt receipt must not be trusted, replaced or retried.
                # Other independent jobs remain eligible for research.
                outcome["blocked_integrity"].append({
                    "job_id": job.job_id, "type": type(exc).__name__})

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            next_index = 0
            memory_blocked = False
            while next_index < len(pending) or futures:
                while not memory_blocked and next_index < len(pending) and len(futures) < max_workers:
                    free = probe()
                    if type(free) is not int or free < min_free_mib:
                        memory_blocked = True
                        outcome["blocked_memory"].extend(x.job_id for x in pending[next_index:])
                        break
                    job = pending[next_index]
                    next_index += 1
                    futures[executor.submit(worker, job, str(root))] = job
                if not futures:
                    break
                ready, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in ready:
                    job = futures.pop(future)
                    try:
                        receipt = _validate_receipt(future.result(), job, root)
                        path = receipts / (job.job_id + ".json")
                        tmp = receipts / (job.job_id + ".tmp")
                        owned_tmp = False
                        try:
                            with tmp.open("x", encoding="utf-8") as stream:
                                owned_tmp = True
                                json.dump(asdict(receipt), stream, sort_keys=True)
                                stream.flush()
                                os.fsync(stream.fileno())
                            tmp.replace(path)
                        finally:
                            if owned_tmp:
                                tmp.unlink(missing_ok=True)
                        outcome["verified"].append(job.job_id)
                    except Exception as exc:
                        outcome["failed"].append({"job_id": job.job_id, "type": type(exc).__name__})
        return outcome
    finally:
        os.close(fd)
        lock.unlink()
