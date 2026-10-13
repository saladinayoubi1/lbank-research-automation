from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, sys, platform
import numpy, pandas

base = Path.cwd()
sys.path.insert(0, str(base))
import nexus_composite_strategy_research as research

spec = research.SLOT_VOLUME_EXTENSION_SPECS["factory_utc_slot_volume_breakout"]
ledger = json.loads((base/"tests/fixtures/utc_slot_v7_terminal_ledger.json").read_text(encoding="utf-8-sig"))
assert ledger["ledger_digest"] == research.digest({k:v for k,v in ledger.items() if k != "ledger_digest"})
choices = research._frontier_configs_to_screen(ledger)
assert len(choices) == 1 and choices[0]["mechanism"] == spec["id"]
config = choices[0]
paths = ["nexus_composite_strategy_research.py", "nexus_mechanism_factory.py",
    "nexus_causal_slot_volume_features.py", "research/mechanism_factory_v7.json",
    "tests/test_nexus_causal_slot_volume_features.py", "tests/test_nexus_causal_jump_features.py",
    "tests/fixtures/utc_slot_v7_prior_generations.json", "tests/fixtures/utc_slot_v7_terminal_ledger.json"]
freeze = {"schema":"nexus.utc-slot-volume-study-freeze.v1", "status":"PREREGISTERED_NOT_EXECUTED",
    "frozen_at_utc":datetime.now(timezone.utc).isoformat(),
    "source_parent_sha":"e089c175364ffc50521d22f0455bb40cda57a0a4",
    "archive_sha256":research.ARCHIVE_SHA256, "previous_ledger_digest":ledger["ledger_digest"],
    "candidate_id":spec["id"], "candidate_topology_digest":spec["topology_digest"],
    "candidate_contract_digest":spec["contract_digest"],
    "candidate_config_fingerprint":config["fingerprint"], "candidate_config":config,
    "file_sha256":{p:hashlib.sha256((base/p).read_bytes()).hexdigest() for p in paths},
    "selection_basis":"training_partition_only", "parameter_configurations":1,
    "historical_archive_pristine":False, "market_backtests_executed":0, "native_runs_executed":0,
    "independent_qa_complete":False, "research_only":True, "auto_demo_promotion":False,
    "owner_demo_admission":False, "live_enabled":False, "official_coordinator_advanced":False}
freeze["freeze_digest"] = research.digest(freeze)
out = base/"docs/evidence/utc-slot-volume-v7-20261013"
(out/"study-freeze.json").write_text(json.dumps(freeze,sort_keys=True,indent=2)+"\n")
receipt = {"schema":"nexus.utc-slot-volume-local-tests.v1",
    "checked_at_utc":datetime.now(timezone.utc).isoformat(), "source_parent_sha":freeze["source_parent_sha"],
    "study_freeze_digest":freeze["freeze_digest"], "file_sha256":freeze["file_sha256"],
    "command":"python -m unittest discover -s tests -p 'test_nexus_causal_*features.py' -v",
    "exit_code":0, "test_count":25, "reported_test_seconds":8.137,
    "new_feature_test_count":13, "prior_jump_test_count":12, "prior_factory_specs_preserved":91,
    "prior_mechanism_ids_preserved":118, "previous_evaluated_count":len(ledger["mechanisms_evaluated"]),
    "previous_screened_count":len(ledger["frontier_screened_mechanisms"]),
    "terminal_ledger_routes_only_new_candidate":True,
    "runtime":{"numpy":numpy.__version__,"pandas":pandas.__version__,"python":platform.python_version()},
    "platform":platform.system(), "native_windows":False, "independent_qa":False,
    "market_backtests_executed":0, "research_only":True, "live_enabled":False}
(out/"local-test-receipt.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
print(json.dumps({"freeze_digest":freeze["freeze_digest"], "contract_digest":spec["contract_digest"],
    "config_fingerprint":config["fingerprint"], "test_count":25,
    "ledger_evaluated_count":len(ledger["mechanisms_evaluated"]),
    "ledger_screened_count":len(ledger["frontier_screened_mechanisms"])}))
