"""Audit one immutable completed research report with the existing Decimal oracle."""
from __future__ import annotations
import hashlib
import socket
from threading import Timer
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
START = time.monotonic()

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def save(name, value):
    tmp = ROOT / (name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, ROOT / name)

def check(ok, why):
    if not ok:
        raise ValueError(why)

def git(source, *args):
    print("GIT_CHECK " + " ".join(args), flush=True)
    p = subprocess.run([read(ROOT / "audit-input.json")["git_executable"], "--no-optional-locks", "-C", str(source), *args], check=True,
                       capture_output=True, text=True, timeout=60)
    return p.stdout.strip()

def blob(path):
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

def validate_numeric_proof(proof, cfg):
    check(proof.get("qa_digest") == cfg["qa_digest"] == digest(
        {k:v for k,v in proof.items() if k != "qa_digest"}), "numeric proof digest mismatch")
    check(proof.get("schema") == "nexus.optimized-composite-independent-numeric-qa.v1" and
          proof.get("source_sha") == cfg["source_sha"] and
          proof.get("verification_source_sha") == cfg["numeric_verification_source_sha"] and
          proof.get("engine_blob_sha") == cfg["numeric_engine_blob_sha"] and
          proof.get("producer_report_digest") == cfg["report_digest"], "numeric proof source/report mismatch")
    check(proof.get("independent_numeric_comparison_complete") is True and
          proof.get("training_ranking_matches") is True and
          proof.get("full_grid_rows_compared") == 12 and
          proof.get("additional_training_cells_compared") == 4 and
          len(proof.get("cells", [])) == 16, "numeric comparison incomplete")
    check(proof.get("original_source_full_replay_complete") is False and
          proof.get("independent_decimal_accounting_complete") is False and
          proof.get("research_only") is True and
          all(proof.get(k) is False for k in ("auto_demo_promotion", "live_enabled",
              "owner_demo_admission", "official_coordinator_advanced")), "numeric proof authority/scope mismatch")
    cells = {}
    for cell in proof["cells"]:
        check(cell.get("cell_digest") == digest({k:v for k,v in cell.items() if k != "cell_digest"}),
              "numeric cell digest mismatch")
        check(cell.get("producer_source_sha") == cfg["source_sha"] and
              cell.get("verification_source_sha") == cfg["numeric_verification_source_sha"] and
              cell.get("engine_blob_sha") == cfg["numeric_engine_blob_sha"] and
              cell.get("producer_report_digest") == cfg["report_digest"] and
              cell.get("matches") is True, "numeric cell source/report mismatch")
        if cell["scope"] == "full_grid":
            key = (cell["symbol"], cell["part"], cell["profile"])
            check(key not in cells, "duplicate numeric report cell")
            cells[key] = cell
    check(len(cells) == 12, "numeric selected report grid incomplete")
    return cells


def load_reused_cells(cfg, report):
    resume = Path(cfg["resume_from"])
    check((resume/"process-exit.txt").read_text().strip() == "NATIVE_EXIT=124", "prior audit not stopped")
    check(sha(resume/"audit-input.json") == cfg["resume_input_file_sha256"] and
          sha(resume/"run-audit.py") == cfg["resume_worker_sha256"], "prior audit binding changed")
    old = read(resume/"audit-input.json")
    check(old["source_sha"] == cfg["source_sha"] and old["report_digest"] == cfg["report_digest"] and
          old["oracle_blob_sha"] == cfg["oracle_baseline_blob_sha"] and
          old["qa_digest"] == cfg["qa_digest"], "prior audit identity changed")
    rows = {(r["symbol"],r["part"],r["profile"]):r for r in report["rows"]}
    result = {}
    for path in sorted(resume.glob("cell-*.json")):
        cell = read(path)
        check(cell["cell_digest"] == digest({k:v for k,v in cell.items() if k != "cell_digest"}),
              "prior accounting cell digest mismatch")
        key = (cell["symbol"],cell["part"],cell["profile"])
        check(key in rows and key not in result, "unexpected/duplicate prior accounting cell")
        row = rows[key]
        check(cell["decision"] == "PASS_RESEARCH_ONLY" and cell["owner_demo_admission"] is False and
              cell["live_trading_authority"] is False and cell["bars"] == row["bars"] and
              cell["fee_bps"] == row["fee_bps"] and cell["slippage_bps"] == row["slippage_bps"] and
              cell["closed_round_trips"] == row["closed_round_trips"] and
              cell["verified_net_pnl_usdt"] == row["net_pnl_usdt"] and
              cell["verified_net_return_pct"] == row["net_return_pct"], "prior accounting cell metrics changed")
        result[key] = cell
    check(len(result) == cfg["reused_cells_expected"], "completed accounting cell count changed")
    return result


def main():
    cfg = read(ROOT / "audit-input.json")
    check(socket.gethostname().split(".")[0].upper() == cfg["qa_host"], "wrong QA host")
    check(cfg["qa_host"] != cfg["producer_host"], "producer and QA hosts must differ")
    check(sha(Path(__file__)) == cfg["worker_sha256"], "audit worker bytes changed")
    def deadline():
        save("deadline-receipt.json", {"status":"FAILED_CLOSED", "reason":"600-second audit deadline", **cfg["authority"]})
        os._exit(124)
    watchdog = Timer(cfg["limits"]["wall_seconds"], deadline)
    watchdog.daemon = True
    watchdog.start()
    qa = Path(cfg["qa_root"])
    source, archive = qa / "source", Path(cfg["archive_root"])
    producer = qa / "producer"
    completed = []
    authority = cfg["authority"]
    check(not (ROOT / "audit-receipt.json").exists(), "completed audit exists; no replay")
    lock = ROOT / "execution.lock"
    with lock.open("x", encoding="utf-8") as f:
        f.write(str(os.getpid()) + "\n")
    common = {"schema": "nexus.existing-composite-economic-audit.v2",
              "source_sha": cfg["source_sha"], "lease_id": cfg["lease_id"],
              "oracle_ref": cfg["oracle_ref"], "oracle_blob_sha": cfg["oracle_blob_sha"],
              "qa_host": cfg["qa_host"], "producer_host": cfg["producer_host"],
              "input_config_digest": digest(cfg), "worker_sha256": cfg["worker_sha256"], "attempt_id":cfg["attempt_id"],
              "numeric_verification_source_sha":cfg["numeric_verification_source_sha"],
              "oracle_baseline_ref":cfg["oracle_baseline_ref"],
              "oracle_baseline_blob_sha":cfg["oracle_baseline_blob_sha"],
              "oracle_repo_path":cfg["oracle_repo_path"], **authority}
    save("launch-receipt.json", {"pid":os.getpid(), "started_at_utc":datetime.now(timezone.utc).isoformat(), "timeout_seconds":600, "source_sha":cfg["source_sha"], "oracle_ref":cfg["oracle_ref"], **authority})
    def status(state, **extra):
        save("status.json", {**common, "status": state, "completed_cells": len(completed),
                            "elapsed_seconds": round(time.monotonic()-START, 3),
                            "checked_at_utc": datetime.now(timezone.utc).isoformat(), **extra})
        print(json.dumps({"status":state,"completed_cells":len(completed),"elapsed_seconds":round(time.monotonic()-START,3)}), flush=True)
    try:
        status("VERIFYING_BOUND_INPUTS")
        check(git(source, "rev-parse", "HEAD") == cfg["source_sha"], "research source SHA changed")
        check(not git(source, "status", "--porcelain"), "research source is dirty")
        check(blob(source / "nexus_composite_strategy_research.py") ==
              cfg["research_blob_sha"], "research code bytes changed")
        oracle_path = ROOT / "nexus_composite_fill_oracle.py"
        check(blob(oracle_path) == cfg["oracle_blob_sha"], "oracle source blob changed")
        for name, expected in cfg["input_file_sha256"].items():
            check(sha(producer / name) == expected, "immutable producer file changed: " + name)
        report, receipt = read(producer / "research-report.json"), read(producer / "agent-receipt.json")
        check(report["report_digest"] == cfg["report_digest"] ==
              digest({k:v for k,v in report.items() if k != "report_digest"}), "report digest mismatch")
        check(receipt["receipt_digest"] == digest(
            {k:v for k,v in receipt.items() if k != "receipt_digest"}), "producer receipt digest mismatch")
        check(report["source_sha"] == receipt["source_sha"] == cfg["source_sha"] and
              receipt["lease_id"] == cfg["lease_id"], "producer identity mismatch")
        qa_proof = read(Path(cfg["qa_proof_path"]))
        numeric_cells = validate_numeric_proof(qa_proof, cfg)
        reused = load_reused_cells(cfg, report)
        for p in (report, receipt, qa_proof):
            check(p["research_only"] is True and p["auto_demo_promotion"] is False and
                  p["live_enabled"] is False, "authority mismatch")
        check(len(report["rows"]) == cfg["limits"]["cell_count"], "research grid changed")
        files = list(archive.rglob("*.parquet"))
        actual = {sha(p): p for p in files}
        expected = cfg["parity"]["frames"]
        check(len(files) == len(actual) == len(expected) == 6 and
              set(actual) == {r["raw_file_sha256"] for r in expected}, "raw archive bytes changed")
        versions = {name:importlib.metadata.version(name) for name in cfg["runtime_pins"]}
        check(versions == cfg["runtime_pins"], "QA decoder/runtime version changed")
        sys.path[:0] = [str(source)]
        import numpy as np
        import pandas as pd
        import nexus_composite_strategy_research as research
        spec = importlib.util.spec_from_file_location("existing_decimal_oracle", oracle_path)
        oracle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(oracle)
        def prohibited(*args, **kwargs):
            raise RuntimeError("producer, tournament and numerical replay are forbidden in this audit")
        research.run = research.backtest = research._screen_frontier = prohibited
        class OfflineSocket(socket.socket):
            def connect(self, *args, **kwargs):
                raise RuntimeError("Decimal accounting audit is archive-only")
            connect_ex = connect
        socket.socket = OfflineSocket
        socket.create_connection = prohibited
        check(sha(ROOT/"check_day_cache.py") == cfg["regression_script_sha256"] and
              sha(ROOT/"scalar-decimal-goldens.json") == cfg["golden_file_sha256"], "native regression bytes changed")
        status("VERIFYING_NATIVE_DECIMAL_DAY_CACHE", raw_files_verified=6, runtime_versions=versions)
        test = subprocess.run([sys.executable,str(ROOT/"check_day_cache.py"),
            "--oracle",str(oracle_path),"--baseline",str(Path(cfg["resume_from"])/"nexus_composite_fill_oracle.py"),
            "--goldens",str(ROOT/"scalar-decimal-goldens.json"),"--receipt",str(ROOT/"native-regression-receipt.json")],
            capture_output=True,text=True,timeout=60)
        (ROOT/"native-regression.stdout.log").write_text(test.stdout,encoding="utf-8")
        (ROOT/"native-regression.stderr.log").write_text(test.stderr,encoding="utf-8")
        check(test.returncode == 0,"native Decimal day-cache regression failed")
        regression = read(ROOT/"native-regression-receipt.json")
        check(regression["exit_code"] == 0 and regression["native_windows"] is True and
              regression["pandas"] == versions["pandas"] and
              regression["cached_oracle_blob_sha"] == cfg["oracle_blob_sha"] and
              regression["golden_unrounded_decimal_and_fill_path_cases"] == 20 and
              regression["timezone_and_dst_key_cases"] == 6 and
              regression["canonical_scalar_floor_calls"] == 0,"native cache receipt mismatch")
        save("resume-binding.json",{"resume_from":cfg["resume_from"],"prior_input_sha256":cfg["resume_input_file_sha256"],
             "reused_cell_digests":[c["cell_digest"] for c in reused.values()],"planned_new_cells":12-len(reused),
             "oracle_baseline_blob_sha":cfg["oracle_baseline_blob_sha"],"oracle_cached_blob_sha":cfg["oracle_blob_sha"],
             "old_and_cached_oracle_calculation_rules_match":True,"native_regression_sha256":sha(ROOT/"native-regression-receipt.json")})
        status("BUILDING_EXISTING_CAUSAL_FEATURES",raw_files_verified=6,runtime_versions=versions,
               native_decimal_day_cache_regression_passed=True,reused_cells_expected=len(reused))
        frames = research._load_frontier_features(archive)
        selected = report["selected"]
        check(selected["fingerprint"] == receipt["config_fingerprint"], "selected config changed")
        wanted = {(s,p,c) for s in research.SYMBOLS for p in
                  ("train","validation","historically_inspected_test") for c in ("conservative","stress")}
        check({(r["symbol"],r["part"],r["profile"]) for r in report["rows"]} == wanted,
              "research grid identities changed")
        current = None
        signals = None
        frame = None
        for row in report["rows"]:
            check(time.monotonic()-START < cfg["limits"]["wall_seconds"], "audit deadline exceeded")
            if current != row["symbol"]:
                current = row["symbol"]
                frame = frames[current]
                signals = research.signal_for(frame, selected)
            n = len(frame)
            a, b = int(n * research.TRAIN_FRAC), int(n * (research.TRAIN_FRAC + research.VALID_FRAC))
            lo, hi = {"train":(0,a), "validation":(a,b),
                      "historically_inspected_test":(b,n)}[row["part"]]
            piece = frame.iloc[lo:hi].reset_index(drop=True)
            decision = signals[lo:hi]
            check(len(piece) == row["bars"] and str(piece["decision_at"].iloc[0]) ==
                  row["first_closed_utc"] and str(piece["decision_at"].iloc[-1]) ==
                  row["last_closed_utc"], "closed-candle window changed")
            fee, slip = ((research.ENTRY_FEE_BPS,research.ENTRY_SLIP_BPS)
                         if row["profile"] == "conservative" else
                         (research.STRESS_FEE_BPS,research.STRESS_SLIP_BPS))
            check(row["fee_bps"] == fee and row["slippage_bps"] == slip and
                  row["config_fingerprint"] == selected["fingerprint"] and
                  row["risk_variant"] == selected["risk_variant"], "cost/config mismatch")
            signal_digest = hashlib.sha256(np.asarray(decision, dtype=np.uint8).tobytes()).hexdigest()
            matched = numeric_cells[(current, row["part"], row["profile"])]
            check(matched["signal_digest"] == signal_digest and
                  matched["config_fingerprint"] == selected["fingerprint"] and
                  matched["bars"] == len(piece), "regenerated v6 signal/numeric identity mismatch")
            cached = reused.get((current,row["part"],row["profile"]))
            if cached is not None:
                feature_digest = hashlib.sha256(pd.util.hash_pandas_object(piece,index=True).to_numpy().tobytes()).hexdigest()
                check(cached["decision_signal_digest"] == signal_digest and
                      cached["feature_frame_digest"] == feature_digest,"reused v6 signal/feature changed")
                save(f"cell-{len(completed):02d}.json",cached)
                completed.append(cached)
                status("REUSED_VERIFIED_DECIMAL_CELL",last_cell=cached)
                continue
            proof = oracle.verify_fills(piece, decision, fee_bps=fee, slip_bps=slip,
                                        risk_variant=selected["risk_variant"], observed=row)
            check(proof["decision"] == "PASS_RESEARCH_ONLY" and
                  proof["owner_demo_admission"] is False and proof["live_trading_authority"] is False,
                  "oracle authority mismatch")
            cell = {"symbol": current, "part": row["part"], "profile": row["profile"],
                    "bars": row["bars"], "fee_bps": fee, "slippage_bps": slip,
                    "feature_frame_digest": hashlib.sha256(
                        pd.util.hash_pandas_object(piece, index=True).to_numpy().tobytes()).hexdigest(),
                    "decision_signal_digest": hashlib.sha256(
                        np.asarray(decision, dtype=np.uint8).tobytes()).hexdigest(),
                    "verified_net_pnl_usdt": row["net_pnl_usdt"],
                    "verified_net_return_pct": row["net_return_pct"], **proof}
            cell["cell_digest"] = digest(cell)
            save(f"cell-{len(completed):02d}.json", cell)
            completed.append(cell)
            status("AUDITING_DECIMAL_ACCOUNTING", last_cell=cell)
        for name, expected in cfg["input_file_sha256"].items():
            check(sha(producer/name) == expected, "producer file changed during audit")
        check(not git(source, "status", "--porcelain") and
              blob(oracle_path) == cfg["oracle_blob_sha"], "source changed during audit")
        core = {**common, "decision":"DECIMAL_ACCOUNTING_MATCHED_RESEARCH_ONLY",
                "source_simulator_called":False, "frontier_or_ledger_changed":False,
                "physical_host_independent":True, "distinct_host_accounting_qa_complete":True,
                "original_report_digest":report["report_digest"], "qa_digest":cfg["qa_digest"],
                "raw_files_verified":6, "prior_verified_decoded_input_digest":cfg["decoded_input_digest"],
                "dataset_decoder_reference_source_sha":cfg["dataset_decoder_reference_source_sha"],
                "dataset_reference_is_v6_strategy_proof":False,
                "audited_selected_report_cells":12, "challenger_training_cells_audited":0,
                "reused_verified_cells":len(reused), "new_accounting_cells_in_stage":12-len(reused),
                "native_decimal_day_cache_regression_passed":True,
                "original_source_full_replay_complete":False,
                "runtime_versions":versions, "cells":completed,
                "qualification":report["qualification"], "owner_demo_admission":False,
                "historical_test_pristine":False, "actual_exchange_fills_verified":False,
                "limitation":"Independent accounting implementation over shared canonical candles and existing signals; no independent signal or market source, pristine holdout, profitability or Demo authority."}
        final = {**core, "audit_digest":digest(core)}
        save("audit-receipt.json", final)
        status("DECIMAL_ACCOUNTING_MATCHED_RESEARCH_ONLY", audit_digest=final["audit_digest"])
        print(json.dumps({"decision":final["decision"],"cells":len(completed),
                          "audit_digest":final["audit_digest"]}), flush=True)
    except Exception as exc:
        status("FAILED_CLOSED", reason=type(exc).__name__ + ": " + str(exc))
        raise
    finally:
        watchdog.cancel()

if __name__ == "__main__":
    main()
