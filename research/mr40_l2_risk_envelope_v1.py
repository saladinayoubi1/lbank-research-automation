#!/usr/bin/env python3
"""MR40 L2 risk envelope: offline, descriptive STATIC BOOK MARK sensitivity only.

No orders, no fills, no strategy backtesting, no parameter fitting.
Frozen event / protocol. All arithmetic uses Decimal.
"""
import argparse
import gzip
import hashlib
import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

SAMPLE_LABELS = (
    "before_1s", "first_cross", "after_100ms", "after_1s",
    "after_5s", "after_15s", "first_recovery_print",
)
PROTOCOL_BLOB_SHA = "2ffb76b6dec3ea96eddc877c87a303ac04c332f1"
ENTRY_CASH = Decimal("11277.26953006")
EXPECTED_L2_SOURCE_SHA = "6a7e3f08c46da49ea2241aaec77371ca414a3f400e0cec4ec3b1ecda662b0d88"


def ensure(condition, message):
    if not condition:
        raise ValueError(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_protocol(path):
    data = Path(path).read_bytes()
    git_sha = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
    ensure(git_sha == PROTOCOL_BLOB_SHA, "Pinned protocol Git blob SHA mismatch")
    p = json.loads(data, parse_float=Decimal)
    ensure(p["schema"] == "mr40.spot-l2-event-marked-risk-envelope.v1", "Protocol schema mismatch")
    ensure(tuple(p["fixed_samples"]) == SAMPLE_LABELS, "Fixed event sample list changed")
    ensure(p["entry_match"]["entry_ms"] == 1760112000000, "Entry identity changed")
    ensure(p["entry_match"]["stop_fraction"] == Decimal("0.04"), "Stop fraction changed")
    ensure(p["constraints"] == {
        "paper_500_usdt_untouched": True, "live": False, "real_orders": False,
        "private_api": False, "automatic_promotion": False, "merge": False,
    }, "Research safety constraints changed")
    return p


def find_position(ledger_rows, match):
    matches = []
    expected_key = {k: match[k] for k in ("venue", "window", "capital", "profile", "case")}
    for row in ledger_rows:
        if row.get("key") == expected_key:
            matches.append(row)
    ensure(len(matches) == 1, "Expected exactly one matching ledger scenario")
    positions = [
        pos for pos in matches[0].get("positions", [])
        if pos.get("entry", {}).get("fill_ms") == match["entry_ms"]
    ]
    ensure(len(positions) == 1, "Expected exactly one entry timestamp in ledger")
    entry = positions[0]["entry"]
    ensure(entry.get("side") == "buy", "Ledger entry side is not buy")
    ensure(Decimal(str(entry["quantity"])) == Decimal(match["expected_entry_quantity_btc"]),
           "Ledger quantity mismatch")
    ensure(Decimal(str(entry["price"])) == Decimal(match["expected_filled_entry_price"]),
           "Ledger filled entry price mismatch")
    ensure(Decimal(str(entry["cash_before"])) == ENTRY_CASH,
           "Ledger cash-before-entry mismatch")
    return entry


def read_frozen_entry(path, protocol):
    ensure(sha256_file(path) == protocol["sources"]["ledger_sha256"],
           "Ledger compressed SHA256 mismatch")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return find_position((json.loads(line, parse_float=Decimal) for line in stream),
                             protocol["entry_match"])


def validate_failed_gates(audit):
    ensure(audit["schema"] == "mr40.bybit-spot-historical-l2-crash.results.v1",
           "L2 audit schema mismatch")
    ensure(audit["prior_4h_1m_full_ohlc_parity"].startswith("FAILED"),
           "4h-to-1m original FAILED gate was overwritten")
    ensure(audit["full_day_strict_time_scope_pass"] is False,
           "Adjacent-day FAILED gate was overwritten")
    ensure(audit["cross_state_usable"] is True, "L2 continuity not usable")
    ensure(audit["paper_changed"] is False, "Unexpected Paper change")
    ensure(audit["real_fill_verified"] is False, "Unexpected claim of verified fill")


def milliseconds(timestamp):
    return int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000)


def validate_snapshot(snapshot, quantity):
    ensure(snapshot.get("label") in SAMPLE_LABELS, "Unregistered sample")
    ensure(snapshot.get("book_valid") is True and snapshot.get("invalidation_reason") is None,
           "Invalid historical book")
    target = milliseconds(snapshot["target_utc"])
    source = milliseconds(snapshot["source_timestamp_utc"])
    engine = milliseconds(snapshot["source_engine_cts_utc"])
    ensure(source <= target and engine <= target, "Future orderbook data used")
    age = target - source
    ensure(0 <= age <= 2000, "Orderbook older than 2000ms or negative age")
    ensure(age == snapshot["age_ms"], "Discrepant recorded snapshot age")
    mark = snapshot["depth_mark"]
    ensure(Decimal(str(mark["ask"])) > Decimal(str(mark["bid"])),
           "Crossed or locked top orderbook")
    ensure(mark["zero_latency_static_displayed_book_walk_completely_covered"] is True,
           "Insufficient displayed depth for original position")
    ensure(Decimal(str(mark["remaining_uncovered_btc"])) == 0,
           "Incomplete static depth walk")
    ensure(Decimal(str(mark["recorded_position_qty_btc"])) == quantity,
           "Snapshot position quantity does not match ledger")
    return Decimal(str(mark["static_book_walk_vwap_mark"])), age


def sensitivity(mark, stop, quantity, cash_before):
    ensure(cash_before > 0 and quantity > 0, "Invalid accounting denominator")
    delta_usdt = (mark - stop) * quantity
    delta_pct = Decimal(100) * delta_usdt / cash_before
    return delta_usdt, delta_pct


def fmt(value, digits=8):
    return format(value.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_EVEN), "f")


def compute(protocol, audit, entry):
    validate_failed_gates(audit)
    ensure(audit["digest"] == protocol["sources"]["l2_digest"], "Pinned L2 digest mismatch")
    ensure(audit["source"]["sha256"] == EXPECTED_L2_SOURCE_SHA,
           "L2 source archive identity mismatch")
    quantity = Decimal(entry["quantity"])
    fill = Decimal(entry["price"])
    cash = Decimal(entry["cash_before"])
    stop = fill * (Decimal(1) - protocol["entry_match"]["stop_fraction"])
    indexed = {}
    for sample in audit["snapshots"]:
        if sample.get("label") in SAMPLE_LABELS:
            ensure(sample["label"] not in indexed, "Duplicate selected sample")
            indexed[sample["label"]] = sample
    ensure(set(indexed) == set(SAMPLE_LABELS), "Missing locked-time samples")
    table = []
    for label in SAMPLE_LABELS:
        sample = indexed[label]
        mark, age = validate_snapshot(sample, quantity)
        delta, pct = sensitivity(mark, stop, quantity, cash)
        table.append({
            "label": label,
            "target_utc": sample["target_utc"],
            "displayed_book_age_ms": age,
            "static_book_walk_vwap_mark_usdt_per_btc": fmt(mark, 6),
            "mark_minus_static_4pct_stop_reference_usdt": fmt(mark - stop, 8),
            "delta_vs_stop_reference_usdt": fmt(delta, 8),
            "delta_vs_stop_reference_pct_of_entry_time_cash": fmt(pct, 6),
            "displayed_bid_walk_levels": sample["depth_mark"]["book_walk_levels"],
            "actual_fill": False,
        })
    fifteen = Decimal(indexed["after_15s"]["depth_mark"]["static_book_walk_vwap_mark"])
    distance = fill - fifteen
    ensure(distance > 0, "15-second mark not adverse relative to entry")
    caps = {}
    for percent in ("1", "2"):
        budget = cash * Decimal(percent) / Decimal(100)
        caps[percent + "pct"] = {
            "hypothetical_loss_budget_usdt": fmt(budget),
            "algebraic_btc_cap": fmt(budget / distance, 8),
        }
    return {
        "schema": "mr40.l2-risk-envelope.offline.v1",
        "research_only": True, "real_fill_verified": False, "paper_changed": False,
        "promotion": "NO_PROMOTE", "merge": False,
        "data_bias": "Historical event previously seen; not truly out of sample.",
        "risk_limits": "Static third-party displayed books, not actual fills, executable price, impact, latency, or worst case.",
        "source_gates": {
            "frozen_4h_1m_full_ohlc_parity": "FAILED",
            "l2_full_day_date_only_scope": "FAILED",
        },
        "provenance": {
            "protocol_git_blob_sha1": PROTOCOL_BLOB_SHA,
            "l2_logical_digest": audit["digest"],
            "ledger_compressed_sha256": protocol["sources"]["ledger_sha256"],
        },
        "entry": {
            "entry_ms": entry["fill_ms"],
            "quantity_btc": str(quantity),
            "filled_entry_price_usdt": str(fill),
            "cash_before_entry_usdt": str(cash),
            "static_stop_reference_usdt": fmt(stop),
        },
        "samples": table,
        "algebraic_size_diagnostic_not_deployable": {
            "after_15s_entry_to_static_mark_distance_usdt_per_btc": fmt(distance),
            "budgets": caps,
            "excludes": "Fees, queue, fill probability, latency, and subsequent adverse motion.",
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--protocol", required=True)
    ap.add_argument("--audit", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    p = load_protocol(args.protocol)
    audit = json.loads(Path(args.audit).read_text(encoding="utf-8"), parse_float=Decimal)
    entry = read_frozen_entry(args.ledger, p)
    result = compute(p, audit, entry)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps({"output": str(path), "sha256": sha256_file(path),
                      "samples": len(result["samples"]), "gates": result["source_gates"],
                      "promotion": result["promotion"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
