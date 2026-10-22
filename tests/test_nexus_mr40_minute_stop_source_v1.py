"""Offline fidelity controls for public minute-source flash-crash research.
No API or trade/order calls during tests; strategy model unchanged.
"""
from pathlib import Path
import gzip,hashlib,json
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"docs"/"evidence"/"mr40-minute-execution-20261022"
def canon(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def parsed(name,digest):
    x=json.loads((DATA/name).read_bytes())
    h=x.pop("digest")
    assert hashlib.sha256(canon(x)).hexdigest()==h==digest
    return x

def test_public_spot_minute_archive_matches_source_receipt():
    compressed=(DATA/"public_api_raw.json.gz").read_bytes()
    assert hashlib.sha256(compressed).hexdigest()=="73639b60284df3f7b54631b3703a5f5f734fbd967154d69bf5906add5813e133"
    raw=gzip.decompress(compressed)
    assert hashlib.sha256(raw).hexdigest()=="b6c9b7aa60334f72c7fc9218f9edfa7d1c506aaf45c2d8ef74783887fbd4f096"
    j=json.loads(raw)
    assert j["retCode"]==0 and j["result"]["category"]=="spot" and j["result"]["symbol"]=="BTCUSDT"
    selected=sorted((r for r in j["result"]["list"] if 1760112000000<=int(r[0])<1760155200000),key=lambda v:int(v[0]))
    assert len(selected)==720
    assert [int(r[0]) for r in selected]==list(range(1760112000000,1760155200000,60000))

def test_pre_registered_strict_4h_ohlc_parity_remains_failed():
    x=parsed("strict_audit.json","555dce436bb17c454bcb3bf17f10ced98e5e19ebcf70c34d9f29dae1001b7368")
    assert x["four_hour_parity_pass"] is False
    assert x["stop_touch"]["evaluated"] is False
    assert x["public_source"]["in_scope_rows"]==720
    assert x["public_source"]["raw_response_sha256"]=="b6c9b7aa60334f72c7fc9218f9edfa7d1c506aaf45c2d8ef74783887fbd4f096"
    assert len(x["four_hour_reconciliation"])==3
    assert all(all(v==0 for v in z["absolute_deltas_usdt"][1:]) for z in x["four_hour_reconciliation"])
    assert x["four_hour_reconciliation"][1]["absolute_deltas_usdt"][0]>1
    assert x["four_hour_reconciliation"][2]["absolute_deltas_usdt"][0]>0

def test_posthoc_trace_does_not_invent_executable_stop_fill():
    x=parsed("descriptive_trace.json","103f4bd98f305bfedb5c89269e59c47e6c3ac6e6a13852b41bd60ad594e84704")
    assert x["primary_4h_parity_pass"] is False
    assert x["no_execution_price_or_pnl"] is True
    t=x["observed_first_touch"]
    assert t["minute"]==296 and t["utc"]=="2025-10-10T20:56:00+00:00"
    assert t["minute_open_below_reference"] is False
    assert t["low_below_reference_pct"]>1.3
    assert x["preceding_minute_close"]=="114901.3"
    assert x["minute_after_touch"]["open"]=="114395.2"

def test_frozen_protocols_still_reject_live_and_paper():
    p=json.loads((ROOT/"research"/"mr40_minute_execution_protocol_v1.json").read_bytes())
    q=json.loads((ROOT/"research"/"mr40_minute_price_trace_protocol_v1.json").read_bytes())
    assert p["request"]["category"]=="spot" and p["request"]["interval"]=="1"
    assert p["restrictions"]["paper_changed"] is False
    assert p["restrictions"]["real_order"] is False
    assert q["restrictions"]["paper_changed"] is False
    assert q["restrictions"]["real_orders"] is False
    assert q["scope"].startswith("Post hoc DESCRIPTIVE")
