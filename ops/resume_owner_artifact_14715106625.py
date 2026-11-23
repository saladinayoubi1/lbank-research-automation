"""Resume one immutable owner-authorized GitHub artifact; never activate an app."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time

ARTIFACT = 14715106625
RUN = 44924381327
SOURCE = "3c3461c4e39801232b64f1016cc48edc0ae6b0c5"
TOTAL = 266113158
EXPECTED = "14fa846d65266c36f100d2fc1ae991b10767c4d5b25f117b64ae5adf50ed8f67"
REPO = "saladinayoubi1/lbank-research-automation"
ROOT = Path(r"E:\NEXUS\NEXUS_OWNER_PAPER_PRIVATE")
GH = r"C:\Program Files\GitHub CLI\gh.exe"
PREFIX = ROOT / "original-artifact-14715106625-main.zip"
TARGET = ROOT / "original-artifact-14715106625-resumed.zip"
RECEIPT = ROOT / "original-artifact-14715106625-resume.json"
CHUNKS = ROOT / "original-artifact-14715106625-ranges"
CHUNK = 1024 * 1024


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def plain(path: Path) -> None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise RuntimeError("Transport path must not be a reparse point")


def api_json(route: str, env: dict[str, str]) -> dict:
    p = subprocess.run([GH, "api", route], capture_output=True, timeout=40, env=env)
    if p.returncode:
        raise RuntimeError("GitHub metadata request failed")
    return json.loads(p.stdout)


def decode_range(raw: bytes, start: int, end: int) -> bytes:
    header, separator, body = raw.partition(b"\r\n\r\n")
    if not separator or len(header) > 16384:
        raise RuntimeError("Artifact range headers missing or oversized")
    lines = header.decode("latin1").splitlines()
    if not lines or not re.fullmatch(r"HTTP/[0-9.]+ 206(?: .*)?", lines[0]):
        raise RuntimeError("Artifact server did not return partial content")
    headers: dict[str, list[str]] = {}
    for line in lines[1:]:
        key, sep, value = line.partition(":")
        if sep:
            headers.setdefault(key.lower(), []).append(value.strip())
    if headers.get("content-range") != [f"bytes {start}-{end}/{TOTAL}"]:
        raise RuntimeError("Artifact content range does not match requested bytes")
    if headers.get("content-length") != [str(end - start + 1)]:
        raise RuntimeError("Artifact declared range length mismatch")
    if len(body) != end - start + 1:
        raise RuntimeError("Artifact received range length mismatch")
    return body


def main() -> None:
    if os.name != "nt" or platform.node() != "DESKTOP-1R1081M":
        raise RuntimeError("Wrong physical download host")
    import msvcrt

    for p in (ROOT, PREFIX, TARGET, RECEIPT, CHUNKS):
        plain(p)
    lock_path = ROOT / "original-artifact-14715106625-resume.lock"
    plain(lock_path)
    lock = lock_path.open("a+b")
    if lock.tell() == 0:
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)

    env = os.environ.copy()
    env.pop("GH_DEBUG", None)
    env["GODEBUG"] = "http2client=0"
    started = time.monotonic()
    deadline = started + 1800
    previous = json.loads(RECEIPT.read_text()) if RECEIPT.exists() else None
    if previous and any(previous.get(k) != v for k, v in {
        "artifact_id": ARTIFACT, "source_sha": SOURCE, "expected_sha256": EXPECTED,
        "expected_bytes": TOTAL, "file": str(TARGET),
    }.items()):
        raise RuntimeError("Existing resume receipt is bound to another artifact")
    state = {
        "artifact_id": ARTIFACT, "artifact_run_id": RUN, "source_sha": SOURCE,
        "expected_bytes": TOTAL, "expected_sha256": EXPECTED, "file": str(TARGET),
        "controller_pid": os.getpid(), "owner_profile_touched": False,
        "settings_changed": False, "cache_published": False,
    }
    session_base = TARGET.stat().st_size if TARGET.exists() else PREFIX.stat().st_size

    def save(status: str, error: str = "") -> None:
        received = TARGET.stat().st_size if TARGET.exists() else 0
        elapsed = time.monotonic() - started
        payload = dict(state, status=status, updated_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       received_bytes=received, progress_percent=round(received / TOTAL * 100, 2),
                       elapsed_seconds=round(elapsed, 2),
                       session_mbps=round(max(0, received-session_base)*8/max(elapsed, 0.01)/1e6, 3),
                       error=error)
        temp = RECEIPT.with_suffix(".json.tmp")
        plain(temp)
        with temp.open("w", encoding="utf-8") as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, RECEIPT)

    try:
        meta = api_json(f"repos/{REPO}/actions/artifacts/{ARTIFACT}", env)
        if not (meta["id"] == ARTIFACT and meta["name"] == "nexus-windows-persistent-unpacked"
                and not meta["expired"] and meta["size_in_bytes"] == TOTAL
                and meta["digest"] == "sha256:" + EXPECTED
                and meta["workflow_run"]["id"] == RUN
                and meta["workflow_run"]["head_sha"] == SOURCE):
            raise RuntimeError("Official artifact identity mismatch")
        original = json.loads((ROOT / "original-artifact-14715106625-transfer.json").read_text())
        if not (original["status"] == "FAILED" and original["artifact_id"] == ARTIFACT
                and original["source_sha"] == SOURCE and original["expected_sha256"] == EXPECTED
                and PREFIX.stat().st_size == original["received_bytes"] == 48496640):
            raise RuntimeError("Original preserved download prefix changed")
        prefix_sha = digest(PREFIX)
        if previous and previous.get("prefix_sha256") is not None and previous["prefix_sha256"] != prefix_sha:
            raise RuntimeError("Original prefix differs from prior resume")
        state["prefix_sha256"] = prefix_sha
        state["prefix_bytes"] = PREFIX.stat().st_size
        if not TARGET.exists():
            with TARGET.open("xb") as dst, PREFIX.open("rb") as src:
                shutil.copyfileobj(src, dst, 1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
        with TARGET.open("rb") as f:
            if hashlib.sha256(f.read(state["prefix_bytes"])).hexdigest() != prefix_sha:
                raise RuntimeError("Resumed file does not retain original prefix")
        if not state["prefix_bytes"] <= TARGET.stat().st_size <= TOTAL:
            raise RuntimeError("Resumed artifact size outside bound")
        CHUNKS.mkdir(exist_ok=True)
        save("DOWNLOADING")

        def fetch(start: int, end: int) -> Path:
            part = CHUNKS / f"{start}-{end}.bin"
            checksum = part.with_suffix(".sha256")
            plain(part)
            plain(checksum)
            if part.exists() and checksum.exists() and part.stat().st_size == end-start+1:
                if digest(part) == checksum.read_text().strip():
                    return part
            for attempt in range(2):
                try:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Bounded transfer session expired")
                    # The ZIP bytes stay in a private binary buffer/file and are
                    # never sent to a terminal. CLI 2.97 otherwise rejects some
                    # valid ZIP ranges containing terminal-control byte patterns.
                    r = subprocess.run([GH, "api", f"repos/{REPO}/actions/artifacts/{ARTIFACT}/zip",
                                        "--header", f"Range: bytes={start}-{end}",
                                        "--allow-escape-sequences", "--include"],
                                       capture_output=True, timeout=85, env=env)
                    if r.returncode:
                        raise RuntimeError("GitHub range request failed")
                    body = decode_range(r.stdout, start, end)
                    temp = part.with_suffix(".incoming")
                    plain(temp)
                    with temp.open("wb") as f:
                        f.write(body)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(temp, part)
                    checksum.write_text(hashlib.sha256(body).hexdigest(), encoding="ascii")
                    return part
                except (subprocess.TimeoutExpired, RuntimeError) as e:
                    if attempt or time.monotonic() >= deadline:
                        detail = str(e) if isinstance(e, RuntimeError) else "Request timeout"
                        raise RuntimeError(f"Range {start}-{end} failed after bounded retry: {detail}") from None
            raise AssertionError("Unreachable")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            while TARGET.stat().st_size < TOTAL:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Bounded 30-minute resume stopped; committed bytes preserved")
                base = TARGET.stat().st_size
                ranges = [(start, min(TOTAL-1, start+CHUNK-1))
                          for start in range(base, min(TOTAL, base+4*CHUNK), CHUNK)]
                jobs = [(start, end, pool.submit(fetch, start, end)) for start, end in ranges]
                for start, end, future in jobs:
                    part = future.result()
                    if TARGET.stat().st_size != start:
                        raise RuntimeError("Concurrent artifact append detected")
                    with TARGET.open("ab") as dst, part.open("rb") as src:
                        shutil.copyfileobj(src, dst, CHUNK)
                        dst.flush()
                        os.fsync(dst.fileno())
                    save("DOWNLOADING")
                    part.unlink()
                    part.with_suffix(".sha256").unlink()
        if TARGET.stat().st_size != TOTAL or digest(TARGET) != EXPECTED:
            raise RuntimeError("Completed artifact failed exact size/SHA-256 verification")
        save("VERIFIED")
    except Exception as e:
        save("FAILED", str(e) if isinstance(e, RuntimeError) else type(e).__name__)
        raise SystemExit(1) from None
    finally:
        lock.close()


if __name__ == "__main__":
    main()
