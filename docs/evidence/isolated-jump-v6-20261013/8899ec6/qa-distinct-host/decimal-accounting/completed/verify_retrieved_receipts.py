from pathlib import Path
import hashlib, json
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
AUDIT = HERE.parent

def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def check(ok, reason):
    if not ok:
        raise ValueError(reason)

# read_file normalizes lines; restore each native writer's newline convention.
for name in ("audit-receipt.json", "resume-binding.json", "launch-receipt.json",
             "terminal-status.json", "native-regression-receipt.json", "process-exit.txt"):
    path = HERE / name
    content = path.read_text().rstrip() + "\n"
    if name == "native-regression-receipt.json":
        # The Windows harness used Path.write_text without a newline override.
        path.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))
    else:
        path.write_text(content, encoding="utf-8", newline="\n")

proof = read(HERE / "audit-receipt.json")
cfg = read(AUDIT / "audit-input-resume.json")
report = read(BASE / "research-report.json")
numeric = read(BASE / "final-numeric-qa/qa-evidence.json")
status = read(HERE / "terminal-status.json")
binding = read(HERE / "resume-binding.json")
regression = read(HERE / "native-regression-receipt.json")
launch = read(HERE / "launch-receipt.json")

check(proof["audit_digest"] == digest({k:v for k,v in proof.items() if k != "audit_digest"}),
      "audit digest changed")
check(proof["audit_digest"] == "13a16e4d308c94ab804706505c95dd1ae59d61ae735a12475b5ed323a488855f",
      "unexpected audit digest")
check(report["report_digest"] == digest({k:v for k,v in report.items() if k != "report_digest"}),
      "original report digest changed")
check(numeric["qa_digest"] == digest({k:v for k,v in numeric.items() if k != "qa_digest"}),
      "numeric proof digest changed")
check(proof["qa_digest"] == cfg["qa_digest"] == numeric["qa_digest"] and
      proof["original_report_digest"] == cfg["report_digest"] == report["report_digest"],
      "report or numeric binding mismatch")
check(proof["input_config_digest"] == digest(cfg) and
      proof["worker_sha256"] == cfg["worker_sha256"] == sha(AUDIT/"run-audit-resume.py"),
      "worker or configuration mismatch")
check(sha(AUDIT/"audit-input-resume.json") ==
      "094ad00eb0440fd736422585ae77052e6235d392fa2d2070a32121a9d354da2a", "input bytes changed")
for key in ("source_sha", "oracle_ref", "oracle_blob_sha", "oracle_baseline_ref",
            "oracle_baseline_blob_sha", "oracle_repo_path", "numeric_verification_source_sha",
            "producer_host", "qa_host"):
    check(proof[key] == cfg[key], "source binding changed: " + key)
check(proof["source_sha"] == "8899ec6bec4927fc39795f2867be91e2431178c6" and
      proof["qa_host"] != proof["producer_host"] and proof["physical_host_independent"] is True,
      "study or distinct-host identity changed")
for item in (proof, status, launch):
    check(item["research_only"] is True and all(item[k] is False for k in
        ("live_enabled", "auto_demo_promotion", "official_coordinator_advanced")),
        "research authority changed")
for key in ("owner_demo_admission", "original_source_full_replay_complete",
            "historical_test_pristine", "actual_exchange_fills_verified",
            "source_simulator_called", "frontier_or_ledger_changed", "dataset_reference_is_v6_strategy_proof"):
    check(proof[key] is False, "scope expanded: " + key)
check(proof["qualification"] == report["qualification"] ==
      "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT", "qualification changed")
check(proof["runtime_versions"] == cfg["runtime_pins"] and
      proof["raw_files_verified"] == 6 and proof["distinct_host_accounting_qa_complete"] is True,
      "input/runtime checks incomplete")
check(proof["audited_selected_report_cells"] == len(proof["cells"]) == 12 and
      proof["challenger_training_cells_audited"] == 0 and
      proof["reused_verified_cells"] == 3 and proof["new_accounting_cells_in_stage"] == 9,
      "accounting scope mismatch")

key = lambda row: (row["symbol"], row["part"], row["profile"])
rows = {key(r):r for r in report["rows"]}
numeric_rows = {key(r):r for r in numeric["cells"] if r["scope"] == "full_grid"}
wanted = {(s,p,c) for s in ("BTCUSDT","ETHUSDT") for p in
          ("train","validation","historically_inspected_test") for c in ("conservative","stress")}
check(len(rows) == len(numeric_rows) == 12 and set(rows) == wanted, "frozen grid mismatch")
seen = set()
for cell in proof["cells"]:
    ident = key(cell)
    check(ident not in seen and ident in wanted, "duplicate or unexpected accounting cell")
    seen.add(ident)
    row, num = rows[ident], numeric_rows[ident]
    check(cell["cell_digest"] == digest({k:v for k,v in cell.items() if k != "cell_digest"}),
          "accounting cell digest mismatch")
    for field in ("bars","fee_bps","slippage_bps","closed_round_trips"):
        check(cell[field] == row[field], "original report field mismatch: " + field)
    check(cell["verified_net_pnl_usdt"] == row["net_pnl_usdt"] and
          cell["verified_net_return_pct"] == row["net_return_pct"], "original returns changed")
    check(cell["decision_signal_digest"] == num["signal_digest"] and
          num["config_fingerprint"] == row["config_fingerprint"] == report["selected"]["fingerprint"],
          "signal/configuration changed")
    check(cell["decision"] == "PASS_RESEARCH_ONLY" and cell["owner_demo_admission"] is False and
          cell["live_trading_authority"] is False, "cell authority changed")
    check(len(cell["feature_frame_digest"]) == 64 and
          cell["evaluated_fills"] == cell["closed_round_trips"] * 2, "cell evidence malformed")
check(seen == wanted, "missing accounting cell")
reused = [read(AUDIT/f"v6-cell-{i:02d}.json") for i in range(3)]
check(proof["cells"][:3] == reused and
      binding["reused_cell_digests"] == [c["cell_digest"] for c in reused],
      "reused original scalar cells changed")
check(binding["prior_input_sha256"] == cfg["resume_input_file_sha256"] and
      binding["planned_new_cells"] == 9 and binding["old_and_cached_oracle_calculation_rules_match"] is True,
      "resume binding mismatch")
check(binding["native_regression_sha256"] == sha(HERE/"native-regression-receipt.json"),
      "native regression receipt bytes changed")
check(regression["exit_code"] == 0 and regression["native_windows"] is True and
      regression["host"] == cfg["qa_host"] and regression["pandas"] == cfg["runtime_pins"]["pandas"] and
      regression["golden_unrounded_decimal_and_fill_path_cases"] == 20 and
      regression["timezone_and_dst_key_cases"] == 6 and regression["canonical_scalar_floor_calls"] == 0 and
      regression["only_day_cache_ast_changes"] is True and
      regression["object_fallback_matches_baseline"] is True, "native regression incomplete")
oracle = (AUDIT/"nexus_composite_fill_oracle_day_cache.py").read_bytes()
check(regression["cached_oracle_sha256"] == hashlib.sha256(oracle).hexdigest() and
      regression["cached_oracle_blob_sha"] == cfg["oracle_blob_sha"] ==
      hashlib.sha1(b"blob " + str(len(oracle)).encode() + b"\0" + oracle).hexdigest(),
      "cached oracle bytes changed")
check(status["status"] == proof["decision"] == "DECIMAL_ACCOUNTING_MATCHED_RESEARCH_ONLY" and
      status["completed_cells"] == 12 and status["audit_digest"] == proof["audit_digest"] and
      status["input_config_digest"] == proof["input_config_digest"], "terminal status mismatch")
check((HERE/"process-exit.txt").read_text().strip() == "NATIVE_EXIT=0", "native exit not zero")
output = (HERE/"native-process-output.txt").read_text()
check('"native_exit_code":0' in output and proof["audit_digest"] in output and
      "Process completed with exit code 0" in output, "native output mismatch")
receipt = {"schema":"nexus.retrieved-decimal-accounting-proof-verification.v1",
    "checked_at_utc":datetime.now(timezone.utc).isoformat(), "result":"PASS",
    "audit_digest":proof["audit_digest"], "all_12_cell_digests_match":True,
    "original_report_metrics_match":True, "numeric_proof_signal_bindings_match":True,
    "three_original_scalar_cells_unchanged":True, "new_decimal_cells":9,
    "native_regression_receipt_hash_matches":True, "native_exit_code":0,
    "worker_config_source_and_oracle_bindings_match":True,
    "original_source_full_strict_replay_complete":False,
    "challenger_training_accounting_cells":0, "backtests_run_in_readback":0,
    "accounting_recalculations_in_readback":0, "research_only":True,
    "owner_demo_admission":False, "live_enabled":False}
(HERE/"retrieved-proof-verification.json").write_text(
    json.dumps(receipt,sort_keys=True,indent=2)+"\n", encoding="utf-8", newline="\n")
print(json.dumps(receipt,sort_keys=True))
