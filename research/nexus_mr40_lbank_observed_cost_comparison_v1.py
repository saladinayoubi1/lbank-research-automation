"""Sensitivity replay using published base fees and current visible depth only."""
import importlib.util
from decimal import Decimal
import hashlib
import json
from pathlib import Path


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(root):
    evidence = root / "docs/evidence/lbank-mr40-exact30-20261021"
    study = load("observed_cost_study", root / "research/nexus_mr40_lbank_exact30_v1.py")
    book = load("observed_cost_book", root / "research/nexus_lbank_spot_cost_snapshot_v1.py")
    snapshot = json.loads((evidence / "current_depth_cost_snapshot.json").read_bytes())
    original = json.loads((evidence / "results.json").read_bytes())
    for value, field in ((snapshot, "digest"), (original, "result_digest")):
        if study.digest({k:v for k,v in value.items() if k != field}) != value[field]:
            raise ValueError("input_digest_mismatch")
    if hashlib.sha256((root / "research/nexus_lbank_spot_cost_snapshot_v1.py").read_bytes()).hexdigest() != snapshot["driver_sha256"]:
        raise ValueError("probe_source_mismatch")
    observed = {500: [], 10000: []}
    for sample in snapshot["samples"]:
        receipt = sample["receipt"]
        raw = receipt["raw_body"].encode()
        if hashlib.sha256(raw).hexdigest() != receipt["body_sha256"]:
            raise ValueError("raw_book_digest_mismatch")
        body = json.loads(raw, parse_float=str)
        books = book.parse_book(body, sample["observed_ms"])
        for old in sample["measurements"]:
            current = book.measure(books, old["notional_usdt"])
            if current != old:
                raise AssertionError("book_measurement_replay_mismatch")
            observed[current["notional_usdt"]].extend(Decimal(current[k]) for k in
                ("buy_shortfall_from_mid_bps", "sell_shortfall_from_mid_bps"))
    code = study.load_sources(root)
    raw = (evidence / "lbank_kline_response.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != original["source_receipt"]["body_sha256"]:
        raise ValueError("raw_candle_digest_mismatch")
    native = code["validator"](json.loads(raw, parse_float=str)["data"])
    end_ms = code["core"].ms(original["policy"]["window_end_exclusive_utc"])
    rows = sorted(([r[0]*1000,*r[1:]] for r in native if r[0]*1000 < end_ms), key=lambda r:r[0])
    results = []
    for capital in (500,10000):
        # This is an observed current-book proxy, not historical fill data.
        slip_bps = float(max(observed[capital]))
        policy = json.loads(json.dumps(original["policy"]))
        policy["profiles"] = [{"id":"published_base_fee_current_book_proxy", "fee_bps":10, "slippage_bps":slip_bps}]
        replay = study.replay(rows, policy, code)
        for record in replay["results"]:
            engine = record.pop("engine_result")
            baseline = [(f["fill_ms"],f["side"]) for f in original["results"][0]["engine_result"]["fills"]]
            if [(f["fill_ms"],f["side"]) for f in engine["fills"]] != baseline:
                raise AssertionError("cost_comparison_changed_signal_times")
            scale = capital/10000
            results.append({"strategy":record["strategy"],"capital_usdt":capital,"fee_bps_per_side":10,
                "current_book_proxy_slippage_bps_per_side":slip_bps,
                "net_pnl_usdt":engine["metrics"]["net_pnl_usdt"]*scale,
                "mean_position_pnl_usdt":engine["metrics"]["average_closed_position_pnl_usdt"]*scale,
                "closed_positions":engine["metrics"]["closed_positions"],
                "max_close_drawdown_pct":engine["metrics"]["max_close_drawdown_pct"],
                "fees_usdt":engine["metrics"]["fees_usdt"]*scale,
                "nominal_slippage_usdt":engine["metrics"]["nominal_slippage_usdt"]*scale,
                "maximum_decimal_error_usdt":record["maximum_decimal_error_500_usdt"] if capital==500 else record["maximum_decimal_error_10000_usdt"]})
    result = {"schema":"nexus.mr40-lbank-observed-cost-comparison.v1",
        "classification":"HISTORICAL_REPLAY_WITH_CURRENT_DEPTH_COST_PROXY_NOT_ACTUAL_HISTORICAL_EXECUTION",
        "prior_result_digest":original["result_digest"],"snapshot_digest":snapshot["digest"],
        "published_base_fee_bps_per_side":10,"fee_reference_url":"https://www.lbank.com/support/articles/42227167714585",
        "fee_reference_publication_date":"2026-01-28","account_fee_verified":False,
        "current_fee_schedule_url":"https://www.lbank.com/vip/my-fee-rate",
        "current_fee_schedule_rendered_result":"No data; account-specific tier, promotions and discounts unverified",
        "past_zero_fee_event_url":"https://www.lbank.com/questions/ar0x3u1764345817",
        "past_zero_fee_event_current_applicability_verified":False,
        "historical_book_or_actual_fills_available":False,"latency_cost_included":False,
        "quantity_rounding_included":False,"exchange_orders":0,"live_enabled":False,
        "samples":len(snapshot["samples"]),"snapshot_utc":snapshot["executed_utc"],
        "results":results,"driver_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    result["digest"] = study.digest(result)
    (evidence / "observed_cost_comparison.json").write_bytes(study.canonical(result)+b"\n")
    print(json.dumps({"digest":result["digest"],"results":results}),flush=True)
    return result


if __name__ == "__main__":
    run(Path(__file__).resolve().parents[1])
