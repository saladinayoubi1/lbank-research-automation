"""Bounded optimizer-to-real-candle MR40 parity smoke, research only.

Uses the same frozen dataset, archived decisions and original NEXUS scenario().
No broker, exchange endpoint, private keys, live orders, or new strategy search.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
from research.nexus_mr40_one_combination_ablation_v1 import (
    STEP, date_ms, inputs, scenario,
)

REPO = Path(__file__).resolve().parents[1]
BASE = Path("E:/NEXUS-Research")
INPUT_DIR = BASE / "MR40-Staged-Entry-20261022/source/inputs"
LEDGER = BASE / "MR40-Entry-Quality-20261022/results/ledger.jsonl.gz"
PROTOCOL = BASE / "MR40-Entry-Event-20261022/research/mr40_one_combination_ablation_protocol_20261022.json"
ARCHIVE = REPO / "docs/evidence/mr40-entry-event-contract-20261022/one_combination_ablation.json"
OUT = REPO / "results/mr40_optimizer_candle_smoke_20261023.json"
CASES = ("baseline", "vol40_only", "stop4_arm2_only", "vol40_stop4_arm2")
MEASURES = ("net_pnl_usdt", "max_close_drawdown_pct",
            "max_intrabar_low_bound_pct", "fees_usdt", "longest_underwater_days")
COUNTS = ("closed_positions", "stops", "stop_gaps", "ratchets", "skips")


def run() -> dict:
    policy, candles, ledger_refs = inputs(INPUT_DIR, LEDGER, PROTOCOL)
    assert len(candles) == 8514, "different candle data"
    assert tuple(case["id"] for case in policy["cases"]) == CASES, "parameter case drift"
    assert sorted(policy["capital_usdt"]) == [500, 10000], "capital contract drift"
    frozen = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    assert frozen["historically_seen"] is True and frozen["genuine_forward_oos"] is False
    assert frozen["promote"] is False and frozen["paper_changed"] is False
    oracle = {
        (x["capital"], x["window"], x["profile"], x["case"]): x
        for x in frozen["cases"]
    }
    assert len(oracle) == len(frozen["cases"]) == 32
    checked = 0
    scored = []
    for window in ("train", "evaluation"):
        start_text, stop_text = policy["windows"][window]
        start = next(i for i, row in enumerate(candles) if row[0] == date_ms(start_text))
        end = next((i for i, row in enumerate(candles) if row[0] == date_ms(stop_text)), len(candles))
        assert start >= 181 and end > start
        assert candles[end-1][0] + STEP == date_ms(stop_text)
        for profile in ("normal", "stress"):
            profile_config = policy["profiles"][profile]
            for case in policy["cases"]:
                # This is the actual NEXUS per-candle accounting simulator,
                # not a lookup into a precomputed result table.
                metrics, positions = scenario(
                    candles, ledger_refs[(window, 500, profile)],
                    policy, case, 500,
                    profile_config["fee_bp"], profile_config["slip_bp"],
                    start, end,
                )
                expected = oracle[(500, window, profile, case["id"])]
                for key in MEASURES:
                    if not math.isclose(metrics[key], expected[key], rel_tol=1e-10, abs_tol=1e-7):
                        raise AssertionError(f"candle replay parity: {window}/{profile}/{case['id']}/{key}")
                for key in COUNTS:
                    if metrics[key] != expected[key]:
                        raise AssertionError(f"event parity: {window}/{profile}/{case['id']}/{key}")
                assert len(positions) == expected["closed_positions"]
                checked += 1
                scored.append({
                    "window": window, "profile": profile, "case": case["id"],
                    "net_pnl_usdt": metrics["net_pnl_usdt"],
                    "low_drawdown_pct": metrics["max_intrabar_low_bound_pct"],
                    "close_drawdown_pct": metrics["max_close_drawdown_pct"],
                    "closed_positions": metrics["closed_positions"],
                })
    assert checked == 16
    data = {(r["window"], r["profile"], r["case"]): r for r in scored}
    # Frozen negative-screen objective only, NOT a new hypothesis search.
    scores = {
        k: data[("train", "stress", k)]["net_pnl_usdt"]
        / max(data[("train", "stress", k)]["low_drawdown_pct"], 1e-9)
        for k in CASES
    }
    chosen = max(CASES, key=lambda k: (scores[k], -CASES.index(k)))
    eval_base = data[("evaluation", "stress", "baseline")]
    eval_pick = data[("evaluation", "stress", chosen)]
    noninferior = eval_pick["net_pnl_usdt"] >= eval_base["net_pnl_usdt"]
    result = {
        "schema": "nexus.mr40.optimizer_real_candle_smoke.v1",
        "repository_head": "dcb731ba5e7e1f533ebbf022550eece661694e87",
        "mode": "RESEARCH_ONLY",
        "optimizer_backend": "bounded_deterministic_grid; Optuna installation failed on laptop",
        "real_candle_rows": len(candles),
        "source_ohlc_sha256": policy["inputs"]["ohlc_digest"],
        "baseline_ledger_sha256": policy["inputs"]["existing_ledger_sha256"],
        "frozen_results_digest": frozen["digest"],
        "cases": list(CASES), "candle_engine_scenario_runs": checked,
        "historical_parity_passed": True,
        "train_stress_scores": scores,
        "selected_case": chosen,
        "evaluation_stress_baseline": eval_base,
        "evaluation_stress_selected": eval_pick,
        "evaluation_noninferiority_passed": noninferior,
        "genuine_new_OOS": False,
        "adopt_optimizer": False, "promote_paper": False,
        "paper_changed": False, "private_api": False,
        "real_orders": 0, "live": False,
    }
    OUT.parent.mkdir(exist_ok=True)
    if OUT.exists():
        raise RuntimeError("refuse_to_overwrite_prior_result")
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
