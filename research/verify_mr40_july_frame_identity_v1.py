"""Independent, standard-library verification of the historical July frame audit."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from decimal import Decimal, localcontext
from pathlib import Path

OLD = "c75ca7e7a74c0ff3a4d51f5a12a9ac27232563a03a1a87b61b5d65851fe47cc9"
CACHED = "e510acb8cf58369880445d2c1ff6d7764234f3718e99902c31b7cf9b239dfa9e"
INPUT = "fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe"
BASELINE = "44ea00e4528ccbe3e420bd999152a36b58450565f8a45bb9489a3c79fe4b4514"
D = Decimal


def digest(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def check(ok, message):
    if not ok:
        raise ValueError(message)


def verify(frame_path, prepared_path, baseline_path, audit_path, witness_path, original_reports_path):
    frame, prepared, baseline, audit, witness = [json.loads(Path(p).read_text(encoding="utf-8"))
        for p in [frame_path, prepared_path, baseline_path, audit_path, witness_path]]
    rebuilt_hash = digest(frame)
    check(rebuilt_hash == audit["reconstructed_historical_frame_sha256"], "rebuilt frame hash")
    original_identity = rebuilt_hash == OLD
    check(audit["original_workbook_frame_reconstructed"] is original_identity, "identity claim")
    for obj, key, expected in [(prepared, "input_digest", INPUT), (baseline, "result_digest", BASELINE),
                               (audit, "audit_digest", audit["audit_digest"])]:
        check(obj[key] == expected == digest({k: v for k, v in obj.items() if k != key}), key)
    cached = [r for r in prepared["rows"] if 1782864000000 <= r[0] < 1785542400000]
    check(digest(cached) == CACHED and len(frame) == len(cached) == 186, "cached frame hash/count")
    check(witness["reported_cells"]["V34"]["value"] == OLD, "original workbook frame cell")
    check(witness["reported_cells"]["C34"]["value"] == "mean_reversion_40_m2", "workbook strategy")
    check(witness["reported_cells"]["U34"]["value"] == digest(
        {"lookback": 40, "entry_z": -2.0, "exit_z": 0.0}), "workbook parameter cell")
    source_zip = Path(original_reports_path).read_bytes()
    check(hashlib.sha256(source_zip).hexdigest() ==
          "4207545c556991960d847cc96e8bf3898a2ee63c8a729c4a74863d3a5066a716", "original report ZIP hash")
    with zipfile.ZipFile(original_reports_path) as archive:
        check(archive.testzip() is None, "original report ZIP CRC")
        core = json.loads(archive.read("monthly-report.json"))
        variants = json.loads(archive.read("ten-variants/ten-variant-report.json"))
    for report, expected in [(core, "a6d15b807e8ffc65c8b25b59f236fbfedf3ec37233e50732737654165b9d4721"),
                            (variants, "ea1fe071de2e96b14447d6985a7aa15ae14e355edf470167341d1d995428c218")]:
        check(report["result_sha256"] == expected == digest(
            {k: v for k, v in report.items() if k != "result_sha256"}), "original report digest")
        check(report["source_sha"] == "d60c063a2a79d2359538d48dd6088133c704eb8f", "report source")
    check(variants["base_report_sha256"] == core["result_sha256"], "cross-report binding")
    check(variants["archive_manifest_sha256"] == core["source_manifest_sha256"] ==
          digest(core["archive_sources"]), "original source manifest digest")
    check(len(core["rows"]) == 36 and len(variants["rows"]) == 120, "report completeness")
    old_row = next(r for r in variants["rows"] if r["strategy_id"] == "mean_reversion_40_m2"
                   and r["symbol"] == "BTCUSDT" and r["timeframe"] == "hour4")
    check(old_row["frame_sha256"] == OLD and old_row["config_sha256"] ==
          witness["reported_cells"]["U34"]["value"], "original JSON/workbook identity")
    check(old_row["net_pnl_usdt"] == witness["reported_cells"]["G34"]["value"] == 195.4101,
          "original JSON/workbook reported PnL")
    control_mapping = [
        ("full_normal", {"net_pnl_usdt": "net_pnl_usdt", "net_return_pct": "net_return_pct",
                         "max_close_drawdown_pct": "max_drawdown_pct", "fills": "fills"}),
        ("holdout_normal", {"net_return_pct": "oos_return_pct", "max_close_drawdown_pct":
                             "oos_max_drawdown_pct", "fills": "oos_fills"}),
        ("holdout_stress", {"net_return_pct": "stress_oos_return_pct", "max_close_drawdown_pct":
                             "stress_oos_max_drawdown_pct", "fills": "stress_oos_fills"})]
    for control, mapping in control_mapping:
        m = next(x for x in audit["historical_metric_controls"] if x["control"] == control)
        check(all(round(m[a], 4) == old_row[b] for a, b in mapping.items()), "original metric control")
    counts = {f: 0 for f in ["timestamp", "open", "high", "low", "close", "volume"]}
    volume_errors = []
    for i, (a, b) in enumerate(zip(frame, cached)):
        check(a[0] == b[0] == 1782864000000 + i * 14400000, "timestamps")
        for j, f in enumerate(counts):
            counts[f] += a[j] != b[j]
        check(a[:5] == b[:5], "strategy price input differs")
        volume_errors.append(abs(D(a[5]) - D(b[5])))
    check(counts == audit["differing_string_cells_by_column"], "column difference counts")
    check(max(volume_errors) == D(audit["maximum_absolute_volume_difference_btc"]), "volume difference")
    controls = []
    with localcontext() as ctx:
        ctx.prec = 50
        close = [D(r[4]) for r in frame]
        signals, state = [], 0
        for i, price in enumerate(close):
            if i >= 40:
                prior = close[i - 40:i]
                mean = sum(prior) / D(40)
                variance = sum((x - mean) ** 2 for x in prior) / D(40)
                if variance:
                    z = (price - mean) / variance.sqrt()
                    if z <= D(-2):
                        state = 1
                    elif z >= 0:
                        state = 0
            signals.append(state)
        for accepted in baseline["results"]:
            if accepted["cohort"] != "july_legacy_control":
                continue
            fee, slip = D(str(accepted["fee_bps"])) / 10000, D(str(accepted["slippage_bps"])) / 10000
            lag = accepted["execution_lag_bars"]
            cash, qty, peak, dd, fills = D(10000), D(0), D(10000), D(0), []
            for i, row in enumerate(frame):
                if i >= lag:
                    wanted = signals[i - lag]
                    ref = D(row[1])
                    if wanted and not qty:
                        qty, cash = cash / ((1 + fee) * ref * (1 + slip)), D(0)
                        fills.append((row[0], "buy", ref))
                    elif not wanted and qty:
                        cash, qty = qty * ref * (1 - slip) * (1 - fee), D(0)
                        fills.append((row[0], "sell", ref))
                equity = cash + qty * D(row[4])
                if i == 185 and qty:
                    cash, qty = qty * D(row[4]) * (1 - slip) * (1 - fee), D(0)
                    equity = cash
                    fills.append((1785542400000, "sell", D(row[4])))
                peak = max(peak, equity)
                dd = max(dd, (1 - equity / peak) * 100)
            original_fills = [(r["fill_ms"], r["side"], D(str(r["reference"])))
                              for r in accepted["fills"]]
            check(fills == original_fills, "independent Decimal fill time/side/reference mismatch")
            pnl_error = abs((cash - 10000) - D(str(accepted["net_pnl_usdt"])))
            dd_error = abs(dd - D(str(accepted["max_close_drawdown_pct"])))
            check(pnl_error < D("1e-8") and dd_error < D("1e-8"), "independent Decimal metrics")
            controls.append({"profile": accepted["profile"], "fill_count": len(fills),
                "net_pnl_usdt_decimal": str(cash - 10000), "absolute_pnl_error_usdt": str(pnl_error),
                "max_close_drawdown_pct_decimal": str(dd), "absolute_drawdown_error_pp": str(dd_error)})
    check(len(controls) == 4, "missing cost/latency controls")
    result = {"schema": "nexus.mr40-july-frame-independent-qa.v1", "decision": "computational_checks_pass",
        "audit_digest": audit["audit_digest"], "all_186_price_records_exact": True,
        "original_full_frame_identity_proven": original_identity,
        "original_156_row_json_reports_recovered_and_digests_verified": True,
        "original_report_metrics_match_reconstruction": True,
        "historical_and_cached_projected_ohlc_sha256": digest([r[:5] for r in frame]),
        "different_cells_by_column": counts, "maximum_volume_difference_btc": str(max(volume_errors)),
        "original_workbook_hash_and_parameter_cells_match": True,
        "independent_decimal_signal_bars": len(signals), "independent_decimal_controls": controls,
        "research_only": True, "orders": 0}
    result["verification_digest"] = digest(result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["frame", "prepared", "baseline", "audit", "witness", "original-reports", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    check(not a.output.exists(), "refuse to overwrite prior verification")
    result = verify(a.frame, a.prepared, a.baseline, a.audit, a.witness, a.original_reports)
    a.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
