"""Preregistered single-rule historical MR40 entry research. No execution API.

Before this implementation, the protocol was frozen in GitHub commit
07fede6ebf888c7cc8e962b409a3e27c26fcc92c.
Research-only: one candidate, no threshold search, no Paper promotion.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path

from research.nexus_mr40_one_combination_ablation_v1 import (
    STEP, canon, date_ms, inputs, scenario,
)

PRECOMMIT = "07fede6ebf888c7cc8e962b409a3e27c26fcc92c"
OHLC_SHA = "a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
LEDGER_SHA = "2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e"
CANDIDATE = {"id": "sell_pressure_close_veto", "vol_target": None,
             "initial_stop": None, "arm2": False}
DEFAULT_ROOT = Path("E:/NEXUS-Research")
DEFAULT_INPUTS = DEFAULT_ROOT / "MR40-Staged-Entry-20261022/source/inputs"
DEFAULT_LEDGER = DEFAULT_ROOT / "MR40-Entry-Quality-20261022/results/ledger.jsonl.gz"
DEFAULT_PARENT_POLICY = DEFAULT_ROOT / "MR40-Entry-Event-20261022/research/mr40_one_combination_ablation_protocol_20261022.json"


def dv(x):
    d = Decimal(str(x))
    if not d.is_finite():
        raise ValueError("nonfinite_bar")
    return d


def signal_veto(rows, j):
    """Causal CLOSED 4h signal-candle high-volume near-low veto."""
    if j < 20 or j >= len(rows):
        raise ValueError("missing_volume_history")
    o, h, l, c, v = map(dv, rows[j][1:6])
    if min(o, h, l, c) <= 0 or v < 0 or h < max(o, c) or l > min(o, c) or h < l:
        raise ValueError("invalid_ohlcv")
    past = [dv(rows[i][5]) for i in range(j - 20, j)]
    if any(p < 0 for p in past):
        raise ValueError("negative_prior_volume")
    mean = sum(past) / 20
    # Zero historical volume gives no credible relative-volume reference.
    if mean <= 0:
        raise ValueError("nonpositive_reference_volume")
    if h == l:
        return False
    return c < o and (c - l) * 5 <= (h - l) and v * 2 >= mean * 3


def filtered_reference(rows, ref):
    """Retain only the FIRST signal decision per accepted episode."""
    positions = {int(p["entry"]["signal_index"]): p for p in ref["positions"]}
    all_ids = [int(d["signal_index"]) for d in ref["decisions"]]
    if len(positions) != len(all_ids) or len(set(all_ids)) != len(all_ids):
        raise ValueError("baseline_reference_not_one_to_one")
    if set(positions) != set(all_ids):
        raise ValueError("missing_reference_position")
    kept_decisions, kept_positions, rejected = [], [], []
    for d in ref["decisions"]:
        j = int(d["signal_index"])
        if rows[j][0] != d["signal_ms"] or not d["allowed"]:
            raise ValueError("baseline_signal_spoof_or_veto")
        veto = signal_veto(rows, j)
        if veto:
            rejected.append({"signal_index": j,
                             "historical_baseline_pnl": positions[j]["net_pnl_usdt"]})
        else:
            kept_decisions.append(d)
            kept_positions.append(positions[j])
    altered = dict(ref)
    altered["decisions"] = kept_decisions
    altered["positions"] = kept_positions
    return altered, rejected


def attribution(ref, rejected):
    by_id = {int(p["entry"]["signal_index"]): p for p in ref["positions"]}
    remove_ids = {e["signal_index"] for e in rejected}
    winners = [p for p in ref["positions"] if p["net_pnl_usdt"] > 0]
    losers = [p for p in ref["positions"] if p["net_pnl_usdt"] < 0]
    lost_winners = [p for p in winners if int(p["entry"]["signal_index"]) in remove_ids]
    lost_losers = [p for p in losers if int(p["entry"]["signal_index"]) in remove_ids]
    win_total = sum(p["net_pnl_usdt"] for p in winners)
    lost_pnl = sum(p["net_pnl_usdt"] for p in lost_winners)
    return {
        "baseline_winners": len(winners), "baseline_losers": len(losers),
        "removed_winners": len(lost_winners), "removed_losers": len(lost_losers),
        "lost_winner_historical_pnl_usdt": lost_pnl,
        "avoided_loser_historical_pnl_usdt": sum(-p["net_pnl_usdt"] for p in lost_losers),
        "retained_winner_fraction": (len(winners) - len(lost_winners)) / len(winners) if winners else 1,
        "retained_winner_pnl_fraction": (win_total - lost_pnl) / win_total if win_total > 0 else 1,
        "rejected_signal_indices": sorted(remove_ids),
        "count": len(by_id),
    }


def _validate_own_protocol(config):
    if config["schema"] != "nexus.mr40.sell_pressure_close_veto.preregistered.v1":
        raise ValueError("protocol_schema_drift")
    veto = config["veto"]
    if veto["case"] != CANDIDATE["id"] or veto["min_prior_bars"] != 20:
        raise ValueError("protocol_case_or_history_drift")
    if veto["all_conditions"] != [
        "close[j] < open[j]", "high[j] > low[j]",
        "(close[j]-low[j])/(high[j]-low[j]) <= 0.20",
        "volume[j] >= 1.50 * mean(volume[j-20:j])"]:
        raise ValueError("protocol_rule_drift")
    if config["data"]["ohlc_digest"] != OHLC_SHA or config["data"]["baseline_ledger_sha256"] != LEDGER_SHA:
        raise ValueError("protocol_data_drift")
    if config["scenarios"]["capital_usdt"] != [500] or config["scenarios"]["cases"] != ["baseline", CANDIDATE["id"]]:
        raise ValueError("protocol_sweep_drift")
    if config["safety"]["live"] or config["safety"]["auto_promote"] or config["safety"]["paper500_change"]:
        raise ValueError("unsafe_protocol")


def test_gate(group, attr):
    b, c = group["baseline"], group[CANDIDATE["id"]]
    return {
        "profit_not_worse": c["net_pnl_usdt"] >= b["net_pnl_usdt"],
        "low_dd_improved_10pct": c["max_intrabar_low_bound_pct"] <= 0.9 * b["max_intrabar_low_bound_pct"],
        "winners_retained_80pct": attr["retained_winner_fraction"] >= 0.8,
        "winner_pnl_retained_90pct": attr["retained_winner_pnl_fraction"] >= 0.9,
        "losing_episode_vetoed": attr["removed_losers"] >= 1,
    }


def run(args):
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    _validate_own_protocol(protocol)
    parent, rows, refs = inputs(args.inputs, args.ledger, args.parent_protocol)
    if len(rows) != 8514 or parent["inputs"]["ohlc_digest"] != OHLC_SHA:
        raise ValueError("wrong_locked_history")
    if any(rows[i][0] - rows[i - 1][0] != STEP for i in range(1, len(rows))):
        raise ValueError("non_contiguous_4h_source")
    historical = json.loads(args.frozen.read_text(encoding="utf-8"))
    if not historical["historically_seen"] or historical["genuine_forward_oos"] or historical["promote"]:
        raise ValueError("frozen_history_auth_drift")
    ref_results = {(x["window"], x["capital"], x["profile"], x["case"]): x
                   for x in historical["cases"]}
    runs, comparisons, attribution_by_window = [], {}, {}
    for window in ("train", "evaluation"):
        a, b = parent["windows"][window]
        s = next(i for i, row in enumerate(rows) if row[0] == date_ms(a))
        end = next((i for i, row in enumerate(rows) if row[0] == date_ms(b)), len(rows))
        if s < 181 or end <= s or rows[end - 1][0] + STEP != date_ms(b):
            raise ValueError("invalid_window")
        comparisons[window] = {}
        for profile in ("normal", "stress"):
            cfg = parent["profiles"][profile]
            reference = refs[(window, 500, profile)]
            candidate_ref, rejected = filtered_reference(rows, reference)
            att = attribution(reference, rejected)
            attribution_by_window.setdefault(window, {})[profile] = att
            group = {}
            for case, source_ref, conf in (
                ("baseline", reference, parent["cases"][0]),
                (CANDIDATE["id"], candidate_ref, CANDIDATE),
            ):
                result, positions = scenario(
                    rows, source_ref, parent, conf, 500,
                    cfg["fee_bp"], cfg["slip_bp"], s, end,
                )
                if len(positions) != result["closed_positions"]:
                    raise ValueError("inconsistent_ledger")
                if case == "baseline":
                    oracle = ref_results[(window, 500, profile, "baseline")]
                    for key in ("net_pnl_usdt", "max_close_drawdown_pct",
                                "max_intrabar_low_bound_pct", "fees_usdt", "closed_positions"):
                        if not math.isclose(result[key], oracle[key], rel_tol=1e-10, abs_tol=1e-7):
                            raise ValueError("frozen_baseline_mismatch:" + key)
                group[case] = result
                runs.append({"window": window, "profile": profile, "case": case,
                             **{k: result[k] for k in (
                                 "net_pnl_usdt", "max_close_drawdown_pct",
                                 "max_intrabar_low_bound_pct", "fees_usdt",
                                 "closed_positions", "fills", "skips")}})
            comparisons[window][profile] = {
                "gate": test_gate(group, att),
                "all_pass": all(test_gate(group, att).values()),
                "delta_net_pnl_usdt": group[CANDIDATE["id"]]["net_pnl_usdt"] - group["baseline"]["net_pnl_usdt"],
                "delta_low_dd_pct_points": group[CANDIDATE["id"]]["max_intrabar_low_bound_pct"] - group["baseline"]["max_intrabar_low_bound_pct"],
            }
    result = {
        "schema": "nexus.mr40.sell_pressure_close_veto.result.v1",
        "precommitted_protocol_commit": PRECOMMIT,
        "historical_seen": True, "genuine_prospective_oos": False,
        "source_sha256": OHLC_SHA, "ledger_sha256": LEDGER_SHA,
        "real_4h_bars": len(rows), "physical_engine_scenarios": len(runs),
        "all_baseline_oracles_pass": True,
        "results": runs, "comparisons": comparisons,
        "attribution": attribution_by_window,
        "economic_gate_all_pass": all(x["all_pass"] for g in comparisons.values() for x in g.values()),
        "promote": False, "merge": False, "paper_changed": False,
        "live": False, "real_orders": 0, "private_api": False,
    }
    result["digest"] = hashlib.sha256(canon(result)).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
    return result


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--protocol", type=Path, required=True)
    cli.add_argument("--frozen", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    cli.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    cli.add_argument("--parent-protocol", type=Path, default=DEFAULT_PARENT_POLICY)
    out = run(cli.parse_args())
    print(json.dumps({
        "digest": out["digest"], "scenarios": out["physical_engine_scenarios"],
        "attribution": out["attribution"], "comparisons": out["comparisons"],
        "economic_gate_all_pass": out["economic_gate_all_pass"],
        "promote": out["promote"],
    }, sort_keys=True))
