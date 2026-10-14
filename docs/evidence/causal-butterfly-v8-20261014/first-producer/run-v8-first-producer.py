"""One preregistered, hash-bound native Butterfly producer; durable real child exit."""
from datetime import datetime, timezone
from pathlib import Path
import argparse, hashlib, json, os, platform, subprocess, sys, time, traceback, zipfile

parser=argparse.ArgumentParser()
parser.add_argument("--freeze",type=Path,required=True)
parser.add_argument("--freeze-sha",required=True)
args=parser.parse_args()
def now(): return datetime.now(timezone.utc).isoformat()
def sha_bytes(raw): return hashlib.sha256(raw).hexdigest()
def sha(path):
    with path.open("rb") as stream: return hashlib.file_digest(stream,"sha256").hexdigest()
def load(path): return json.loads(path.read_text(encoding="utf-8"))
def require(value,reason):
    if not value: raise ValueError(reason)
def put(path,value):
    temporary=path.with_suffix(path.suffix+".tmp")
    with temporary.open("w",encoding="utf-8",newline="\n") as stream:
        json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)
require(sha(args.freeze)==args.freeze_sha,"Frozen invocation bytes changed")
freeze=load(args.freeze)
ROOT=Path(freeze["run_root"])
SOURCE=Path(freeze["source_root"])
GATE_ROOT=Path(freeze["source_gate_root"])
SOURCE_SHA=freeze["source_sha"]
ARCHIVE=Path(freeze["archive_root"])
DELIVERY=Path(freeze["delivery_zip_path"])
DATASET_ID=freeze["archive_semantic_sha256"]
DELIVERY_SHA=freeze["delivery_zip_byte_sha256"]
PREVIOUS=Path(freeze["previous_ledger_path"])
PRIOR_DIGEST=freeze["previous_ledger_digest"]
LEASE=freeze["lease_id"]
OUTPUT=ROOT/"producer"
STATUS=ROOT/"producer-status.json"
DEADLINE=freeze["deadline_seconds"]
start=time.monotonic()
child=None
market_started=False
def status(state,**extra):
    value=dict(schema="nexus.v8-first-producer-checkpoint.v1",status=state,
        checked_at_utc=now(),lease_id=LEASE,source_sha=SOURCE_SHA,
        host=os.environ.get("COMPUTERNAME"),research_only=True,auto_demo_promotion=False,
        owner_demo_admission=False,live_enabled=False,official_coordinator_advanced=False,
        independent_strategy_qa_complete=False,market_started=market_started,
        elapsed_seconds=round(time.monotonic()-start,3),**extra)
    put(STATUS,value); print(json.dumps(value,sort_keys=True),flush=True)
def zip_member(archive,relative):
    matches=[name for name in archive.namelist() if name==relative or name.endswith("/"+relative)]
    require(len(matches)==1,"ZIP member missing or ambiguous: "+relative)
    return archive.read(matches[0])
require(ROOT.resolve()==args.freeze.parent.resolve(),"Wrong frozen run directory")
require(sha(Path(__file__))==freeze["wrapper_sha256"],"Producer wrapper changed")
require(sha(ROOT/"V8_PRODUCER_PRECHECK.md")==freeze["precheck_sha256"],"Precheck changed")
lock_record=dict(lease_id=LEASE,source_sha=SOURCE_SHA,wrapper_pid=os.getpid(),
                 created_at_utc=now(),child_timeout_seconds=DEADLINE,
                 research_only=True,live_enabled=False,run_root=str(ROOT))
for path in (GATE_ROOT/"first-market-producer.lock", ROOT/"producer-execution.lock"):
    with path.open("x",encoding="utf-8") as lock:
        json.dump(lock_record,lock,sort_keys=True); lock.flush(); os.fsync(lock.fileno())
try:
    require(platform.system()=="Windows" and not sys.flags.optimize and sys.version_info[:2]==(3,12),
            "Native pinned Windows runtime with assertions required")
    require(os.environ.get("COMPUTERNAME")=="DESKTOP-F4SA4VL","Wrong physical producer host")
    require(Path(sys.executable).resolve()==Path(freeze["runtime_executable"]).resolve(),"Runtime path differs")
    require(DEADLINE==600 and not OUTPUT.exists(),"Existing output or changed deadline; never rerun")
    status("VERIFYING_NATIVE_INPUTS")
    for relative,expected in freeze["source_gate_file_sha256"].items():
        require(sha(GATE_ROOT/relative)==expected,"Completed native gate changed: "+relative)
    gate=load(GATE_ROOT/"native-source-receipt.json")
    proof=load(GATE_ROOT/"exit-proof/receipt.json")
    require(gate["source_sha"]==SOURCE_SHA and gate["tests_run"]==39
            and gate["failures"]==0 and gate["errors"]==0,"Native semantic tests not passed")
    require(proof["source_sha"]==SOURCE_SHA and proof["true_child_exit_code"]==0
            and proof["native_source_tests"]==39 and proof["source_and_prior_ledger_unchanged"] is True,
            "True native source-gate exit proof differs")
    require(load(GATE_ROOT/"native-status.json")["status"]=="NATIVE_SOURCE_GATE_PASS","Gate state changed")
    source_hashes=freeze["source_component_sha256"]
    require(gate["source_file_sha256"]==source_hashes,"Source-gate component binding differs")
    for relative,expected in source_hashes.items():
        require(not (SOURCE/relative).is_symlink() and sha(SOURCE/relative)==expected,"Source bytes changed: "+relative)
    actual={p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob("*") if p.is_file()
            and (p.suffix==".py" or (p.suffix==".json" and p.relative_to(SOURCE).parts[0]=="research"))}
    expected={p for p in source_hashes if p.endswith(".py") or (p.startswith("research/") and p.endswith(".json"))}
    require(actual==expected,"Unbound executable/research components present")
    require(sha(PREVIOUS)==freeze["previous_ledger_file_sha256"],"Completed v7 predecessor bytes changed")
    sys.path.insert(0,str(SOURCE))
    import numpy,pandas,pyarrow
    require((numpy.__version__,pandas.__version__,pyarrow.__version__)==("2.3.5","2.3.3","23.0.1"),"Pinned dependencies changed")
    import nexus_composite_strategy_research as engine
    require(engine.digest({k:v for k,v in gate.items() if k!="receipt_digest"})==gate["receipt_digest"]
            and gate["receipt_digest"]==freeze["native_source_gate_receipt_digest"],"Gate semantic digest invalid")
    previous=engine.load_ledger(PREVIOUS)
    require(previous["ledger_digest"]==PRIOR_DIGEST,"Wrong terminal v7 predecessor")
    require(engine.research_mode(previous)=="frontier_tournament"
            and engine._frontier_configs_to_screen(previous)==[freeze["candidate_config"]],
            "Frontier must contain only the frozen Butterfly candidate")
    require(sha(DELIVERY) == DELIVERY_SHA, "Delivery ZIP byte identity differs")
    require(DELIVERY.with_suffix(".zip.sha256").read_text().split()[0] == DELIVERY_SHA,
            "Existing delivery sidecar differs")
    manifest = load(ARCHIVE / "REPLAY_DATASET_MANIFEST.json")
    require(manifest["semantic_dataset_sha256"] == DATASET_ID
            and manifest["venue"] == "bybit" and manifest["series_count"] == 6,
            "Wrong semantic dataset identity")
    require(sha(ARCHIVE / "REPLAY_DATASET_MANIFEST.json") == freeze["manifest_file_sha256"],
            "Manifest file binding changed")
    expected = {(row["symbol"], row["timeframe"]): row["raw_file_sha256"]
                for row in freeze["raw_inputs"]}
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
        dict(schema="nexus.v8-first-producer-input-binding.v1", bound_at_utc=now(),
             source_sha=SOURCE_SHA, source_gate_receipt_digest=gate["receipt_digest"],
             source_component_sha256=source_hashes,
             native_gate_receipt_sha256=sha(GATE_ROOT / "native-source-receipt.json"),
             invocation_freeze_sha256=sha(args.freeze),
             archive_root=str(ARCHIVE), archive_semantic_sha256=DATASET_ID,
             delivery_zip_path=str(DELIVERY), delivery_zip_byte_sha256=DELIVERY_SHA,
             manifest_file_sha256=sha(ARCHIVE / "REPLAY_DATASET_MANIFEST.json"),
             previous_ledger_path=str(PREVIOUS), previous_ledger_digest=PRIOR_DIGEST,
             previous_ledger_file_sha256=sha(PREVIOUS),
             candidate_config=freeze["candidate_config"], raw_inputs=raw_inputs,
             raw_zip_parity_recomputed=True,
             decoded_parity_recomputed=False, research_only=True, live_enabled=False))
    command = [sys.executable, str(SOURCE / "nexus_composite_strategy_research.py"),
               "--archive-root", str(ARCHIVE), "--output", str(OUTPUT),
               "--source-sha", SOURCE_SHA, "--previous-ledger", str(PREVIOUS)]
    put(ROOT / "producer-command.json",
        dict(argv=command, cwd=str(SOURCE), deadline_seconds=DEADLINE,
             wrapper_sha256=sha(Path(__file__)), precheck_sha256=sha(ROOT / "V8_PRODUCER_PRECHECK.md"),
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
            termination = subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                                         stdout=stdout, stderr=stderr, timeout=15)
            exit_code = child.wait(timeout=15)
            put(ROOT / "producer-timeout-tree.json",
                dict(owned_child_pid=child.pid, taskkill_exit_code=termination.returncode,
                     true_child_exit_code=exit_code, checked_at_utc=now()))
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
    require(report["risk_assumptions"] == freeze["risk_assumptions"], "Risk contract changed")
    require(report["historical_test_pristine"] is False and report["independent_future_data_required"] is True,
            "Historical diagnostic authority changed")
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
    for row in rows:
        require(row["mechanism"] == freeze["candidate_id"] and row["risk_variant"] == 0
                and row["config_fingerprint"] == freeze["candidate_config_fingerprint"]
                and row["trade_count_limit"] is None, "Diagnostic configuration differs")
        expected_cost = freeze["costs_per_leg_bps"][row["profile"]]
        require(row["fee_bps"] == expected_cost["fee"] and row["slippage_bps"] == expected_cost["slippage"],
                "Diagnostic costs differ")
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
    require(sha(PREVIOUS) == freeze["previous_ledger_file_sha256"], "Prior ledger mutated")
    require(sha(DELIVERY) == DELIVERY_SHA and
            sha(ARCHIVE / "REPLAY_DATASET_MANIFEST.json") == freeze["manifest_file_sha256"],
            "Delivery/manifest mutated")
    require(sha(args.freeze) == args.freeze_sha and sha(Path(__file__)) == freeze["wrapper_sha256"]
            and sha(ROOT / "V8_PRODUCER_PRECHECK.md") == freeze["precheck_sha256"],
            "Invocation files mutated")
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
                         profit_factor=r["profit_factor"],
                         profit_factor_status=r["profit_factor_status"],win_rate_pct=r["win_rate_pct"],
                         max_drawdown_pct=r["max_drawdown_pct"],fee_bps=r["fee_bps"],
                         slippage_bps=r["slippage_bps"],turnover_usdt=r["turnover_usdt"])
                    for r in rows]
    put(ROOT / "producer-result-summary.json",
        dict(schema="nexus.v8-first-producer-result-summary.v1",source_sha=SOURCE_SHA,
             report_digest=report["report_digest"],rows=summary_rows,
             initial_simulated_cash_usdt_per_cell=10000,owner_reference_usdt=500,
             historical_test_pristine=False,monthly_return_claim=False,
             independent_strategy_qa_complete=False,owner_demo_admission=False,
             auto_demo_promotion=False,research_only=True,live_enabled=False))
    receipt = dict(schema="nexus.v8-first-producer-receipt.v1",completed_at_utc=now(),
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

