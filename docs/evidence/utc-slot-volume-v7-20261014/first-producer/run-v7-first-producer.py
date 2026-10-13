from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, os, platform, subprocess, sys, time, traceback, zipfile

ROOT = Path(r"E:\NEXUS-QA\utc-slot-volume-v7-20261014")
SOURCE = ROOT / "source"
SOURCE_SHA = "7cab4f0368823ef3dd9dec79f572bd05721e2316"
CACHE = Path(r"C:\NEXUS\research-cache\replay-canonical-37681826492")
ARCHIVE = CACHE / "archive"
DELIVERY = CACHE / "delivery" / "NEXUS_BYBIT_replay_v2_2022-12-01_to_2026-07-31.zip"
DATASET_ID = "2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422"
DELIVERY_SHA = "d284a49f1b6e8951763cf225992a52a620289b2baf10815247d8626045763cec"
PREVIOUS = Path(r"E:\NEXUS-QA\causal-jump-v6-20261013\producer\novelty-ledger.json")
PRIOR_DIGEST = "18675234ad8c981be8f8c5e348c1a39737a9c3fc4ca09ba0ae9532c8a59b567a"
LEASE = "isolated-utc-slot-volume-v7-20261014-7cab4f0"
OUTPUT = ROOT / "producer"
STATUS = ROOT / "producer-status.json"
DEADLINE = 600
start = time.monotonic()
child = None
market_started = False

def now():
    return datetime.now(timezone.utc).isoformat()

def sha_bytes(raw):
    return hashlib.sha256(raw).hexdigest()

def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def put(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)

def status(state, **extra):
    value = dict(schema="nexus.v7-first-producer-checkpoint.v1", status=state,
                 checked_at_utc=now(), lease_id=LEASE, source_sha=SOURCE_SHA,
                 host=os.environ.get("COMPUTERNAME"), research_only=True,
                 auto_demo_promotion=False, owner_demo_admission=False,
                 live_enabled=False, official_coordinator_advanced=False,
                 independent_strategy_qa_complete=False, market_started=market_started,
                 elapsed_seconds=round(time.monotonic()-start, 3), **extra)
    put(STATUS, value)
    print(json.dumps(value, sort_keys=True), flush=True)

def require(value, reason):
    if not value:
        raise ValueError(reason)

def zip_member(archive, relative):
    matches = [name for name in archive.namelist()
               if name == relative or name.endswith("/" + relative)]
    require(len(matches) == 1, "ZIP member missing or ambiguous: " + relative)
    return archive.read(matches[0])

with (ROOT / "producer-execution.lock").open("x", encoding="utf-8") as lock:
    json.dump(dict(lease_id=LEASE, source_sha=SOURCE_SHA, wrapper_pid=os.getpid(),
                   created_at_utc=now(), child_timeout_seconds=DEADLINE,
                   research_only=True, live_enabled=False), lock, sort_keys=True)
try:
    require(platform.system() == "Windows" and not sys.flags.optimize,
            "Native Windows with assertions required")
    require(os.environ.get("COMPUTERNAME") == "DESKTOP-F4SA4VL",
            "Wrong physical producer host")
    require(not OUTPUT.exists(), "Existing producer output; never rerun")
    status("VERIFYING_NATIVE_INPUTS")
    gate = load(ROOT / "native-gate-receipt.json")
    binding = load(ROOT / "native-source-binding.json")
    require(sha(ROOT / "native-gate-receipt.json") ==
            "33ec80b99dc0d224532b8f8719da88273964bff1268dfe94d5a577669e099cf7",
            "Native gate receipt changed")
    require(sha(ROOT / "native-source-binding.json") ==
            "752f74d60060c050f28c81b0ab9e1757211ec7c58ecb19f6995e0297248d9eb4",
            "Native source binding changed")
    require(gate["source_sha"] == SOURCE_SHA and gate["exit_code"] == 0
            and gate["test_count"] == 30 and gate["failures"] == 0
            and gate["errors"] == 0, "Native source gate is not passed")
    require((ROOT / "native-gate-exit.txt").read_text().strip() == "0",
            "Native source exit file mismatch")
    require(load(ROOT / "native-gate-continuation-status.json")["status"] ==
            "NATIVE_SOURCE_GATE_PASS", "Native gate state changed")
    require(binding["source_sha"] == SOURCE_SHA, "Computation source mismatch")
    require(sha(ROOT / "exact-source.zip") == binding["source_archive_sha256"],
            "Exact source archive changed")
    source_hashes = {}
    with zipfile.ZipFile(ROOT / "exact-source.zip") as archive:
        for entry in archive.infolist():
            if entry.is_dir() or "/" not in entry.filename:
                continue
            relative = entry.filename.split("/", 1)[1]
            if (relative.endswith(".py") or
                (relative.startswith("research/") and relative.endswith(".json"))):
                actual = sha(SOURCE / relative)
                require(actual == sha_bytes(archive.read(entry)),
                        "Exact GitHub source differs: " + relative)
                source_hashes[relative] = actual
    require("nexus_composite_strategy_research.py" in source_hashes,
            "Source archive does not bind the engine")
    for relative, expected in binding["source_file_sha256"].items():
        require(sha(SOURCE / relative) == expected, "Source-gate file changed: " + relative)
    freeze = load(SOURCE / "docs/evidence/utc-slot-volume-v7-20261013/study-freeze.json")
    require(freeze["freeze_digest"] ==
            "d5d0e8c4f8f78632afa321bbf23ce84ac988827b03b7890575f7277f05b491d4",
            "Original study freeze changed")
    require(sha(PREVIOUS) == binding["previous_ledger_file_sha256"],
            "Completed v6 predecessor file changed")
    sys.path.insert(0, str(SOURCE))
    import nexus_composite_strategy_research as engine
    previous = engine.load_ledger(PREVIOUS)
    require(previous["ledger_digest"] == PRIOR_DIGEST, "Wrong terminal predecessor")
    require(engine._frontier_configs_to_screen(previous) == [freeze["candidate_config"]],
            "Frontier must contain exactly the frozen one new candidate")
    require(sha(DELIVERY) == DELIVERY_SHA, "Delivery ZIP byte identity differs")
    require(DELIVERY.with_suffix(".zip.sha256").read_text().split()[0] == DELIVERY_SHA,
            "Existing delivery sidecar differs")
    manifest = load(ARCHIVE / "REPLAY_DATASET_MANIFEST.json")
    require(manifest["semantic_dataset_sha256"] == DATASET_ID
            and manifest["venue"] == "bybit" and manifest["series_count"] == 6,
            "Wrong semantic dataset identity")
    reference = load(Path(r"E:\NEXUS-QA\causal-jump-v6-20261013\input-attestation.json"))
    require(reference["archive_sha256"] == DATASET_ID, "Prior data attestation differs")
    expected = {(row["symbol"], row["timeframe"]): row["raw_file_sha256"]
                for row in reference["raw_frames"]}
    raw_inputs = []
    with zipfile.ZipFile(DELIVERY) as archive:
        require(sha_bytes(zip_member(archive, "REPLAY_DATASET_MANIFEST.json")) ==
                sha(ARCHIVE / "REPLAY_DATASET_MANIFEST.json"), "Dataset manifest differs from ZIP")
        for symbol in ("BTCUSDT", "ETHUSDT"):
            for timeframe in ("minute15", "hour1", "hour4"):
                relative = "bybit_market/" + symbol[:3].lower() + "_usdt/" + timeframe + ".parquet"
                path = ARCHIVE / relative
                expected_hash = expected[(symbol, timeframe)]
                require(not path.is_symlink(), "Symlinked dataset input")
                require(sha(path) == expected_hash and
                        sha_bytes(zip_member(archive, relative)) == expected_hash,
                        "Raw data file/ZIP differs: " + relative)
                item = next(row for row in manifest["files"] if row["path"] == relative)
                require(item["parquet_sha256"] == expected_hash and
                        item["bytes"] == path.stat().st_size, "Manifest raw binding differs")
                raw_inputs.append(dict(symbol=symbol, timeframe=timeframe, path=str(path),
                                       relative_path=relative, raw_file_sha256=expected_hash,
                                       bytes=path.stat().st_size, rows=item["rows"],
                                       first_timestamp=item["first_timestamp"],
                                       last_timestamp=item["last_timestamp"]))
    put(ROOT / "producer-input-binding.json",
        dict(schema="nexus.v7-first-producer-input-binding.v1", bound_at_utc=now(),
             source_sha=SOURCE_SHA, source_archive_sha256=binding["source_archive_sha256"],
             source_component_sha256=source_hashes,
             native_gate_receipt_sha256=sha(ROOT / "native-gate-receipt.json"),
             original_freeze_digest=freeze["freeze_digest"],
             archive_root=str(ARCHIVE), archive_semantic_sha256=DATASET_ID,
             delivery_zip_path=str(DELIVERY), delivery_zip_byte_sha256=DELIVERY_SHA,
             manifest_file_sha256=sha(ARCHIVE / "REPLAY_DATASET_MANIFEST.json"),
             previous_ledger_path=str(PREVIOUS), previous_ledger_digest=PRIOR_DIGEST,
             previous_ledger_file_sha256=sha(PREVIOUS),
             candidate_config=freeze["candidate_config"], raw_inputs=raw_inputs,
             reference_decoded_input_digest=reference["reference_decoded_input_digest"],
             decoded_parity_recomputed=False, research_only=True, live_enabled=False))
    command = [sys.executable, str(SOURCE / "nexus_composite_strategy_research.py"),
               "--archive-root", str(ARCHIVE), "--output", str(OUTPUT),
               "--source-sha", SOURCE_SHA, "--previous-ledger", str(PREVIOUS)]
    put(ROOT / "producer-command.json",
        dict(argv=command, cwd=str(SOURCE), deadline_seconds=DEADLINE,
             wrapper_sha256=sha(Path(__file__)), precheck_sha256=sha(ROOT / "V7_PRODUCER_PRECHECK.md"),
             source_sha=SOURCE_SHA, research_only=True, live_enabled=False))
    with (ROOT / "producer.stdout.log").open("wb") as stdout, \
         (ROOT / "producer.stderr.log").open("wb") as stderr:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        child = subprocess.Popen(command, cwd=str(SOURCE), stdout=stdout,
                                 stderr=stderr, env=environment)
        market_started = True
        status("RUNNING_FIRST_FROZEN_PRODUCER", child_pid=child.pid,
               child_timeout_seconds=DEADLINE,
               input_binding_sha256=sha(ROOT / "producer-input-binding.json"))
        try:
            exit_code = child.wait(timeout=DEADLINE)
        except subprocess.TimeoutExpired:
            child.kill()
            exit_code = child.wait(timeout=15)
            (ROOT / "producer-exit.txt").write_text(str(exit_code), encoding="ascii")
            status("PRODUCER_DEADLINE_EXCEEDED_NOT_QUALIFIED", child_pid=child.pid,
                   child_exit_code=exit_code, retry_authorized=False)
            raise SystemExit(124)
    (ROOT / "producer-exit.txt").write_text(str(exit_code), encoding="ascii")
    require(exit_code == 0, "Producer returned nonzero true exit: " + str(exit_code))
    report = load(OUTPUT / "research-report.json")
    ledger = engine.load_ledger(OUTPUT / "novelty-ledger.json")
    require(engine.digest({k:v for k,v in report.items() if k != "report_digest"}) ==
            report["report_digest"], "Report digest invalid")
    require(report["source_sha"] == SOURCE_SHA and report["archive_sha256"] == DATASET_ID
            and report["research_only"] is True and report["live_enabled"] is False
            and report["auto_demo_promotion"] is False, "Report identity/authority differs")
    require(report["selected"] == freeze["candidate_config"], "Frozen candidate changed")
    screening = report["frontier_screening"]
    require(screening["candidate_count"] == 1
            and screening["screened_mechanisms"] == [freeze["candidate_id"]]
            and screening["validation_used_for_selection"] is False
            and screening["historically_inspected_test_used_for_selection"] is False,
            "Training-only one-candidate screening differs")
    rows = report["rows"]
    required = {(s,p,c) for s in ("BTCUSDT","ETHUSDT")
                for p in ("train","validation","historically_inspected_test")
                for c in ("conservative","stress")}
    require(len(rows) == 12 and
            {(r["symbol"],r["part"],r["profile"]) for r in rows} == required,
            "Fixed 12-cell diagnostic grid incomplete or duplicated")
    cells = screening["ranking"][0]["cells"]
    require(len(cells) == 4, "Expected four Training-screen cells")
    for cell in cells:
        row = next(r for r in rows if r["part"] == "train" and
                   r["symbol"] == cell["symbol"] and r["profile"] == cell["profile"])
        for metric in ("net_return_pct","max_drawdown_pct","closed_round_trips",
                       "profit_factor","win_rate_pct","bars"):
            require(row[metric] == cell[metric], "Repeated Training metric differs: " + metric)
    require(ledger["config_fingerprints_evaluated"] ==
            previous["config_fingerprints_evaluated"] + [freeze["candidate_config_fingerprint"]],
            "Prior config history reset or extra candidate evaluated")
    require(ledger["mechanisms_evaluated"] ==
            sorted(set(previous["mechanisms_evaluated"] + [freeze["candidate_id"]])),
            "Prior evaluated history changed")
    require(ledger["frontier_screened_mechanisms"] ==
            sorted(set(previous["frontier_screened_mechanisms"] + [freeze["candidate_id"]])),
            "Prior screened history changed")
    require(report["ledger_digest"] == ledger["ledger_digest"], "Report/ledger disagree")
    require(sha(PREVIOUS) == binding["previous_ledger_file_sha256"], "Prior ledger mutated")
    for relative, expected_hash in source_hashes.items():
        require(sha(SOURCE / relative) == expected_hash, "Producer source mutated")
    for item in raw_inputs:
        require(sha(Path(item["path"])) == item["raw_file_sha256"], "Producer input mutated")
    summary_rows = [dict(symbol=r["symbol"],part=r["part"],profile=r["profile"],
                         first_closed_utc=r["first_closed_utc"],last_closed_utc=r["last_closed_utc"],
                         bars=r["bars"],closed_round_trips=r["closed_round_trips"],
                         net_return_pct=r["net_return_pct"],net_pnl_usdt=r["net_pnl_usdt"],
                         mean_closed_trade_pnl_usdt=(round(r["net_pnl_usdt"]/r["closed_round_trips"],8)
                                                    if r["closed_round_trips"] else None),
                         max_drawdown_pct=r["max_drawdown_pct"],fee_bps=r["fee_bps"],
                         slippage_bps=r["slippage_bps"],turnover_usdt=r["turnover_usdt"])
                    for r in rows]
    put(ROOT / "producer-result-summary.json",
        dict(schema="nexus.v7-first-producer-result-summary.v1",source_sha=SOURCE_SHA,
             report_digest=report["report_digest"],rows=summary_rows,
             initial_simulated_cash_usdt_per_cell=10000,owner_reference_usdt=500,
             historical_test_pristine=False,monthly_return_claim=False,
             independent_strategy_qa_complete=False,owner_demo_admission=False,
             auto_demo_promotion=False,research_only=True,live_enabled=False))
    receipt = dict(schema="nexus.v7-first-producer-receipt.v1",completed_at_utc=now(),
                   lease_id=LEASE,host=os.environ.get("COMPUTERNAME"),native_windows=True,
                   source_sha=SOURCE_SHA,child_pid=child.pid,true_child_exit_code=exit_code,
                   elapsed_seconds=round(time.monotonic()-start,3),
                   deadline_seconds=DEADLINE,parameter_configurations=1,
                   training_screen_cells=4,diagnostic_rows=12,
                   report_digest=report["report_digest"],ledger_digest=ledger["ledger_digest"],
                   report_file_sha256=sha(OUTPUT/"research-report.json"),
                   ledger_file_sha256=sha(OUTPUT/"novelty-ledger.json"),
                   input_binding_sha256=sha(ROOT/"producer-input-binding.json"),
                   result_summary_sha256=sha(ROOT/"producer-result-summary.json"),
                   command_file_sha256=sha(ROOT/"producer-command.json"),
                   wrapper_sha256=sha(Path(__file__)),
                   stdout_sha256=sha(ROOT/"producer.stdout.log"),
                   stderr_sha256=sha(ROOT/"producer.stderr.log"),
                   source_and_raw_inputs_unchanged=True,previous_ledger_unchanged=True,
                   independent_strategy_qa_complete=False,historical_test_pristine=False,
                   owner_demo_admission=False,auto_demo_promotion=False,
                   official_coordinator_advanced=False,research_only=True,live_enabled=False)
    receipt["receipt_digest"] = engine.digest(receipt)
    put(ROOT/"producer-receipt.json",receipt)
    status("COMPLETE_RESEARCH_NOT_QUALIFIED",child_pid=child.pid,
           child_exit_code=exit_code,receipt_sha256=sha(ROOT/"producer-receipt.json"),
           report_digest=report["report_digest"],diagnostic_rows=12)
    print(json.dumps(receipt,sort_keys=True),flush=True)
except Exception as exc:
    (ROOT/"producer-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
    status("FIRST_PRODUCER_FAILED_NOT_QUALIFIED",error_type=type(exc).__name__,
           child_pid=child.pid if child else None,
           child_exit_code=child.poll() if child else None,retry_authorized=False)
    raise
