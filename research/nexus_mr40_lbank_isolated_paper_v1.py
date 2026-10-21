"""Owner-requested LBank research Paper, isolated from the Bybit owner account.

Public GET transport and an existing pure Paper simulator only. This module
cannot send an exchange order, use credentials, or promote a strategy.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import hashlib
import html
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time

STEP = 14_400_000
SCHEMA = "nexus.mr40-lbank-isolated-research-paper.v1"
POLICY = {
    "strategy_id": "mean_reversion_40_m2_momentum30_entry_v1",
    "provider": "LBank", "market": "spot", "symbol": "btc_usdt", "timeframe": "hour4",
    "initial_cash_usdt": "500", "fee_rate": "0.001", "extra_adverse_slippage_bps": "5",
    "fee_is_published_base_assumption_not_account_verified": True,
    "history_start_ms": 1782864000000, "trial_days": 30, "max_entry_delay_ms": 120000,
    "paper_only": True, "research_only": True, "live_enabled": False,
    "exchange_orders": 0, "owner_paper_mutation": False, "automatic_promotion": False,
}
BUNDLE_FILES = (
    "research/nexus_mr40_lbank_isolated_paper_v1.py",
    "research/nexus_mr40_lbank_exact30_v1.py",
    "research/nexus_lbank_spot_cost_snapshot_v1.py",
    "research/nexus_mean_reversion_40_m2_retest_v1.py",
    "research/nexus_mean_reversion_40_m2_momentum30_entry_v1.py",
    "research/nexus_mr40_momentum30_newday_v1.py",
    "product_alternative_market.py", "paper_exchange_simulator.py",
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def seal(value):
    core = {k:v for k,v in value.items() if k != "digest"}
    return {**core, "digest": digest(core)}


def utc(ms):
    return datetime.fromtimestamp(ms/1000, timezone.utc).isoformat()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sources(source, manifest_sha):
    raw = (source / "SOURCE_MANIFEST.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest_sha:
        raise ValueError("source_manifest_substitution")
    manifest = json.loads(raw)
    if set(manifest["files"]) != set(BUNDLE_FILES):
        raise ValueError("source_bundle_members_changed")
    for name, expected in manifest["files"].items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest() != expected:
            raise ValueError("source_file_changed: " + name)
    study = load("isolated_mr40_study", source / BUNDLE_FILES[1])
    return (study.load_sources(source),
            load("isolated_lbank_public_book", source / BUNDLE_FILES[2]),
            load("isolated_pure_paper_simulator", source / "paper_exchange_simulator.py"))


def atomic(path, value):
    raw = value if isinstance(value, bytes) else canonical(value)+b"\n"
    fd, temporary = tempfile.mkstemp(prefix=".mr40-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def writer(root):
    root = root.absolute()
    for candidate in (root, *root.parents):
        if candidate.exists() and (candidate.is_symlink() or getattr(candidate.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("research_root_link_rejected")
    root.mkdir(parents=True, exist_ok=True)
    with (root/"writer.lock").open("a+b") as handle:
        handle.seek(0); handle.write(b"0"); handle.flush(); handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def new_state(now_ms, source_sha, manifest_sha, instrument):
    if len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha):
        raise ValueError("exact_source_commit_required")
    first = (now_ms//STEP+1)*STEP
    return seal({"schema":SCHEMA, "policy":POLICY, "source_sha":source_sha,
        "manifest_sha256":manifest_sha, "activated_ms":now_ms, "first_execution_bar_ms":first,
        "trial_end_ms":first+POLICY["trial_days"]*86_400_000,
        "instrument":instrument, "cash":"500", "quantity":"0", "fees_paid":"0",
        "realized_pnl":"0", "equity":"500", "peak_equity":"500", "max_drawdown_pct":"0",
        "last_execution_bar_ms":None, "last_history_end_ms":None, "history_rows":[],
        "entry":None, "fills":[], "closed_positions":[], "events":[],
        "last_success_ms":None, "last_mid_usdt":None, "last_target":0})


def verify(state, source_sha, manifest_sha):
    if (seal(state) != state or state.get("schema") != SCHEMA or state.get("policy") != POLICY
            or state.get("source_sha") != source_sha or state.get("manifest_sha256") != manifest_sha):
        raise ValueError("paper_identity_or_digest_changed")
    if Decimal(state["cash"]) < 0 or Decimal(state["quantity"]) < 0:
        raise ValueError("negative_cash_or_leveraged_position")
    if (Decimal(state["quantity"]) > 0) != (state["entry"] is not None):
        raise ValueError("paper_position_entry_mismatch")
    previous = "0"*64
    for number, event in enumerate(state["events"], 1):
        if seal(event) != event or event["previous_digest"] != previous or event["sequence"] != number:
            raise ValueError("paper_event_chain_changed")
        previous = event["digest"]
    cash, units, fees, realized, entry_cash = Decimal(500), Decimal(0), Decimal(0), Decimal(0), None
    for fill in state["fills"]:
        qty, notional, fee = map(Decimal, (fill["quantity"],fill["notional_usdt"],fill["fee_usdt"]))
        if fill["filled_ms"] < state["first_execution_bar_ms"] or fill["filled_ms"] < fill["signal_available_ms"]:
            raise ValueError("backdated_or_future_fill")
        if fill["side"] == "buy":
            if units or qty <= 0: raise ValueError("duplicate_entry")
            entry_cash = cash; cash -= notional+fee; units = qty
        elif fill["side"] == "sell":
            if qty != units or entry_cash is None: raise ValueError("orphan_exit")
            cash += notional-fee; units = Decimal(0); realized += cash-entry_cash; entry_cash = None
        else:
            raise ValueError("invalid_fill_side")
        fees += fee
    if (cash,units,fees,realized) != tuple(Decimal(state[k]) for k in ("cash","quantity","fees_paid","realized_pnl")):
        raise ValueError("paper_cashflow_replay_mismatch")


def history(body, end_ms, code):
    if (body.get("result") not in (True,"true") or type(body.get("error_code")) is not int
            or body["error_code"] != 0):
        raise ValueError("public_history_provider_failure")
    native = code["validator"](body["data"])
    if any(r[0]*1000 % STEP for r in native): raise ValueError("off_grid_history")
    rows = sorted(([r[0]*1000,*r[1:]] for r in native if r[0]*1000 < end_ms), key=lambda r:r[0])
    code["core"].validate_frame(rows)
    if [r[0] for r in rows] != list(range(POLICY["history_start_ms"],end_ms,STEP)):
        raise ValueError("closed_history_incomplete")
    return rows


def instrument_from(body):
    if body.get("result") not in (True,"true") or body.get("error_code") != 0 or len(body.get("data",[])) != 1:
        raise ValueError("instrument_schema_failure")
    item = body["data"][0]
    precision = int(item["quantityAccuracy"])
    if item["symbol"] != "btc_usdt" or not 0 <= precision <= 8:
        raise ValueError("instrument_identity_failure")
    result = {"quantity_step":str(Decimal(1).scaleb(-precision)),
              "minimum_quantity":str(Decimal(item["minTranQua"])),
              "minimum_notional_usdt":str(Decimal(item["minOrderAmount"]))}
    if any(not Decimal(x).is_finite() or Decimal(x) <= 0 for x in result.values()):
        raise ValueError("invalid_instrument_limits")
    return result


def fill(state, side, books, book, simulator, now_ms, signal_ms, reason):
    cash, held = Decimal(state["cash"]), Decimal(state["quantity"])
    fee, slip = Decimal(POLICY["fee_rate"]), Decimal(POLICY["extra_adverse_slippage_bps"])/10000
    step = Decimal(state["instrument"]["quantity_step"])
    if side == "buy":
        raw_quote = cash/((1+fee)*(1+slip))
        raw_vwap = book.walk(books["asks"],raw_quote,True)
        quantity = (raw_quote/raw_vwap/step).to_integral_value(rounding=ROUND_DOWN)*step
    else:
        quantity = held
    if quantity < Decimal(state["instrument"]["minimum_quantity"]):
        raise ValueError("quantity_below_venue_minimum")
    # False selects a base-quantity walk; asks/bids already have the correct order.
    reference = book.walk(books["asks" if side == "buy" else "bids"],quantity,False)
    if quantity*reference < Decimal(state["instrument"]["minimum_notional_usdt"]):
        raise ValueError("notional_below_venue_minimum")
    outcome = simulator.simulate_paper_order(order={"order_id":f"mr40-{signal_ms}-{side}",
        "symbol":"btc_usdt", "side":side, "quantity":str(quantity),
        "reference_price":str(reference), "fee_rate":str(fee),
        "slippage_bps":POLICY["extra_adverse_slippage_bps"]},
        profile={"latency_ms":0,"per_fill_quantity":str(quantity),"max_fills":1})
    item = outcome.fills[0]
    notional = (item.quantity*item.price).quantize(Decimal("0.00000001"))
    after = cash-notional-item.fee if side == "buy" else cash+notional-item.fee
    if after < 0: raise ValueError("cash_budget_exceeded")
    event = {"fill_id":item.fill_id,"side":side,"filled_ms":now_ms,"filled_utc":utc(now_ms),
        "signal_available_ms":signal_ms,"delay_ms":now_ms-signal_ms,"reason":reason,
        "quantity":str(quantity),"reference_vwap_usdt":str(reference),"price_usdt":str(item.price),
        "notional_usdt":str(notional),"fee_usdt":str(item.fee),
        "extra_model_slippage_usdt":str(item.slippage_cost),"paper_only":True}
    if side == "buy":
        state["entry"] = {"cash_before":str(cash), **event}
        state["quantity"] = str(quantity)
    else:
        entry = state["entry"]
        pnl = after-Decimal(entry["cash_before"])
        state["closed_positions"].append({"entry":entry,"exit":event,"net_pnl_usdt":str(pnl)})
        state["realized_pnl"] = str(Decimal(state["realized_pnl"])+pnl)
        state["quantity"], state["entry"] = "0", None
    state["cash"] = str(after)
    state["fees_paid"] = str(Decimal(state["fees_paid"])+item.fee)
    state["fills"].append(event)


def advance(old, rows, books, code, book, simulator, now_ms, receipt_refs):
    state = deepcopy(old)
    end_ms = now_ms//STEP*STEP
    code["core"].validate_frame(rows)
    if [r[0] for r in rows] != list(range(POLICY["history_start_ms"],end_ms,STEP)):
        raise ValueError("missing_closed_history")
    prefix = old["history_rows"]
    if len(rows) < len(prefix) or any(a[0] != b[0] or any(Decimal(x)!=Decimal(y) for x,y in zip(a[1:],b[1:]))
                                   for a,b in zip(prefix,rows)):
        raise ValueError("accepted_closed_history_revised")
    state["history_rows"], state["last_history_end_ms"] = rows, end_ms
    action, decisions = "waiting_first_boundary", []
    if (end_ms >= state["first_execution_bar_ms"] and end_ms != state["last_execution_bar_ms"]):
        first = next(i for i,r in enumerate(rows) if r[0] == state["first_execution_bar_ms"]-STEP)
        raw = code["core"].targets(rows)
        if raw != code["core"].decimal_targets(rows): raise ValueError("signal_decimal_mismatch")
        target, decisions = code["gate"].admit_episodes(rows,raw,first,len(rows))
        if target != code["gate"].independent_admission(rows,raw,first,len(rows)):
            raise ValueError("admission_decimal_mismatch")
        desired, held = target[-1], Decimal(state["quantity"]) > 0
        is_new_episode = any(d["accepted"] and d["decision_index"] == len(rows)-1 for d in decisions)
        action = "hold_position" if held else "wait_signal"
        if held and not desired:
            fill(state,"sell",books,book,simulator,now_ms,end_ms,"signal_exit" if now_ms-end_ms <= POLICY["max_entry_delay_ms"] else "delayed_signal_exit")
            action = "paper_sell"
        elif desired and not held:
            if is_new_episode and now_ms-end_ms <= POLICY["max_entry_delay_ms"]:
                fill(state,"buy",books,book,simulator,now_ms,end_ms,"fresh_episode_entry")
                action = "paper_buy"
            else:
                action = "entry_skipped_no_late_entry"
        previous = state["events"][-1]["digest"] if state["events"] else "0"*64
        last = state["last_execution_bar_ms"] or state["first_execution_bar_ms"]-STEP
        state["events"].append(seal({"sequence":len(state["events"])+1,"previous_digest":previous,
            "execution_boundary_ms":end_ms,"observed_ms":now_ms,"action":action,"target":desired,
            "skipped_prior_boundaries":max(0,(end_ms-last)//STEP-1),"receipts":receipt_refs,
            "history_rows_sha256":digest(rows)}))
        state["last_execution_bar_ms"], state["last_target"] = end_ms, desired
    elif end_ms >= state["first_execution_bar_ms"]:
        action = "hold_position" if Decimal(state["quantity"]) else "wait_signal"
    mid = (books["asks"][0][0]+books["bids"][0][0])/2
    equity = Decimal(state["cash"])+Decimal(state["quantity"])*mid
    peak = max(Decimal(state["peak_equity"]),equity)
    state.update(equity=str(equity),peak_equity=str(peak),last_success_ms=now_ms,last_mid_usdt=str(mid),
                 max_drawdown_pct=str(max(Decimal(state["max_drawdown_pct"]),(1-equity/peak)*100)))
    state = seal(state)
    verify(state,state["source_sha"],state["manifest_sha256"])
    return state, action


def dashboard(state, status):
    if state is None:
        return ("<!doctype html><meta charset='utf-8'><meta http-equiv='refresh' content='60'><body dir='rtl'>"
                "<h1>NEXUS · Paper پژوهشی LBank</h1><p>آزمون هنوز فعال نشده است.</p><pre>"+
                html.escape(json.dumps(status,ensure_ascii=False))+"</pre>").encode()
    esc = lambda x: html.escape(str(x))
    money = lambda x: f"{Decimal(x):,.4f}"
    pnl = Decimal(state["equity"])-500
    fills = "".join("<tr>"+"".join(f"<td>{esc(v)}</td>" for v in
        (f["filled_utc"],f["side"],f["quantity"],f["price_usdt"],f["fee_usdt"]))+"</tr>" for f in reversed(state["fills"]))
    body = f"""<!doctype html><html lang='fa' dir='rtl'><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='60'>
<title>NEXUS · MR40 LBank Paper</title><style>body{{background:#101722;color:#e6edf6;font:16px Tahoma,sans-serif;margin:30px auto;padding:18px;max-width:1000px;line-height:1.9}}h1{{font-size:26px}}.tag{{color:#69dbb5}}.cards{{display:flex;flex-wrap:wrap;gap:14px}}.card{{background:#1b2737;border-radius:14px;padding:18px;min-width:170px}}b{{font-size:23px;display:block}}table{{width:100%;text-align:right;font-size:14px;border-collapse:collapse}}td,th{{padding:10px;border-bottom:1px solid #334257}}.muted{{color:#acb9cb}}.warn{{color:#ffc875}}code{{direction:ltr;display:inline-block}}a{{color:#79bcff}}</style>
<h1>NEXUS · MR40 + Momentum30</h1><p class='tag'>Paper پژوهشی مستقل · LBank Spot · BTC/USDT · ۴ ساعته</p>
<p>تمام موجودی و معاملات این صفحه مجازی‌اند. سفارش صرافی ارسال نمی‌شود.</p>
<div class='cards'><div class='card'>ارزش حساب، تتر<b>{money(state['equity'])}</b></div>
<div class='card'>سود و زیان، تتر<b>{pnl:+,.4f}</b></div><div class='card'>موجودی نقد، تتر<b>{money(state['cash'])}</b></div>
<div class='card'>مقدار BTC<b>{esc(state['quantity'])}</b></div></div>
<p id='health'>وضعیت: <code>{esc(status['status'])}</code></p><p class='muted'>آخرین دادهٔ معتبر UTC: <code>{esc(utc(state['last_success_ms']))}</code></p>
<p>شروع ثبت: <code>{esc(utc(state['activated_ms']))}</code><br>اولین مرز مجاز معامله: <code>{esc(utc(state['first_execution_bar_ms']))}</code><br>
پایان آزمون ۳۰ روزه: <code>{esc(utc(state['trial_end_ms']))}</code></p>
<p>کارمزد مرجع هر سمت: ۰٫۱٪؛ لغزش محافظه‌کارانه: ۰٫۰۵٪ اضافه بر VWAP دفتر سفارش. دقت حجم و حداقل سفارش LBank رعایت می‌شود.</p>
<p>کارمزد مدل‌شده: {money(state['fees_paid'])} تتر · معاملات بسته: {len(state['closed_positions'])} · افت ارزش نمونه‌برداری‌شده: {Decimal(state['max_drawdown_pct']):.3f}٪</p>
<h2>رویدادهای خرید و فروش مجازی</h2><div style='overflow:auto'><table><tr><th>زمان UTC</th><th>سمت</th><th>مقدار BTC</th><th>قیمت، تتر</th><th>کارمزد، تتر</th></tr>{fills or '<tr><td colspan=5>هنوز معامله‌ای ثبت نشده است؛ منتظر سیگنال آینده هستیم.</td></tr>'}</table></div>
<p class='muted'>صفحه هر ۶۰ ثانیه تازه می‌شود. نمایش جدا از حساب اصلی بای‌بیت است.</p>
<script>const last={state['last_success_ms']};if(Date.now()-last>180000){{document.getElementById('health').textContent='داده تازه نیست؛ وضعیت اجرای آزمون باید بررسی شود';document.getElementById('health').className='warn'}}</script></html>"""
    return body.encode()


def run_once(source, root, source_sha, manifest_sha):
    code, book, simulator = sources(source,manifest_sha)
    with writer(root):
        state, now_ms = None, int(time.time()*1000)
        sp, ap = root/"state.json", root/"activation.json"
        if sp.exists() != ap.exists(): raise ValueError("orphan_activation_or_state_no_capital_reset")
        if sp.exists():
            state = json.loads(sp.read_bytes()); verify(state,source_sha,manifest_sha)
            activation = json.loads(ap.read_bytes())
            if seal(activation) != activation or activation["activated_ms"] != state["activated_ms"]:
                raise ValueError("activation_changed")
        try:
            if (root/"STOP").exists():
                action = "stopped_by_owner"
            elif (root/"PAUSE").exists():
                action = "paused_after_public_access_denial"
            elif state is not None and now_ms >= state["trial_end_ms"]:
                action = "trial_complete_open_position_marked" if Decimal(state["quantity"]) else "trial_complete"
            else:
                end_ms = now_ms//STEP*STEP
                refs, receipts = {}, {}
                if state is None or state["last_history_end_ms"] != end_ms:
                    count = (end_ms-POLICY["history_start_ms"])//STEP+1
                    if not 222 <= count <= 2000: raise ValueError("history_size_outside_trial_contract")
                    body, receipt = book.fetch("/v2/kline.do",{"symbol":"btc_usdt","type":"hour4", "time":str(POLICY["history_start_ms"]//1000),"size":str(count)})
                    if type(body.get("ts")) is not int or not -10000 <= int(time.time()*1000)-body["ts"] <= 120000:
                        raise ValueError("history_response_not_fresh")
                    rows = history(body,end_ms,code)
                    refs["history"] = receipt["body_sha256"]; receipts[receipt["body_sha256"]] = receipt
                    metadata, receipt = book.fetch("/v2/accuracy.do",{"symbol":"btc_usdt"})
                    instrument = instrument_from(metadata)
                    if state is not None and instrument != state["instrument"]: raise ValueError("instrument_rules_changed")
                    refs["instrument"] = receipt["body_sha256"]; receipts[receipt["body_sha256"]] = receipt
                else:
                    rows, instrument = state["history_rows"], state["instrument"]
                body, receipt = book.fetch("/v2/depth.do",{"symbol":"btc_usdt","size":"200"})
                observed = int(time.time()*1000)
                books = book.parse_book(body,observed)
                if observed//STEP != end_ms//STEP: raise ValueError("boundary_changed_during_intake_retry_next_tick")
                refs["depth"] = receipt["body_sha256"]; receipts[receipt["body_sha256"]] = receipt
                candidate = state
                if candidate is None:
                    candidate = new_state(observed,source_sha,manifest_sha,instrument)
                    activation = seal({"schema":SCHEMA,"activated_ms":observed,"source_sha":source_sha,
                        "manifest_sha256":manifest_sha,"first_execution_bar_ms":candidate["first_execution_bar_ms"],
                        "trial_end_ms":candidate["trial_end_ms"],"policy":POLICY,"initial_cash_usdt":"500"})
                next_state, action = advance(candidate,rows,books,code,book,simulator,observed,refs)
                if next_state["events"] != candidate["events"] or not ap.exists():
                    rr = root/"receipts"; rr.mkdir(exist_ok=True)
                    for sha,item in receipts.items(): atomic(rr/(sha+".json"),item)
                if not ap.exists(): atomic(ap,activation)
                atomic(sp,next_state); state = next_state
            status = seal({"schema":SCHEMA,"status":action,"checked_ms":int(time.time()*1000),
                "activated":state is not None,"paper_only":True,"live_enabled":False,"exchange_orders":0,
                "state_digest":None if state is None else state["digest"]})
        except Exception as exc:
            if getattr(exc,"code",None) in (403,429,451):
                atomic(root/"PAUSE",("public_http_"+str(exc.code)+"; manual review before another request\n").encode())
            status = seal({"schema":SCHEMA,"status":"data_or_execution_blocked","checked_ms":int(time.time()*1000),
                "activated":state is not None and ap.exists(),"reason":type(exc).__name__+": "+str(exc)[:160],
                "paper_only":True,"live_enabled":False,"exchange_orders":0})
        atomic(root/"status.json",status)
        atomic(root/"dashboard.html",dashboard(state,status))
        print(json.dumps({**status,"cash":None if state is None else state["cash"],
            "quantity":None if state is None else state["quantity"],"fills":None if state is None else len(state["fills"])}),flush=True)
        return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--state-root",type=Path,required=True)
    parser.add_argument("--source-sha",required=True)
    parser.add_argument("--manifest-sha",required=True)
    args = parser.parse_args()
    result = run_once(args.source,args.state_root,args.source_sha,args.manifest_sha)
    if result["status"] == "data_or_execution_blocked": sys.exit(2)
