"""Offline integrity tests for Bybit public BTCUSDT SPOT tape, October 10, 2025.

These tests intentionally do NOT estimate how a stop-market order would fill.
No network, trading API, keys, order placement or historical strategy replays.
"""
from __future__ import annotations
import csv,gzip,hashlib,io,json
from decimal import Decimal as D
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
E=BASE/"docs"/"evidence"/"mr40-spot-ticks-20251010"
def canonical(v):
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def evidence():
    j=json.loads((E/"summary.json").read_bytes())
    sha=j.pop("digest")
    assert hashlib.sha256(canonical(j)).hexdigest()==sha=="c925578f3c73870a1f56ef35573dbd3ecb2303dffb97a192d7299d954fa07c37"
    return j

def test_frozen_spot_source_and_count():
    data=evidence()
    source=data["source"]
    assert source["day_archive_sha256"]=="df094454ca458a41c0908fa0c15d73286804509b3eeb1330c98a4c53d13f487b"
    assert source["day_archive_bytes"]==16190304
    assert source["all_day_print_count"]==2299006
    assert source["schema"]==["id","timestamp","price","volume","side","rpi"]
    assert data["parent_4h_exact_ohlc_parity_remains_failed"] is True

def test_crossing_tape_reproduces_1minute_ohlc_and_below_stop_volume():
    data=evidence()
    file=E/"one_minute_trade_tape.csv.gz"
    assert hashlib.sha256(file.read_bytes()).hexdigest()=="de938b666c6862108af479824c288c54f18429e00d12a427d66d1c2882b51c2e"
    with gzip.open(file,"rt",encoding="utf-8",newline="") as raw:
        rs=list(csv.DictReader(raw))
    assert len(rs)==data["focus_minute_print_count"]==31659
    assert all(1760129760000<=int(r["timestamp_ms"])<1760129820000 for r in rs)
    prices=[D(r["price"]) for r in rs]
    vols=[D(r["volume_btc"]) for r in rs]
    ohlc=[prices[0],max(prices),min(prices),prices[-1]]
    assert [str(x) for x in ohlc]==data["tick_trade_ohlc"]
    assert data["tick_vs_1minute_ohlc_abs_deltas"]==["0.0","0.0","0.0","0.0"]
    assert data["one_minute_parity_pass"] is True
    stop=D("114312.3916320000")
    hits=[i for i,p in enumerate(prices) if p<=stop]
    assert len(hits)==data["focus_minute_print_count_at_or_below_stop"]==24028
    assert sum((vols[i] for i in hits),D(0))==D(data["focus_minute_btc_volume_at_or_below_stop"])
    assert sum(vols,D(0))==D(data["focus_minute_btc_volume"])
    assert str(prices[hits[0]])=="114312"
    assert rs[hits[0]]["timestamp_ms"]=="1760129774936"

def test_first_crossing_and_recovery_are_trades_not_fills():
    d=evidence()
    ev=d["event"]
    assert ev["first_cross"]["utc"]=="2025-10-10T20:56:14.936+00:00"
    assert ev["first_cross"]["previous_print"]["price"]=="114312.5"
    assert ev["first_recovery_print_at_or_above_stop"]["elapsed_ms_after_first_cross"]==42395
    assert ev["last_trade_at_or_below_stop_utc"]=="2025-10-10T21:00:01.694+00:00"
    assert "No bid/ask order book" in d["inference"]
    assert "pnl" not in d and "fill" not in ev

def test_policy_research_only_and_no_live():
    policy=json.loads((BASE/"research"/"mr40_tick_archive_protocol_v1.json").read_bytes())
    assert policy["schema"]=="mr40.bybit-spot-ticks.20251010.v1"
    assert policy["prior_strict_parity"].startswith("FAILED")
    assert policy["constraints"]=={"paper_changed":False,"live":False,
        "real_orders":False,"private_api":False,"auto_promote":False,"merge":False}
