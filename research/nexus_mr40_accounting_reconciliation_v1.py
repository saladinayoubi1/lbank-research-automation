"""Independent, READ-ONLY accounting reconciliation from the existing MR40 ledger.

No new strategy signals, fills, or backtests. Published baseline equity and
drawdown measurements are independently recomputed from frozen prior fills
and 4h candle closes/lows. No orders or private APIs.
"""
import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path

SOURCE_LEDGER_SHA = "2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e"
OHLC_SHA = "a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
LOT = D("0.00001")
Q = D("0.00000001")
STEP = 14_400_000


def must(pred, reason):
    if not pred:
        raise ValueError(reason)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as inp:
        for part in iter(lambda: inp.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def canon(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def load_rows(folder):
    a = json.loads((folder / "bybit_prepared_inputs.json").read_bytes())["rows"]
    b = json.loads((folder / "bybit_october_input_extension.json").read_bytes())["rows"]
    rows = a + b
    must(hashlib.sha256(canon(rows)).hexdigest() == OHLC_SHA, "frozen_OHLC_changed")
    return rows


def read_input(ledger_path, results_path, policy_path):
    must(sha256_file(ledger_path) == SOURCE_LEDGER_SHA, "ledger_SHA_mismatch")
    report = json.loads(results_path.read_bytes())
    summary_digest = report.pop("digest")
    must(hashlib.sha256(canon(report)).hexdigest() == summary_digest,
         "recorded_metrics_logical_digest_invalid")
    must(report["schema"] == "mr40.entry-quality.results.v1", "wrong_metric_schema")
    must(report["paper_changed"] is False, "paper_mutation_report")
    protocol = json.loads(policy_path.read_bytes())
    must(protocol["schema"] == "nexus.mr40.frozen-accounting-reconciliation.v1", "protocol_schema")
    must(protocol["frozen_sources"]["baseline_ledger_sha256"] == SOURCE_LEDGER_SHA,
         "protocol_ledger_hash_changed")
    must(protocol["frozen_sources"]["market_4h_rows_sha256"] == OHLC_SHA,
         "protocol_market_hash_changed")
    must(protocol["fixed_cases"] == {
        "venue":"Bybit", "strategy":"baseline",
        "windows":["train","evaluation","full"],
        "capitals":[10000,500], "profiles":["normal","stress","lag"]
    }, "protocol_case_drift")
    ledger = {}
    with gzip.open(ledger_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            x = json.loads(line)
            k = x["key"]
            if k["venue"] != "Bybit" or k["case"] != "baseline":
                continue
            key = (k["window"], int(k["capital"]), k["profile"])
            must(key not in ledger, "duplicate_ledger_case")
            ledger[key] = x
    metrics = {}
    for x in report["rows"]:
        if x["venue"] == "Bybit" and x["case"] == "baseline":
            key = (x["window"], int(x["capital"]), x["profile"])
            must(key not in metrics, "duplicate_metrics_case")
            metrics[key] = x
    must(set(ledger) == set(metrics), "ledger_metrics_key_mismatch")
    must(len(ledger) == 18, "expected_exactly_18_frozen_cases")
    return ledger, metrics


def ms(date):
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp() * 1000)


WINDOWS = {
    "train": ("2023-01-01", "2025-01-01"),
    "evaluation": ("2025-01-01", "2026-10-20"),
    "full": ("2023-01-01", "2026-10-20"),
}
PROFILES = {"normal":(10,5,1), "stress":(25,15,1), "lag":(10,5,2)}


def replay(rows, ledger, expected, key):
    window, capital_int, profile = key
    capital = D(capital_int)
    dates = WINDOWS[window]
    start = next((i for i,r in enumerate(rows) if r[0] == ms(dates[0])), -1)
    end = next((i for i,r in enumerate(rows) if r[0] == ms(dates[1])), -1)
    must(start >= 181 and end > start, "missing_window_boundaries")
    must(all(rows[i+1][0] - rows[i][0] == STEP for i in range(start,end-1)),
         "missing_4h_bars")

    fee_bp, slip_bp, lag = PROFILES[profile]
    fee = D(fee_bp) / D(10000)
    slip = D(slip_bp) / D(10000)
    by_bar = defaultdict(list)
    for f in ledger["fills"]:
        i = f["bar_index"]
        must(start <= i < end, "fill_outside_window")
        by_bar[i].append(f)

    cash, held = capital, D(0)
    entry_cash_before, entry_price, entry_index = None,None,None
    fees_sum = D(0)
    positions_reconstructed = []
    curve, low_curve = [], []
    peak, max_close_dd, max_low_dd = float(capital),0.0,0.0
    underwater, longest = 0,0

    for i in range(start,end):
        row = rows[i]
        op, high, low, close = map(lambda v: D(str(v)), row[1:5])
        must(op > 0 and close > 0 and high >= max(op, close)
             and low <= min(op, close) and low > 0, "invalid_ohlc")
        for f in by_bar[i]:
            buy = f["side"] == "buy"
            qty = D(str(f["quantity"]))
            ref = D(str(f["reference"]))
            expect_ref = close if f["reason"] == "terminal_close" else op
            must(ref == expect_ref, "reference_not_frozen_open_or_terminal_close")
            price = (ref * (D(1) + slip if buy else D(1)-slip)).quantize(Q)
            notional = (qty * price).quantize(Q)
            commission = (notional * fee).quantize(Q)
            must(qty > 0 and qty % LOT == 0, "invalid_lot_quantity")
            must(all(D(str(f[name])) == amount for name,amount in [
                ("price",price),("notional",notional),("fee",commission),("cash_before",cash)]),
                "trade_cost_or_before_cash_drift")
            if f["reason"] == "terminal_close":
                must(not buy and i == end - 1 and f["signal_index"] is None,
                     "illegal_terminal_close")
            else:
                j = f["signal_index"]
                must(j == i-lag and rows[j][0] + STEP <= row[0],
                     "future_signal_or_wrong_delay")
            if buy:
                must(not held and f["reason"] == "episode_entry", "unexpected_buy_reason")
                max_qty=(cash/(price*(D(1)+fee))/LOT).to_integral_value(rounding=ROUND_DOWN)*LOT
                while max_qty >= LOT:
                    n=(max_qty*price).quantize(Q)
                    fc=(n*fee).quantize(Q)
                    if n+fc <= cash: break
                    max_qty-=LOT
                must(max_qty == qty, "all_in_sizing_reconstruction_failed")
                entry_cash_before = cash
                entry_price, entry_index = price,i
                held += qty
                cash -= notional+commission
            else:
                must(held == qty and f["reason"] in ("natural_exit","terminal_close"),
                     "unexpected_sell_or_size")
                cash += notional-commission
                positions_reconstructed.append({
                    "entry_index":entry_index,"exit_index":i,
                    "net_pnl":cash-entry_cash_before
                })
                held=D(0)
                entry_cash_before, entry_price, entry_index = None,None,None
            must(cash == D(str(f["cash_after"])) and cash >= 0,"after_cash_drift")
            fees_sum += commission

        mark = float(cash + held * close)
        low_mark = float(cash + held * low)
        low_curve.append(low_mark)
        max_low_dd = max(max_low_dd,max(0.0,100*(1-low_mark/peak)))
        peak = max(peak,mark)
        max_close_dd=max(max_close_dd,100*(1-mark/peak))
        underwater=underwater+1 if mark < peak - 1e-8 else 0
        longest=max(longest,underwater)
        curve.append(mark)

    must(held == 0, "unexpected_open_position_after_window")
    must(len(positions_reconstructed) == len(ledger["positions"]), "position_count_mismatch")
    for calc,p in zip(positions_reconstructed,ledger["positions"]):
        must(calc["entry_index"] == p["entry"]["bar_index"] and
             calc["exit_index"] == p["exit"]["bar_index"], "position_pair_drift")
        must(abs(calc["net_pnl"]-D(str(p["net_pnl_usdt"]))) <= D("0.00000001"),
             "trade_net_pnl_drift")
    computed_pnl=float(cash)-capital_int
    must(abs(computed_pnl-sum(float(p["net_pnl_usdt"]) for p in ledger["positions"])) <= 1e-6,
         "closed_trade_pnl_sum_drift")
    computed_equity_sha=hashlib.sha256(canon([format(x,".6f") for x in curve])).hexdigest()
    must(computed_equity_sha == ledger["equity_digest"],"close_curve_digest_mismatch")

    observed={
        "net_pnl_usdt": computed_pnl,
        "max_close_drawdown_pct": max_close_dd,
        "max_intrabar_low_bound_pct": max_low_dd,
        "longest_underwater_days":longest/6,
        "fees_usdt":float(fees_sum),
        "closed_positions":len(positions_reconstructed),
        "fills":len(ledger["fills"])
    }
    for name,value in observed.items():
        tol=1e-6 if name not in ("closed_positions","fills") else 0
        must(abs(value-expected[name])<=tol,"published_"+name+"_parity_failed")
    return {
        "window":window,"capital":capital_int,"profile":profile,
        "trades":len(positions_reconstructed),
        "pnl_usdt":round(computed_pnl,8),
        "close_dd_pct":round(max_close_dd,8),
        "intrabar_low_dd_bound_pct":round(max_low_dd,8),
        "equity_sha256":computed_equity_sha,
        "all_checks_pass":True,
    }


def main():
    a=argparse.ArgumentParser()
    for name in ("inputs","ledger","results","protocol","output"):
        a.add_argument("--"+name,required=True,type=Path)
    args=a.parse_args()
    must(not args.output.exists(),"refuse_overwrite")
    rows=load_rows(args.inputs)
    ledger,metrics=read_input(args.ledger,args.results,args.protocol)
    results=[replay(rows,ledger[key],metrics[key],key) for key in sorted(ledger)]
    out={
        "schema":"nexus.mr40.frozen-accounting-reconciliation.results.v1",
        "cases":len(results),
        "all_pass":all(x["all_checks_pass"] for x in results),
        "historically_seen":True,
        "new_backtest":False,
        "strategy_edge_proven":False,
        "paper_changed":False,
        "merge":False,
        "promote":False,
        "sources":{"ledger_sha256":SOURCE_LEDGER_SHA,"ohlc_sha256":OHLC_SHA},
        "results":results,
    }
    out["digest"]=hashlib.sha256(canon(out)).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"cases":len(results),"passed":out["all_pass"],"digest":out["digest"],
                      "train_10k_normal":next(x for x in results if (x["window"],x["capital"],x["profile"])==("train",10000,"normal")),
                      "evaluation_10k_normal":next(x for x in results if (x["window"],x["capital"],x["profile"])==("evaluation",10000,"normal"))},
                     ensure_ascii=False))


if __name__=="__main__":
    main()
