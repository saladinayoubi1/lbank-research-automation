"""Strict offline checks for third-party historical SPOT L2, not executed fills."""
import hashlib,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/"docs"/"evidence"/"mr40-l2-depth-20251022"/"depth_audit.json"
def report():
    r=json.loads(DOC.read_bytes())
    digest=r.pop("digest")
    b=json.dumps(r,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
    assert hashlib.sha256(b).hexdigest()==digest=="5cb72adacf98f0789b3095557234b07fdc21317858b64b685cda9dde3a2738e8"
    return r
def test_archive_sha_and_update_sequence_are_pinned():
    r=report()
    assert r["source"]["sha256"]=="6a7e3f08c46da49ea2241aaec77371ca414a3f400e0cec4ec3b1ecda662b0d88"
    assert r["source"]["compressed_bytes"]==95584674
    assert r["source"]["jsonl_bytes"]==530351866
    assert r["counts"]["jsonl_messages"]==431176
    assert r["counts"]["snapshots"]==1
    assert r["counts"]["deltas"]==431159
    assert r["counts"].get("u_gaps_or_resets",0)==0
    assert r["counts"].get("nonmonotone_ts",0)==0
    assert r["counts"].get("nonmonotone_seq",0)==0

def test_strict_end_of_day_scope_failed_and_is_not_reinterpreted():
    r=report()
    assert r["full_day_strict_time_scope_pass"] is False
    assert r["counts"]["out_of_day_trailing_records"]==16
    assert r["prior_4h_1m_full_ohlc_parity"].startswith("FAILED")
    assert r["real_fill_verified"] is False and r["paper_changed"] is False

def test_l2_cross_state_has_no_future_quotes_or_execution_claim():
    r=report()
    states={s["label"]:s for s in r["snapshots"]}
    assert len(states)==8 and r["cross_state_usable"] is True
    for s in states.values():
        assert s["source_timestamp_utc"]<=s["target_utc"]
        assert s["book_valid"] is True
        assert 0<=s["age_ms"]<=2000
        x=s["depth_mark"]
        assert x["ask"]>x["bid"]
        assert x["static_book_walk_vwap_mark"] is not None
        assert x["recorded_position_qty_btc"]==0.09461
        assert x["zero_latency_static_displayed_book_walk_completely_covered"] is True
        assert x["EXPLICIT_NON_EXECUTABLE"].startswith("Static displayed L2 mark")
    a=states["first_cross"];b=states["after_1s"];c=states["after_5s"]
    assert a["age_ms"]==72 and a["depth_mark"]["bid"]==114345.2
    assert a["depth_mark"]["top_20_bid_btc"]==0.456075
    assert b["depth_mark"]["bid"]==114202.5
    assert c["depth_mark"]["bid"]==113924.3
    assert 0.03648<c["depth_mark"]["top_20_bid_btc"]<0.03649
    assert states["after_15s"]["depth_mark"]["bid"]==113069.4

def test_model_refuses_stale_and_crossed_books():
    script=ROOT/"research"/"nexus_mr40_l2_snapshot_delta_audit_v1.py"
    spec=importlib.util.spec_from_file_location("l2_book_verifier",script)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    last={"ts":1000,"cts":999,"u":100,"seq":200}
    valid=mod.snapshot_state(1010,"good",{"100.0":0.02,"99.0":0.2},{"101.0":0.1},last,True,None,0.09461)
    assert valid["book_valid"] and valid["depth_mark"]["book_walk_levels"]==2
    stale=mod.snapshot_state(5000,"stale",{"100":0.2},{"101":0.2},last,True,None,0.09461)
    assert not stale["book_valid"]
    crossed=mod.snapshot_state(1010,"crossed",{"102":0.2},{"101":0.2},last,True,None,0.09461)
    assert not crossed["book_valid"]
    broken=mod.snapshot_state(1010,"gap",{"100":0.2},{"101":0.2},last,False,"missing_delta",0.09461)
    assert not broken["book_valid"]

def test_pre_registered_protective_restrictions():
    p=json.loads((ROOT/"research"/"mr40_l2_depth_audit_protocol_20261022.json").read_bytes())
    assert p["schema"]=="mr40.bybit-spot-historical-l2-crash.v1"
    assert p["constraints"]=={"private_keys":False,"real_orders":False,"paper_untouched":True,
        "live":False,"auto_merge":False,"auto_promotion":False}
    assert p["frozen_reference"]["stop_ref"]=="114312.3916320000"
