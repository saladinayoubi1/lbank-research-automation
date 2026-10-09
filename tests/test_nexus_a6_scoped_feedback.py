"""A6 data may be observed without replaying or qualifying its mechanism."""
import hashlib
import json
import shutil
from pathlib import Path

from nexus_strategy_discovery_feedback import empty_state, reviewed_local_data_feedback
from scripts.nexus_strategy_discovery_controller import build_status

ROOT = Path(__file__).resolve().parents[1]


def test_scoped_local_rejection_does_not_fabricate_run_or_clear_exhaustion():
    before = empty_state()
    result = reviewed_local_data_feedback(ROOT)
    assert not result["rejected"]
    row, = result["observations"]
    assert row["outcome"] == "rejected_data_verified_no_promotion"
    assert row["data_scope"]["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert row["counts_as_new_research_cycle"] is False
    assert row["global_frontier_capability_granted"] is False
    assert "run_id" not in row
    assert empty_state() == before
    core = {k:v for k,v in row.items() if k != "feedback_sha256"}
    assert row["feedback_sha256"] == hashlib.sha256(json.dumps(
        core,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    assert build_status(ROOT)["verified_local_data_feedback"] == result


def test_broken_proof_is_not_a_controller_data_claim(tmp_path):
    shutil.copytree(ROOT/"product_ui/research-reports", tmp_path/"product_ui/research-reports")
    path = tmp_path/"product_ui/research-reports/a6-signed-trade-flow-proof.json"
    proof = json.loads(path.read_text())
    proof["market"] = "linear"
    path.write_text(json.dumps(proof))
    result = reviewed_local_data_feedback(tmp_path)
    assert not result["observations"]
    assert result["rejected"][0]["id"] == "A6"
