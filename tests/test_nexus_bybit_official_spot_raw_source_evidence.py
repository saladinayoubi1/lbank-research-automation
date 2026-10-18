"""Receipt regression QA for actual official-host Bybit BTC/ETH Spot trades.

Evidence is a six-day SAMPLE. It is not the missing contiguous
Aug-Oct archive and NOT forward OOS or proof of trading profitability.
"""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from scripts.nexus_bybit_official_spot_raw_4h_adapter import _digest

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"docs/evidence/bybit-official-spot-raw-4h-20261018"
MANIFEST=ROOT/"research/bybit_official_spot_daily_raw_sample_claims_20261018.json"
SAMPLE=EVIDENCE/"six-day-btc-eth-raw-trade-4h-sample.json"
SEAM=EVIDENCE/"six-day-original-seam-crosscheck.json"
SAMPLE_DIGEST="d51f9062df36d590f2d60d7d1edb59107d2e4a58613a133c80db4cf6ee80559a"
SEAM_ORIGINAL_FILE_SHA="b3c3f16fb99e06486e89ac987f18190d2770eda3620b0190e3ada9403f9cf843"
DATES={"2026-07-31","2026-08-01","2026-10-17"}
EXPECTED={
 "BTCUSDT":{"2026-07-31":481468,"2026-08-01":221151,
            "2026-10-17":468696},
 "ETHUSDT":{"2026-07-31":160308,"2026-08-01":89507,
            "2026-10-17":212317},
}


def evidence():
    o=json.loads(SAMPLE.read_text("utf8"))
    assert o["digest"]==_digest({k:v for k,v in o.items() if k!="digest"})==SAMPLE_DIGEST
    return o


def crosscheck():
    data=SEAM.read_bytes().replace(b"\r\n",b"\n")
    assert sha256(data).hexdigest()==SEAM_ORIGINAL_FILE_SHA
    return json.loads(data.decode("utf8"))


def test_six_real_trade_files_exact_hash_and_original_4h_parser_receipt():
    original=json.loads(MANIFEST.read_text("utf8"))
    record={(v["symbol"],v["date"]):v for v in original["samples"]}
    sample=evidence()
    assert len(record)==len(sample["sampled_bybit_spot_days"])==6
    for item in sample["sampled_bybit_spot_days"]:
        sym,day=item["symbol"],item["date"]
        assert day in DATES
        assert item["raw_file_sha256"]==record[(sym,day)]["raw_sha256"]
        assert item["total_raw_trade_rows"]==EXPECTED[sym][day]
        assert len(item["fully_observed_4h_bars"])==6
        assert sum(bar["trades"] for bar in item["fully_observed_4h_bars"])==item["total_raw_trade_rows"]
        assert item["claimed_official_url"]==(
            f"https://public.bybit.com/spot/{sym}/{sym}_{day}.csv.gz"
        )


def test_july31_exact_old_seam_twelve_4h_ohlcv_no_delta():
    cross=crosscheck()["comparisons"]
    assert set(cross)==set(EXPECTED)
    for sym in EXPECTED:
        rows=cross[sym]["2026-07-31"]["old_canonical_overlaps"]
        assert len(rows)==6
        for row in rows.values():
            assert row["matched"] is True
            assert all(float(delta)==0.0 for delta in row["price_deltas"].values())
            assert float(row["volume_delta"])==0.0


def test_august_first_and_october_17_are_new_historical_warmup_samples():
    a=crosscheck()["comparisons"]
    for sym in EXPECTED:
        for day in ("2026-08-01","2026-10-17"):
            row=a[sym][day]
            assert len(row["4h_bars"])==6
            assert row["trade_rows"]==EXPECTED[sym][day]
            assert all(x["matched"] is False for x in row["old_canonical_overlaps"].values())


def test_independent_native_4h_aggregators_reconcile_daily_bars():
    a=crosscheck()["comparisons"]
    b=evidence()["sampled_bybit_spot_days"]
    for row in b:
        legacy=a[row["symbol"]][row["date"]]
        assert row["raw_file_sha256"]==legacy["raw_sha256"]
        assert row["total_raw_trade_rows"]==legacy["trade_rows"]
        for native,cross in zip(row["fully_observed_4h_bars"],legacy["4h_bars"]):
            assert native["timestamp"]==cross["timestamp"]
            for col in ("open","high","low","close","volume"):
                assert native[col]==pytest.approx(cross[col],abs=1e-6)


def test_six_sample_receipt_forbids_future_trading_or_qualification():
    o=evidence()
    assert o["sample_only_not_full_day_by_day_source_coverage"] is True
    assert o["raw_files_have_official_https_claim_but_no_exchange_signature"] is True
    assert o["independent_provider_qa_still_required"] is True
    assert o["actual_original_canonical_seam_parity_not_proven_by_this_parser_alone"] is True
    assert o["source_type"]=="SPOT_RAW_TRADE_NOT_SPOT_KLINE_API"
    assert o["not_future_prospective_holdout"] is True
    assert o["paper_eligible"] is False
    assert o["live_enabled"] is False
    assert o["orders"]==0
