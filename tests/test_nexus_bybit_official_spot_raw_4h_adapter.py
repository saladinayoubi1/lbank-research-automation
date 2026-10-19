"""Offline-only official Spot raw trade 4h adapter QA; no future prices."""
from __future__ import annotations

import csv
import gzip
import json
from hashlib import sha256
from pathlib import Path

import pytest

from scripts import nexus_bybit_official_spot_raw_4h_adapter as source

DAY="2026-08-01"
SYMBOL="BTCUSDT"
BASE=1785542400000
HEAD=["id","timestamp","price","volume","side","rpi"]


def built(tmp_path,*,omit_bar=None,volume="0.1",start_ms=BASE):
    path=tmp_path/f"{SYMBOL}_{DAY}.csv.gz"
    rows=[[str(i+1),str(start_ms+i*source.FOUR_H_MS+1000),
           str(100+i),volume,"buy","0"]
          for i in range(6) if i!=omit_bar]
    with gzip.open(path,"wt",newline="",encoding="utf8") as f:
        writer=csv.writer(f)
        writer.writerow(HEAD)
        writer.writerows(rows)
    return path,rows


def test_strict_synthetic_six_4h_bars_and_no_trading_authority(tmp_path):
    path,rows=built(tmp_path)
    o=source.aggregate_gzip_day(path,SYMBOL,DAY,source._sha256_file(path))
    assert o["total_raw_trade_rows"]==6
    assert len(o["fully_observed_4h_bars"])==6
    assert o["fully_observed_4h_bars"][0]["open"]==100
    assert o["fully_observed_4h_bars"][-1]["close"]==105
    assert o["fully_observed_4h_bars"][0]["timestamp"]=="2026-08-01T00:00:00+00:00"
    assert o["claimed_official_url"]=="https://public.bybit.com/spot/BTCUSDT/BTCUSDT_2026-08-01.csv.gz"
    assert o["provider_origin_cryptographically_signed"] is False
    assert o["ready_to_score_prospective_strategy"] is False
    assert o["orders"]==0 and o["live_enabled"] is False


def test_two_real_trades_same_bucket_keep_first_open_and_final_close(tmp_path):
    path,rows=built(tmp_path)
    rows.insert(1,["2",str(BASE+2000),"130.5","0.2","sell","1"])
    for i,row in enumerate(rows):
        row[0]=str(i+1)
    with gzip.open(path,"wt",newline="") as f:
        writer=csv.writer(f);writer.writerow(HEAD);writer.writerows(rows)
    x=source.aggregate_gzip_day(path,SYMBOL,DAY,source._sha256_file(path))
    one=x["fully_observed_4h_bars"][0]
    assert (one["open"],one["high"],one["low"],one["close"])==(100,130.5,100,130.5)
    assert one["volume"]==pytest.approx(.3)
    assert one["trades"]==2


def test_no_missing_four_hour_bucket_or_interpolation(tmp_path):
    path,_=built(tmp_path,omit_bar=3)
    with pytest.raises(source.RawTradeSourceError,match="incomplete 4h"):
        source.aggregate_gzip_day(path,SYMBOL,DAY,source._sha256_file(path))


@pytest.mark.parametrize("edit,expected",[
    ("bad_sha","SHA256 mismatch"),
    ("bad_symbol","unexpected Spot asset"),
    ("bad_day","wrong-day"),
    ("out_of_day","out-of-order, out-of-day"),
    ("zero_volume","invalid trade"),
    ("negative_price","invalid trade"),
    ("out_of_order_id","out-of-order, out-of-day"),
    ("out_of_order_time","out-of-order, out-of-day"),
    ("unknown_side","invalid trade"),
])
def test_source_proof_and_market_price_fail_closed(tmp_path,edit,expected):
    path,rows=built(tmp_path)
    if edit in ("bad_sha","bad_symbol","bad_day"):
        argsha="0"*64 if edit=="bad_sha" else source._sha256_file(path)
        sym="BTCUSD" if edit=="bad_symbol" else SYMBOL
        day="2026-08-02" if edit=="bad_day" else DAY
        with pytest.raises(source.RawTradeSourceError,match=expected):
            source.aggregate_gzip_day(path,sym,day,argsha)
        return
    if edit=="out_of_day":rows[0][1]=str(BASE-1)
    elif edit=="zero_volume":rows[0][3]="0"
    elif edit=="negative_price":rows[0][2]="-5"
    elif edit=="out_of_order_id":rows[1][0]=rows[0][0]
    elif edit=="out_of_order_time":rows[1][1]=str(BASE)
    elif edit=="unknown_side":rows[0][4]="hold"
    with gzip.open(path,"wt",newline="") as f:
        w=csv.writer(f);w.writerow(HEAD);w.writerows(rows)
    with pytest.raises(source.RawTradeSourceError,match=expected):
        source.aggregate_gzip_day(path,SYMBOL,DAY,source._sha256_file(path))


def test_manifest_report_is_explicitly_only_sampled_historical_source(tmp_path):
    file,_=built(tmp_path)
    manifest={
      "schema":source.MANIFEST_SCHEMA,"assets":list(source.SYMBOLS),
      "study_scope":"historical_source_seam_and_warmup_examples_only",
      "source_claim_not_exchange_signed":True,
      "samples":[{"symbol":SYMBOL,"date":DAY,
                  "raw_sha256":source._sha256_file(file)}]
    }
    path=tmp_path/"reviewed.json"
    path.write_text(json.dumps(manifest))
    report=source.audited_samples(tmp_path,path)
    assert report["sample_only_not_full_day_by_day_source_coverage"] is True
    assert report["independent_provider_qa_still_required"] is True
    assert report["actual_original_canonical_seam_parity_not_proven_by_this_parser_alone"] is True
    assert report["not_future_prospective_holdout"] is True
    assert report["paper_eligible"] is False and report["orders"]==0


def test_invalid_manifest_cannot_fake_complete_source(tmp_path):
    file,_=built(tmp_path)
    manifest={
      "schema":source.MANIFEST_SCHEMA,"assets":list(source.SYMBOLS),
      "study_scope":"historical_source_seam_and_warmup_examples_only",
      "source_claim_not_exchange_signed":True,
      "samples":[{"symbol":SYMBOL,"date":DAY,
                  "raw_sha256":source._sha256_file(file)}]
    }
    p=tmp_path/"reviewed.json"
    manifest["study_scope"]="COMPLETE_FUTURE_BYBIT_VALIDATION"
    p.write_text(json.dumps(manifest))
    with pytest.raises(source.RawTradeSourceError,match="unreviewed raw sample scope"):
        source.audited_samples(tmp_path,p)


def test_symlink_input_denied(tmp_path):
    real,_=built(tmp_path)
    other=tmp_path/"alias"
    try:
        other.symlink_to(real)
    except OSError:
        pytest.skip("Symlinks unavailable to nonadmin Windows")
    with pytest.raises(source.RawTradeSourceError,match="missing/linked"):
        source.aggregate_gzip_day(other,SYMBOL,DAY,source._sha256_file(real))
