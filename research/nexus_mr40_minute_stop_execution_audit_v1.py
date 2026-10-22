"""MR40 single-event minute-price execution uncertainty audit.

Uses public Bybit SPOT 1-minute Klines only. No key, no private endpoints,
no trading, no strategy tuning. Reject all scenario valuations if 4h parity fails.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,urllib.parse,urllib.request
from decimal import Decimal as D,ROUND_DOWN
from pathlib import Path

OHLC_SHA="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
LEDGER_SHA="2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e"
INTERVAL=60000
UTC=dt.timezone.utc
def canon(x):return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def iso(t):return dt.datetime.fromtimestamp(t/1000,UTC).isoformat()
def main(protocol,inputs,ledger,output):
    if output.exists():raise RuntimeError("output_dir_exists")
    cfg=json.loads(protocol.read_bytes())
    if cfg["schema"]!="mr40.20251010.spot-minute-stop-audit.v1":raise ValueError("bad_protocol")
    req=cfg["request"]
    if (req["category"],req["symbol"],req["interval"],req["start"],req["end"],req["limit"])!=("spot","BTCUSDT","1",1760112000000,1760155200000,1000):raise ValueError("unregistered_request")
    original=json.loads((inputs/"bybit_prepared_inputs.json").read_bytes())
    extension=json.loads((inputs/"bybit_october_input_extension.json").read_bytes())
    all4=original["rows"]+extension["rows"]
    if hashlib.sha256(canon(all4)).hexdigest()!=OHLC_SHA:raise ValueError("original_market_sha_mismatch")
    if hashlib.sha256(ledger.read_bytes()).hexdigest()!=LEDGER_SHA:raise ValueError("original_trade_ledger_sha_mismatch")
    position=None
    with gzip.open(ledger,"rt",encoding="utf-8") as fh:
        for line in fh:
            o=json.loads(line);k=o["key"]
            if (k["venue"],k["window"],k["capital"],k["profile"],k["case"])==("Bybit","evaluation",10000,"normal","baseline"):
                position=next(p for p in o["positions"] if p["entry"]["fill_ms"]==req["start"])
                break
    if position is None:raise ValueError("original_entry_absent")
    buy=position["entry"]
    if buy["side"]!="buy" or buy["fill_ms"]!=req["start"]:raise ValueError("entry_reconciliation")
    qty=D(buy["quantity"]);entry=D(buy["price"])
    cash_after_buy=D(buy["cash_after"]);initial_cash=D(buy["cash_before"])
    if abs(float(entry)-119075.40795)>0.000001 or abs(initial_cash-cash_after_buy-D(buy["notional"])-D(buy["fee"]))>D("0.00000001"):\n        raise ValueError("original_entry_ledger_accounting_mismatch")
    stop=entry*D(".96")
    params=urllib.parse.urlencode(req)
    url=cfg["source_uri"]+"?"+params
    request=urllib.request.Request(url,headers={"User-Agent":"NEXUS-Research-Public-OHLC/1.0","Accept":"application/json"})
    with urllib.request.urlopen(request,timeout=18) as response:
        status=response.status;raw=response.read(2_000_000)
    if status!=200 or len(raw)>=2_000_000:raise RuntimeError("public_api_unavailable_or_too_large")
    payload=json.loads(raw)
    if payload.get("retCode")!=0 or payload.get("result",{}).get("category")!="spot" or payload["result"]["symbol"]!="BTCUSDT":
        raise ValueError("public_api_wrong_product_or_code")
    klines=payload["result"]["list"]
    extra=[int(r[0]) for r in klines if int(r[0])<req["start"] or int(r[0])>=req["end"]]
    selected=sorted((r for r in klines if req["start"]<=int(r[0])<req["end"]),key=lambda r:int(r[0]))
    if len(selected)!=720:raise ValueError("one_minute_missing_or_pagination_required:"+str(len(selected)))
    if [int(r[0]) for r in selected] !=list(range(req["start"],req["end"],INTERVAL)):raise ValueError("missing_or_duplicate_minute")
    for r in selected:
        if len(r)<7:raise ValueError("truncated_kline")
        t,o,h,l,c,v,turn=r[:7]
        op,hi,lo,cl,volume,turnover=map(D,(o,h,l,c,v,turn))
        if not (lo<=op<=hi and lo<=cl<=hi and volume>=0 and turnover>=0):raise ValueError("bad_candle_price")
    expected=[r for r in all4 if r[0] in (1760112000000,1760126400000,1760140800000)]
    if len(expected)!=3:raise ValueError("parent_4h_rows_missing")
    parity=[]
    for group in range(3):
        block=selected[group*240:(group+1)*240]
        agg=[D(block[0][1]),max(D(z[2]) for z in block),min(D(z[3]) for z in block),D(block[-1][4])]
        base=expected[group]
        old=[D(str(v)) for v in base[1:5]]
        deltas=[float(abs(a-b)) for a,b in zip(agg,old)]
        parity.append({"4h_start_utc":iso(base[0]),
                       "minute_aggregated_ohlc":[str(z) for z in agg],
                       "frozen_original_ohlc":[str(z) for z in old],
                       "absolute_deltas_usdt":deltas,
                       "within_0p01_usdt":all(x<=.01 for x in deltas)})
    parity_pass=all(x["within_0p01_usdt"] for x in parity)
    report={"schema":"mr40.20251010.spot-minute-stop-audit.results.v1",
            "protocol_sha256":hashlib.sha256(protocol.read_bytes()).hexdigest(),
            "public_source":{"url":url,"raw_response_sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),
                             "rows_server":len(klines),"in_scope_rows":len(selected),"outside_scope_timestamps":extra},
            "frozen_sources":{"4h_frame_sha256":OHLC_SHA,"original_trade_ledger_sha256":LEDGER_SHA},
            "original_entry":{"entry_utc":iso(buy["fill_ms"]),"fill_price":str(entry),"quantity_btc":str(qty),
                              "cash_after_entry":str(cash_after_buy),"initial_cash":str(initial_cash),"initial_stop4_price":str(stop)},
            "four_hour_reconciliation":parity,
            "four_hour_parity_pass":parity_pass,
            "limitation":"Market OHLC (even 1-minute) does not prove executable stop-market price, market order depth, queueing, outage or intra-minute chronology. Reference-price scenarios only."}
    if parity_pass:
        hit_index=next((i for i,z in enumerate(selected) if D(z[3])<=stop),None)
        if hit_index is None:
            report["stop_touch"]={"occurred":False}
        else:
            r=selected[hit_index]
            opens=[D(z[1]) for z in selected]
            hi,lo,cl=map(D,(r[2],r[3],r[4]))
            op=D(r[1]);next_open=opens[hit_index+1] if hit_index+1<len(selected) else None
            price_scenarios={"stop_level_ideal":stop,
                             "first_cross_minute_close_mark":cl,
                             "first_cross_minute_low_worst_mark":lo}
            if next_open is not None:price_scenarios["next_minute_open_mark"]=next_open
            scenarios=[]
            for label,reference in price_scenarios.items():
                item={"reference_case":label,"reference_price":str(reference),
                      "gap_below_stop_pct":round(100*float(1-reference/stop),5)}
                for pname,fee,slip in (("normal",D(".001"),D(".0005")),("stress",D(".0025"),D(".0015"))):
                    execution=reference*(1-slip)
                    pnl=cash_after_buy+qty*execution*(1-fee)-initial_cash
                    item[pname+"_pnl_usdt"]=round(float(pnl),4)
                scenarios.append(item)
            report["stop_touch"]={
                "occurred":True,"minute_start_utc":iso(int(r[0])),"minutes_after_entry_open":hit_index,
                "opened_below_stop":op<=stop,
                "candle":{"open":str(op),"high":str(hi),"low":str(lo),"close":str(cl),
                          "btc_volume":r[5],"quote_turnover_usdt":r[6]},
                "previous_minute_close":selected[hit_index-1][4] if hit_index else None,
                "next_minute_open":str(next_open) if next_open is not None else None,
                "worst_low_over_next_five_minutes":str(min(D(z[3]) for z in selected[hit_index:min(len(selected),hit_index+5)])),
                "same_minute_close_above_stop":cl>=stop,
                "scenario_marks_not_verified_fills":scenarios}
    else:
        report["stop_touch"]={"evaluated":False,"reason":"parent 4h OHLC vs public spot minute mismatch — no fill estimate allowed"}
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    output.mkdir(parents=True)
    (output/"public_api_raw.json").write_bytes(raw)
    (output/"audit.json").write_bytes(canon(report)+b"\n")
    print(json.dumps({"parity":parity_pass,"digest":report["digest"],
                      "one_minute_bars":len(selected),"original_vs_minute":parity,"stop_touch":report["stop_touch"]},ensure_ascii=False),flush=True)

if __name__=="__main__":
    a=argparse.ArgumentParser()
    for n in ("protocol","inputs","ledger","output"):a.add_argument("--"+n,required=True,type=Path)
    main(**vars(a.parse_args()))
