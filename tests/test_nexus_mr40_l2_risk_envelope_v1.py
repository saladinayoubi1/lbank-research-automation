"""Offline CI regression for MR40 static displayed-book risk envelope.
Nothing here authorizes live trading, stop fills, or production sizing.
"""
import hashlib,importlib.util,json
from decimal import Decimal as D
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EV=ROOT/"docs"/"evidence"/"mr40-l2-risk-envelope-20261022"/"marked_risk_envelope.json"
def evidence():
    r=json.loads(EV.read_bytes())
    digest=r.pop("digest")
    c=json.dumps(r,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
    assert hashlib.sha256(c).hexdigest()==digest=="d4f37d35605ca893e6b488f24f6e4ca485003b667a0e98c459f1dbba05adec55"
    return r
def test_source_ledger_and_existing_failed_gates_are_retained():
    p=json.loads((ROOT/"research"/"mr40_l2_risk_envelope_protocol_20261022.json").read_bytes())
    r=evidence()
    assert p["schema"]=="mr40.spot-l2-event-marked-risk-envelope.v1"
    assert r["source_l2_digest"]==p["sources"]["l2_digest"]
    assert r["source_baseline_ledger_sha256"]==p["sources"]["ledger_sha256"]
    assert p["entry_match"]["expected_entry_quantity_btc"]=="0.09461"
    assert r["reference"]["cash_before_entry_usdt"]=="11277.26953006"
    assert r["selection_or_promotion_allowed"] is False
    assert r["paper_changed"] is False and r["live_enabled"] is False and r["trade_order_placed"] is False
    assert any("parity" in caveat.lower() for caveat in r["limitations"])

def test_mark_value_variation_is_pure_accounting_not_fill():
    r=evidence()
    ref=r["reference"]
    q=D(ref["quantity_btc"]);cash=D(ref["cash_before_entry_usdt"])
    stop=D(ref["static_original_stop4_reference_usdt"])
    assert D(ref["filled_entry_price_usdt"])*D(".96")==stop
    cases={x["label"]:x for x in r["sensitivity_marks"]}
    assert len(cases)==7 and all(x["mark_allowed"] for x in cases.values())
    assert cases["first_cross"]["age_ms"]==72
    for x in cases.values():
        assert x["age_ms"]<=2000
        expected=(D(x["mark_usdt"])-stop)*q
        assert abs(expected-D(x["vs_stop_reference_usdt"]))<D(".0000011")
        pct=D(x["vs_stop_reference_usdt"])/cash*100
        assert abs(pct-D(x["vs_stop_reference_pct_of_preentry_equity"]))<D(".000011")
    assert cases["after_1s"]["vs_stop_reference_usdt"]=="-10.846648"
    assert cases["after_5s"]["vs_stop_reference_usdt"]=="-37.772676"
    assert cases["after_15s"]["vs_stop_reference_usdt"]=="-117.780258"
    assert cases["after_15s"]["vs_stop_reference_pct_of_preentry_equity"]=="-1.04440"

def test_algebraic_budgets_do_not_become_deployment_rules():
    r=evidence();ref=r["reference"];cash=D(ref["cash_before_entry_usdt"])
    entry=D(ref["filled_entry_price_usdt"])
    after=next(x for x in r["sensitivity_marks"] if x["label"]=="after_15s")
    unit_loss=entry-D(after["mark_usdt"])
    assert unit_loss>0
    assert [v["qty_floor_at_0p00001_btc"] for v in r["one_event_algebraic_budgets"]]==["0.01877","0.03754"]
    for v in r["one_event_algebraic_budgets"]:
        budget=cash*D(v["algebraic_risk_budget_pct"])/100
        assert abs(budget-D(v["risk_budget_usdt"]))<D(".000001")
        assert D(v["qty_floor_at_0p00001_btc"])*unit_loss<=budget
        assert D(v["qty_floor_at_0p00001_btc"])<D(ref["quantity_btc"])
    assert "NOT a recommended sizing rule" in " ".join(r["limitations"])

def test_synthetic_metric_rejects_bad_inputs_and_preserves_linear_risk():
    script=ROOT/"research"/"nexus_mr40_l2_risk_envelope_v1.py"
    spec=importlib.util.spec_from_file_location("risk_envelope",script)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    a=m.metric(D(120),D(96),D(10000),D(1),D(94))
    b=m.metric(D(120),D(96),D(10000),D(2),D(94))
    assert D(a["vs_stop_reference_usdt"])==D(-2)
    assert D(b["vs_stop_reference_usdt"])==D(-4)
    for bad in (D(-1),D(0)):
        try:m.metric(D(120),D(96),D(10000),D(1),bad)
        except ValueError:pass
        else:raise AssertionError("nonpositive_mark_accepted")
