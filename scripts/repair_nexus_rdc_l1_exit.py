"""Repair the observed L1 supervisor exit status; never touch tasks or RDC."""
from __future__ import annotations
import argparse, hashlib, json, os, platform, tempfile
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path(r"C:\Users\afaq\AppData\Local\NEXUS\desktop-commander-remote\remote-supervisor.cjs")
EXPECTED_BEFORE = "6518fd61948239a6434a5569a5aaad87fc163cce7596377283e02d0889d05083"
OLD = b"process.exit(code||0)"
NEW = b"process.exit(code === null || code === 0 ? 1 : code)"

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def corrected_bytes(raw):
    if raw.count(NEW) == 1 and OLD not in raw:
        return raw
    if raw.count(OLD) != 1 or NEW in raw:
        raise ValueError("Unexpected exit-handler shape")
    return raw.replace(OLD, NEW, 1)

def verify_source(raw, expected=EXPECTED_BEFORE):
    original = raw.replace(NEW, OLD, 1) if raw.count(NEW) == 1 else raw
    if digest(original) != expected:
        raise ValueError("Supervisor does not match the observed immutable source")
    return corrected_bytes(raw)

def apply_with_backup(path, evidence, expected=EXPECTED_BEFORE):
    if path.is_symlink():
        raise ValueError("Symlinked supervisor is not the observed component")
    before = path.read_bytes()
    after = verify_source(before, expected)
    if after == before:
        return {"status": "ALREADY_CORRECT", "changed": False,
                "before_sha256": digest(before), "after_sha256": digest(after)}
    evidence.mkdir(parents=True, exist_ok=False)
    backup = evidence / "remote-supervisor.cjs.before"
    with backup.open("xb") as stream:
        stream.write(before); stream.flush(); os.fsync(stream.fileno())
    if backup.read_bytes() != before:
        raise ValueError("Backup verification failed")
    fd, temporary = tempfile.mkstemp(prefix="nexus-rdc-l1-exit-", dir=path.parent)
    pending = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(after); stream.flush(); os.fsync(stream.fileno())
        if path.read_bytes() != before:
            raise ValueError("Concurrent supervisor change; no replacement")
        os.replace(pending, path)
        if path.read_bytes() != after:
            raise ValueError("Readback mismatch; retain original backup")
    finally:
        if pending.exists():
            pending.unlink()
    return {"status": "EXIT_STATUS_FIXED", "changed": True,
            "before_sha256": digest(before), "after_sha256": digest(after),
            "backup_path": str(backup), "backup_byte_verified": True}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if len(args.source_sha) != 40 or any(c not in "0123456789abcdef" for c in args.source_sha):
        raise ValueError("Exact source SHA required")
    if platform.system() != "Windows" or os.environ.get("COMPUTERNAME") != "DESKTOP-1R1081M":
        raise ValueError("Wrong physical host")
    if TARGET.is_symlink():
        raise ValueError("Symlinked supervisor")
    stamp = datetime.now(timezone.utc)
    evidence = Path(r"E:\NEXUS-QA") / ("rdc-l1-exit-" + stamp.strftime("%Y%m%dT%H%M%S%fZ"))
    if args.apply:
        result = apply_with_backup(TARGET, evidence)
    else:
        raw = TARGET.read_bytes()
        result = {"status": "READ_ONLY_CHECK", "changed": False,
                  "fix_needed": verify_source(raw) != raw, "before_sha256": digest(raw)}
    result.update(schema="nexus.rdc-l1-exit-repair.v1", host=os.environ["COMPUTERNAME"],
                  source_sha=args.source_sha, checked_at_utc=stamp.isoformat(),
                  helper_sha256=digest(Path(__file__).read_bytes()),
                  active_remote_restarted=False, task_retargeted=False,
                  legacy_guard_removed=False, credentials_modified=False,
                  duplicate_remote_started=False, owner_state_modified=False,
                  applies_to_future_invocations=True, live_enabled=False)
    if args.apply and result["changed"]:
        (evidence / "receipt.json").write_text(json.dumps(result, sort_keys=True, indent=2)+"\n",
                                             encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
