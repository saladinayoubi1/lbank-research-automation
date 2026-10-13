"""Repair only the observed L2 nested-batch return bug; never restart RDC."""
from __future__ import annotations
import argparse, hashlib, json, os, platform, tempfile
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path(r"C:\Users\afaq\AppData\Local\NEXUS-Research\remote-supervisor.cmd")
NPX = b'"C:\\Program Files\\nodejs\\npx.cmd" -y @wonderwhy-er/desktop-commander@latest remote'
ORIGINAL = (b"@echo off", b":loop", NPX, b"timeout /t 15 /nobreak >nul", b"goto loop")
FIXED = (*ORIGINAL[:2], b"call " + NPX, *ORIGINAL[3:])

def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def corrected_bytes(raw: bytes) -> bytes:
    """Fail closed on unrelated launcher content; preserve all other bytes."""
    lines = tuple(raw.splitlines())
    if lines == FIXED:
        return raw
    if lines != ORIGINAL or raw.count(NPX) != 1:
        raise ValueError("Launcher does not match the observed five-line L2 component")
    return raw.replace(NPX, b"call " + NPX, 1)

def apply_with_backup(path: Path, evidence: Path) -> dict:
    before = path.read_bytes()
    after = corrected_bytes(before)
    if before == after:
        return {"status": "ALREADY_CORRECT", "changed": False,
                "before_sha256": digest(before), "after_sha256": digest(after)}
    evidence.mkdir(parents=True, exist_ok=False)
    backup = evidence / "remote-supervisor.cmd.before"
    with backup.open("xb") as stream:
        stream.write(before)
        stream.flush()
        os.fsync(stream.fileno())
    check = backup.read_bytes()
    if check != before:
        raise ValueError("Backup byte verification failed")
    descriptor, temporary = tempfile.mkstemp(prefix="nexus-rdc-return-", suffix=".tmp",
                                            dir=path.parent)
    pending = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != before:
            raise ValueError("Launcher changed concurrently; refusing replacement")
        os.replace(pending, path)
        if path.read_bytes() != after:
            raise ValueError("Patched launcher readback differs; retain backup")
    finally:
        if pending.exists():
            pending.unlink()
    return {"status": "CALL_RETURN_FIXED", "changed": True,
            "before_sha256": digest(before), "after_sha256": digest(after),
            "backup_path": str(backup), "backup_byte_verified": True}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    if len(args.source_sha) != 40 or any(c not in "0123456789abcdef" for c in args.source_sha):
        raise ValueError("Exact source SHA required")
    if platform.system() != "Windows" or os.environ.get("COMPUTERNAME") != "DESKTOP-F4SA4VL":
        raise ValueError("This operation is bound to the observed physical Laptop2")
    if TARGET.is_symlink():
        raise ValueError("Symlinked launcher is not the observed component")
    timestamp = datetime.now(timezone.utc)
    evidence = Path(r"E:\NEXUS-QA") / ("rdc-return-" + timestamp.strftime("%Y%m%dT%H%M%S%fZ"))
    if args.apply:
        result = apply_with_backup(TARGET, evidence)
    else:
        raw = TARGET.read_bytes()
        result = {"status": "READ_ONLY_CHECK", "changed": False,
                  "call_fix_needed": corrected_bytes(raw) != raw,
                  "before_sha256": digest(raw)}
    result.update(schema="nexus.rdc-batch-return-repair.v1",
                  source_sha=args.source_sha, host=os.environ["COMPUTERNAME"],
                  checked_at_utc=timestamp.isoformat(), target=str(TARGET),
                  applies_to_future_launcher_invocations=True,
                  active_remote_restarted=False, credentials_modified=False,
                  startup_modified=False, scheduled_tasks_modified=False,
                  duplicate_remote_started=False, owner_state_modified=False,
                  live_enabled=False, helper_sha256=digest(Path(__file__).read_bytes()))
    if args.apply and result["changed"]:
        (evidence / "receipt.json").write_text(json.dumps(result, sort_keys=True, indent=2)+"\n",
                                             encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
