"""Offline accounting sensitivity from pre-recorded L2 displayed book marks.

No stop execution modeling: this explicitly does NOT approximate fills.
No network, private API, order placement, return forecasting, or backtests.
"""
from __future__ import annotations
import argparse,gzip,hashlib,json
from decimal import Decimal as D,ROUND_DOWN
from pathlib import Path

L2_HASH="5cb72adacf98f0789b3095557234b07fdc21317858b64b685cda9dde3a2738e8"
LEDGER_SHA="2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e"
def canonical(v):
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def txt(v,places="0.000001"):
    return str(v.quantize(D(places)))
def metric(entry,stop,cash,qty,mark):
    if any(z<=0 for z in (entry,stop,cash,qty,mark)):
        raise ValueError("nonpositive_price_or_amount")
    change=(mark-stop)*qty
    entry_mark_loss=(entry-mark)*qty
    return {"mark_usdt":txt(mark),
        "vs_stop_reference_usdt":txt(change),
        "vs_stop_reference_pct_of_preentry_equity":txt(change/cash*100,"0.00001"),
        "entry_to_mark_loss_no_fee_usdt":txt(entry_mark_loss),
        "entry_to_mark_loss_pct_of_preentry_equity":txt(entry_mark_loss/cash*100,"0.00001")}
def audit(policy,l2,ledger,output):
    if output.exists():raise ValueError("output_already_exists")
    p=json.loads(policy.read_bytes())
    if p["schema"]!="mr40.spot-l2-event-marked-risk-envelope.v1" or p["sources"]["l2_digest"]!=L2_HASH:
        raise ValueError("changed_preregistered_policy")
    report=json.loads(l2.read_bytes())
    published=report.pop("digest")
    if published!=L2_HASH or hashlib.sha256(canonical(report)).hexdigest()!=L2_HASH:
        raise ValueError("l2_evidence_digest_changed")
    if report["full_day_strict_time_scope_pass"] is not False or report["real_fill_verified"] is not False or report["paper_changed"] is not False:
        raise ValueError("source_failure_or_constraints_lost")
    if report["prior_4h_1m_full_ohlc_parity"]!="FAILED and deliberately not changed":
        raise ValueError("original_source_parity_wrongly_relaxed")
    if hashlib.sha256(ledger.read_bytes()).hexdigest()!=LEDGER_SHA:
        raise ValueError("baseline_trade_ledger_changed")
    desired=p["entry_match"]
    found=[]
    with gzip.open(ledger,"rt",encoding="utf8") as f:
        for line in f:
            x=json.loads(line);k=x["key"]
            if all(k[n]==desired[n] for n in ("venue","window","capital","profile","case")):
                found.extend(z for z in x["positions"] if z["entry"]["fill_ms"]==desired["entry_ms"])
    if len(found)!=1:raise ValueError("baseline_trade_not_unique")
    buy=found[0]["entry"]
    entry=D(buy["price"]);qty=D(buy["quantity"]);cash=D(buy["cash_before"])
    if qty!=D(desired["expected_entry_quantity_btc"]) or entry!=D(desired["expected_filled_entry_price"]):
        raise ValueError("trade_entry_changed")
    stop=entry*(D(1)-D(str(desired["stop_fraction"])))
    by_label={s["label"]:s for s in report["snapshots"]}
    cases=[]
    for label in p["fixed_samples"]:
        s=by_label[label]
        m=s["depth_mark"]
        if (not s["book_valid"] or not(0<=s["age_ms"]<=2000) or not m["zero_latency_static_displayed_book_walk_completely_covered"]
                or m["EXPLICIT_NON_EXECUTABLE"].split(",")[0]!="Static displayed L2 mark"):
            cases.append({"label":label,"mark_allowed":False,"reason":"invalid_or_uncovered_book"})
            continue
        mark=D(str(m["static_book_walk_vwap_mark"]))
        cases.append({"label":label,"source_timestamp_utc":s["source_timestamp_utc"],"age_ms":s["age_ms"],
                     "mark_allowed":True,**metric(entry,stop,cash,qty,mark),
                     "top20_bid_liquidity_btc":str(m["top_20_bid_btc"]),
                     "book_walk_levels":m["book_walk_levels"]})
    mark_15=next(x for x in cases if x["label"]=="after_15s")
    if not mark_15["mark_allowed"]:raise ValueError("anchor_mark_missing")
    adverse=entry-D(mark_15["mark_usdt"])
    if adverse<=0:raise ValueError("risk_sensitivity_sign")
    budgets=[]
    for frac in (D(".01"),D(".02")):
        cap=cash*frac/adverse
        floored=(cap/D(".00001")).to_integral_value(rounding=ROUND_DOWN)*D(".00001")
        budgets.append({"algebraic_risk_budget_pct":str(frac*100),
            "risk_budget_usdt":txt(cash*frac),
            "hypothetical_qty_cap_btc_at_15s_mark_no_fee":txt(cap,"0.00000001"),
            "qty_floor_at_0p00001_btc":str(floored),
            "original_qty_btc":str(qty),
            "hypothetical_fraction_of_original_qty":txt(cap/qty,"0.00001")})
    result={"schema":"mr40.spot-l2-event-marked-risk-envelope.results.v1",
            "source_l2_digest":L2_HASH,"source_baseline_ledger_sha256":LEDGER_SHA,
            "policy_sha256":hashlib.sha256(policy.read_bytes()).hexdigest(),
            "reference":{"entry_utc":"2025-10-10T16:00:00+00:00","cash_before_entry_usdt":str(cash),
               "quantity_btc":str(qty),"filled_entry_price_usdt":str(entry),
               "static_original_stop4_reference_usdt":str(stop)},
            "sensitivity_marks":cases,"one_event_algebraic_budgets":budgets,
            "limitations":["Values are measured against a historical DISPLAYED bid depth VWAP marker, NOT an actual or executable fill.",
                "No fee, added slippage, queueing, latency, book cancellations, market impact or actual realized PNL are modeled.",
                "Latency scenarios refer only to a single already-observed extreme event; 15 sec is NOT worst case.",
                "Preexisting 4h-to-1m parity and source date-only validation remain failed.",
                "Risk-budget quantities are mathematical illustrations NOT a recommended sizing rule.",
                "No portfolio simulation, prospective validation, trading activity or Paper change."],
            "paper_changed":False,"live_enabled":False,"trade_order_placed":False,
            "selection_or_promotion_allowed":False}
    result["digest"]=hashlib.sha256(canonical(result)).hexdigest()
    output.write_bytes(canonical(result)+b"\n")
    print(json.dumps({"digest":result["digest"],"references":result["reference"],
        "cases":[{"label":v["label"],"delta_usdt":v.get("vs_stop_reference_usdt"),
                 "extra_equity_pct":v.get("vs_stop_reference_pct_of_preentry_equity")} for v in cases],
        "illustrative_budgets":budgets},ensure_ascii=False),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for k in ("policy","l2","ledger","output"):p.add_argument("--"+k,required=True,type=Path)
    audit(**vars(p.parse_args()))
