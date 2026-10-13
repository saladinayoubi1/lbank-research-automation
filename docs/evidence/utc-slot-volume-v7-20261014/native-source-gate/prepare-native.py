from datetime import datetime, timezone
import hashlib, json, os
from pathlib import Path
import subprocess, sys, zipfile

ROOT = Path(r"E:\NEXUS-QA\utc-slot-volume-v7-20261014")
SOURCE = "7cab4f0368823ef3dd9dec79f572bd05721e2316"
STATUS = ROOT / "native-gate-status.json"
def stamp():
    return datetime.now(timezone.utc).isoformat()
def put(path, data):
    target = path.with_suffix(path.suffix + ".tmp")
    target.write_text(json.dumps(data, sort_keys=True, indent=2), encoding="utf-8")
    target.replace(path)
def hashed(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def status(state, **extra):
    put(STATUS, dict(status=state, checked_at_utc=stamp(), source_sha=SOURCE,
                    research_only=True, live_enabled=False,
                    market_backtests_executed=0, **extra))
if STATUS.exists():
    raise SystemExit("Existing native stage; inspect rather than replay")
(ROOT / "native-execution.lock").open("x").close()
try:
    status("FETCHING_EXACT_SOURCE")
    bundle = ROOT / "exact-source.zip"
    with bundle.open("xb") as out, (ROOT / "source-fetch.stderr.log").open("w") as err:
        subprocess.run(["gh", "api", "--method", "GET",
                        "repos/saladinayoubi1/lbank-research-automation/zipball/" + SOURCE],
                       stdout=out, stderr=err, timeout=60, check=True)
    with zipfile.ZipFile(bundle) as z:
        members = z.infolist()
        prefix = members[0].filename.split("/")[0] + "/"
        destination = ROOT / "source"
        destination.mkdir()
        for item in members:
            if not item.filename.startswith(prefix):
                raise ValueError("source zip has multiple roots")
            rel = Path(item.filename[len(prefix):])
            if rel.is_absolute() or ".." in rel.parts or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("unsafe source member")
            target = destination / rel
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(item))
    source = ROOT / "source"
    frozen = source / "docs/evidence/utc-slot-volume-v7-20261013"
    freeze = json.loads((frozen / "study-freeze.json").read_text())
    amendment = json.loads((frozen / "routing-fix/freeze-amendment.json").read_text())
    if freeze["freeze_digest"] != "d5d0e8c4f8f78632afa321bbf23ce84ac988827b03b7890575f7277f05b491d4":
        raise ValueError("wrong study freeze")
    if amendment["amendment_digest"] != "fed3adebaa2274b05f9f1907f231d723242ca6fe36417be598b0dd2649981ce3":
        raise ValueError("wrong routing amendment")
    for document, field in ((freeze, "freeze_digest"), (amendment, "amendment_digest")):
        actual = hashlib.sha256(json.dumps({k:v for k,v in document.items() if k != field},
                                 sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        if actual != document[field]:
            raise ValueError("invalid preregistration digest")
    expected = {**freeze["file_sha256"], **amendment["file_sha256"]}
    file_hashes = {name:hashed(source / name) for name in expected}
    if file_hashes != expected:
        raise ValueError("source bytes differ from preregistration")
    sys.path.insert(0, str(source))
    import numpy, pandas, pyarrow
    import nexus_composite_strategy_research as engine
    prior = Path(r"E:\NEXUS-QA\causal-jump-v6-20261013\producer\novelty-ledger.json")
    ledger = engine.load_ledger(prior)
    if ledger["ledger_digest"] != freeze["previous_ledger_digest"]:
        raise ValueError("wrong terminal ledger")
    candidates = engine._frontier_configs_to_screen(ledger)
    if len(candidates) != 1 or candidates[0] != freeze["candidate_config"]:
        raise ValueError("new candidate/config binding failed")
    binding = dict(source_sha=SOURCE, source_archive_sha256=hashed(bundle),
                   freeze_digest=freeze["freeze_digest"],
                   amendment_digest=amendment["amendment_digest"],
                   source_file_sha256=file_hashes, previous_ledger_path=str(prior),
                   previous_ledger_file_sha256=hashed(prior),
                   previous_ledger_digest=ledger["ledger_digest"],
                   selected_candidate=candidates[0],
                   python=sys.version, numpy=numpy.__version__, pandas=pandas.__version__,
                   pyarrow=pyarrow.__version__, host=os.environ.get("COMPUTERNAME"),
                   research_only=True, live_enabled=False)
    put(ROOT / "native-source-binding.json", binding)
    status("RUNNING_NATIVE_SOURCE_GATE", source_binding_sha256=hashed(ROOT / "native-source-binding.json"))
    harness = frozen / "routing-fix/run_targeted_regressions.py"
    with (ROOT / "native-gate.stdout.log").open("w") as out, (ROOT / "native-gate.stderr.log").open("w") as err:
        result = subprocess.run([sys.executable, str(harness)], cwd=source,
                                stdout=out, stderr=err, timeout=180, check=False)
    (ROOT / "native-gate-exit.txt").write_text(str(result.returncode), encoding="ascii")
    status("NATIVE_SOURCE_GATE_PASS" if result.returncode == 0 else "NATIVE_SOURCE_GATE_FAILED",
           exit_code=result.returncode, source_binding_sha256=hashed(ROOT / "native-source-binding.json"),
           stdout_sha256=hashed(ROOT / "native-gate.stdout.log"),
           stderr_sha256=hashed(ROOT / "native-gate.stderr.log"))
except Exception as exc:
    status("NATIVE_SOURCE_STAGE_FAILED", error_type=type(exc).__name__)
    (ROOT / "native-stage-error.txt").write_text(type(exc).__name__ + ": " + str(exc), encoding="utf-8")
    raise
