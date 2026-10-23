"""SHA-pinned historical diagnostic join for 47 already-seen MR40 positions.

No new parameter selection, no strategy backtest, no execution, and no
counterfactual strategy PnL. Only reusable research results are read.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from statistics import median

NAMES = {
    "structure": "structure_break_audit.json",
    "volume": "entry_volume_audit.json",
    "adverse": "mr40_all47_adverse_event_timing_20261022.json",
    "unarmed": "mr40_unarmed_adverse_risk_source_join_20261023.json",
}
PROTOCOL = "mr40_cross_evidence_47_entry_diagnosis_protocol_20261023.json"
OUTPUT = "mr40_cross_evidence_47_entry_diagnosis_20261023.json"


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_ms(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("utc_time_missing_offset")
    return int(dt.timestamp() * 1000)


def unique_index(rows, key, label):
    result = {}
    for row in rows:
        k = key(row)
        if k in result:
            raise ValueError("duplicate_" + label + "_" + str(k))
        result[k] = row
    return result


def compatible_pnl(a, b):
    return abs(Decimal(str(a)) - Decimal(str(b))) <= Decimal("0.0000001")


def load_locked(root):
    p = json.loads((root / "research" / PROTOCOL).read_bytes())
    if (p.get("schema") != "nexus.mr40.cross_evidence_47_entry_diagnosis.protocol.v1"
        or p.get("seen_sample") != {"train": 25, "evaluation": 22, "total": 47, "oos": False}
        or p.get("safety", {}).get("promote") is not False
        or p.get("safety", {}).get("orders") != 0):
        raise ValueError("frozen_diagnostic_protocol_drift")
    expected = p["input_files"]
    if set(expected) != set(NAMES.values()):
        raise ValueError("input_list_mismatch")
    sources = {}
    for name, file in NAMES.items():
        src = root / "results" / file
        if sha(src) != expected[file]:
            raise ValueError("input_sha256_drift_" + name)
        sources[name] = json.loads(src.read_bytes())
    return p, sources


def inspect(root):
    protocol, sources = load_locked(root)
    structural, vol, adverse, unarmed = (
        sources["structure"], sources["volume"], sources["adverse"], sources["unarmed"]
    )
    if len(adverse["per_position"]) != 47:
        raise ValueError("expected_47_adverse_positions")
    adverse_by_id = unique_index(adverse["per_position"],
                                 lambda x: (x["window"], x["entry_signal_index"]),
                                 "adverse_signal")
    trade_rows = []
    for window, expected, wins, losses in (("train", 25, 19, 6),
                                           ("evaluation", 22, 18, 4)):
        s = structural["windows"][window]["entry_records"]
        v = vol["windows"][window]["entries"]
        if len(s) != expected or len(v) != expected:
            raise ValueError("cohort_count_drift_" + window)
        vb = unique_index(v, lambda x: x["signal_index"], "volume_signal")
        sb = unique_index(s, lambda x: x["signal_index"], "structure_signal")
        if set(sb) != set(vb):
            raise ValueError("cross_study_signal_identity_drift_" + window)
        for signal_idx, st in sorted(sb.items()):
            vo = vb[signal_idx]
            ad = adverse_by_id.get((window, signal_idx))
            if ad is None:
                raise ValueError("adversity_signal_missing")
            if not (st["entry_utc_ms"] == vo["entry_ms"] ==
                    utc_ms(ad["entry_open_utc"])):
                raise ValueError("entry_timestamp_drift_" + str(signal_idx))
            if not compatible_pnl(st["realized_historical_baseline_pnl_usdt"],
                                  vo["realized_pnl_usdt"]):
                raise ValueError("realized_pnl_cross_study_drift")
            winning = Decimal(str(st["realized_historical_baseline_pnl_usdt"])) > 0
            if (winning != vo["realized_winner"] or
                    winning != (st["label"] == "winner")):
                raise ValueError("label_cross_study_drift")
            br = ad["first_threshold_breach"].get("5")
            trade_rows.append({
                "window": window, "signal_index": signal_idx,
                "entry_open_utc": ad["entry_open_utc"],
                "prior30_low_break": st["prior_30_low_break"],
                "relative_base_volume_30": vo["relative_base_volume_30"],
                "signed_candle_volume_proxy": vo["signed_candle_volume_proxy"],
                "historical_result_label": st["label"],
                "historical_baseline_PnL_10k_normal_USDT":
                    st["realized_historical_baseline_pnl_usdt"],
                "held_hours": ad["held_hours"],
                "held_low_MAE_pct": ad["whole_position_adverse_price_MAE_pct"],
                "first_5pct_low_breach_band": br["band"] if br else None,
                "unarmed_loss_before_2pct_profitable_close": None
            })
        subset = [r for r in trade_rows if r["window"] == window]
        if (sum(r["historical_result_label"] == "winner" for r in subset) != wins
                or sum(r["historical_result_label"] == "loser" for r in subset) != losses):
            raise ValueError("winner_loser_count_drift")
        lowbreak = [r for r in subset if r["prior30_low_break"]]
        if (sum(r["historical_result_label"] == "winner" for r in lowbreak)
                != structural["windows"][window]["flagged_winners"]
                or sum(r["historical_result_label"] == "loser" for r in lowbreak)
                != structural["windows"][window]["flagged_losers"]):
            raise ValueError("published_break_count_drift")
    if len(adverse_by_id) != 47:
        raise ValueError("adverse_ids_not_exhausted")
    record_by_id = unique_index(trade_rows,
                                lambda r: (r["window"], utc_ms(r["entry_open_utc"])),
                                "rejoined_entry")
    unarmed_count = 0
    for window in ("train", "evaluation"):
        episodes = unarmed["windows"][window]["episodes"]
        if len(episodes) != unarmed["windows"][window]["unarmed_prior_baseline_losers"]:
            raise ValueError("unarmed_prior_loss_count_drift")
        for ep in episodes:
            row = record_by_id.get((window, utc_ms(ep["entry_open_utc"])))
            if row is None or row["historical_result_label"] != "loser":
                raise ValueError("unarmed_loser_not_a_baseline_loser")
            if row["unarmed_loss_before_2pct_profitable_close"] is not None:
                raise ValueError("duplicate_unarmed_loss")
            row["unarmed_loss_before_2pct_profitable_close"] = True
            unarmed_count += 1
    if len(trade_rows) != 47 or unarmed_count != 8:
        raise ValueError("joint_47_or_unarmed_8_drift")
    summary = {}
    for window in ("train", "evaluation", "all_47"):
        subset = [r for r in trade_rows if window == "all_47" or r["window"] == window]
        winners = [r for r in subset if r["historical_result_label"] == "winner"]
        losers = [r for r in subset if r["historical_result_label"] == "loser"]
        flagged = [r for r in subset if r["prior30_low_break"]]
        lost_winner_pnl = sum((Decimal(str(r["historical_baseline_PnL_10k_normal_USDT"]))
                               for r in flagged if r["historical_result_label"] == "winner"),
                              Decimal(0))
        summary[window] = {
            "positions": len(subset), "winners": len(winners), "losers": len(losers),
            "structural_break_flagged_winners": sum(r in winners for r in flagged),
            "structural_break_flagged_losers": sum(r in losers for r in flagged),
            "historical_winner_PnL_exposed_to_break_filter_USDT":
                str(lost_winner_pnl),
            "median_held_low_MAE_winners_pct":
                float(median(Decimal(r["held_low_MAE_pct"]) for r in winners)),
            "median_held_low_MAE_losers_pct":
                float(median(Decimal(r["held_low_MAE_pct"]) for r in losers)),
            "median_relative_volume_winners":
                float(median(r["relative_base_volume_30"] for r in winners)),
            "median_relative_volume_losers":
                float(median(r["relative_base_volume_30"] for r in losers)),
            "unarmed_losers": sum(r["unarmed_loss_before_2pct_profitable_close"] is True
                                 for r in losers),
            "unarmed_losers_with_5pct_held_low":
                sum((r["unarmed_loss_before_2pct_profitable_close"] is True and
                     r["first_5pct_low_breach_band"] is not None) for r in losers),
            "largest_historical_loser_USDT":
                min(r["historical_baseline_PnL_10k_normal_USDT"] for r in losers),
        }
    output = {
        "schema": "nexus.mr40.cross_evidence_47_entry_diagnosis.v1",
        "preregistered_protocol_sha256": sha(root / "research" / PROTOCOL),
        "source_SHA256": protocol["input_files"],
        "historic_seen_47_not_OOS": True,
        "realized_PnL_only_retrospective_baseline_10k_normal": True,
        "causal_or_predictive_claim": False, "new_filter_or_threshold": False,
        "recompounded_filtered_equity": False,
        "independent_actual_stop_or_fill": False,
        "summary": summary, "entries": trade_rows,
        "decision": "DESCRIPTIVE_ONLY_NO_PROMOTE",
        "safety": protocol["safety"],
    }
    output["digest"] = hashlib.sha256(canon(output)).hexdigest()
    return output


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    args = p.parse_args()
    output = inspect(args.root)
    dest = args.root / "results" / OUTPUT
    if dest.exists():
        raise FileExistsError("refuse_overwrite_existing_diagnostic")
    created = False
    try:
        with dest.open("xb") as handle:
            created = True
            handle.write(json.dumps(output, sort_keys=True, indent=2,
                                    ensure_ascii=False, allow_nan=False).encode("utf-8"))
            handle.write(b"\n")
    except OSError:
        # Delete only our own newly-created incomplete file, never one from
        # another writer; power-loss atomicity is not guaranteed.
        if created and dest.exists():
            dest.unlink()
        raise
    print(json.dumps({
        "schema": output["schema"], "digest": output["digest"],
        "file_sha256": sha(dest), "summary": output["summary"],
        "paper_changed": False, "live": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
