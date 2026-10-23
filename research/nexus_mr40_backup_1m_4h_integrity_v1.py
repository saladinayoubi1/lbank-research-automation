"""Single fixed one-shot public research backup Spot BTC 1m -> 4h quality audit.

NO exchange/auth/private API/orders/schedulers. NEVER claim Bybit equivalence.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

STEP4=14_400_000
STEP1=60_000
Q=D("0.00000001")
VENUES=("Bitget","LBank")


def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def utc(ms):
    return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()


def make_url(venue,interval,start):
    if venue=="Bitget":
        return "https://api.bitget.com/api/v3/market/candles?"+urllib.parse.urlencode({
            "category":"SPOT","symbol":"BTCUSDT","interval":"1m" if interval=="1m" else "4H",
            "limit":800 if interval=="1m" else 10,
        })
    if venue=="LBank":
        return "https://api.lbank.info/v2/kline.do?"+urllib.parse.urlencode({
            "symbol":"btc_usdt","size":400 if interval=="1m" else 10,
            "type":"minute1" if interval=="1m" else "hour4",
            "time":(start//1000-60) if interval=="1m" else (start//1000-4*3600),
        })
    raise ValueError("unapproved_venue")


def fetch(url):
    request=urllib.request.Request(url,headers={"User-Agent":"NEXUS-MR40-Public-Research-Only/1.0"})
    with urllib.request.urlopen(request,timeout=9) as resp:
        if resp.status!=200:raise ValueError("public_http_non_200")
        raw=resp.read(500000)
    if len(raw)>=500000:raise ValueError("response_size_limit")
    return {"url":url,"received_utc_ms":int(time.time()*1000),
            "body_sha256":hashlib.sha256(raw).hexdigest(),
            "raw_json":json.loads(raw)}


def parse(source,venue,interval):
    if venue=="Bitget":
        if source.get("code")!="00000":raise ValueError("bitget_status_not_ok")
        data=source.get("data")
    elif venue=="LBank":
        if str(source.get("result")).lower()!="true" or source.get("error_code")!=0:
            raise ValueError("lbank_status_not_ok")
        data=source.get("data")
    else:raise ValueError("unknown_venue")
    if not isinstance(data,list):raise ValueError("missing_candles")
    millis=venue=="Bitget"
    ts_factor=1 if millis else 1000
    step=STEP1 if interval=="1m" else STEP4
    ret={}
    for item in data:
        if not isinstance(item,list) or len(item)<6:raise ValueError("malformed_row")
        bar=int(item[0])*ts_factor
        if bar%step:raise ValueError("not_utc_aligned_interval")
        if bar in ret:raise ValueError("duplicate_open_time")
        o,h,l,c,v=[D(str(x)) for x in item[1:6]]
        if (not all(x.is_finite() for x in (o,h,l,c,v))
            or min(o,h,l,c)<=0 or v<0 or h<max(o,c) or l>min(o,c)):
            raise ValueError("invalid_ohlcv")
        ret[bar]=(o,h,l,c,v)
    return ret


def evaluate(rows_1m,rows_4h,target,asof_ms,p):
    limit_price=D(p["requirements"]["price_abs_tolerance_usdt"])
    limit_volume=D(p["requirements"]["base_volume_rel_tolerance"])
    matched=[rows_1m.get(target+i*STEP1) for i in range(240)]
    missing=[target+i*STEP1 for i,v in enumerate(matched) if v is None]
    output={"target_start_utc":utc(target),"target_end_utc":utc(target+STEP4),
            "minute_rows_required":240,
            "minute_rows_found":240-len(missing),
            "missing_minute_starts_utc":[utc(i) for i in missing[:8]],
            "target_4h_present":target in rows_4h,
            "latest_bar_strictly_closed":(target+STEP4+120000)<=asof_ms,
            "market_source_gate_pass":False,
            "bybit_4h_1m_quality_proven":False}
    if not output["latest_bar_strictly_closed"] or missing or target not in rows_4h:
        output["reason"]="missing_or_unclosed_data"
        return output
    o=matched[0][0]; h=max(v[1] for v in matched); l=min(v[2] for v in matched)
    c=matched[-1][3]; v=sum((r[4] for r in matched),D(0))
    old=rows_4h[target]
    errors={name:str(abs(value-old_i)) for name,value,old_i in zip(
        ("open","high","low","close"),(o,h,l,c),old[:4])}
    max_abs=max(D(v) for v in errors.values())
    volume_abs=abs(v-old[4]);volume_rel=(volume_abs/max(v,old[4])) if max(v,old[4])>0 else D(0)
    passed=(max_abs<=limit_price and volume_rel<=limit_volume)
    output.update({
        "reconstructed":{name:str(x) for name,x in zip(("open","high","low","close","base_volume"),(o,h,l,c,v))},
        "published_4h":{name:str(x) for name,x in zip(("open","high","low","close","base_volume"),old)},
        "absolute_price_differences_usdt":errors,
        "base_volume_absolute_diff":str(volume_abs),
        "base_volume_relative_diff":str(volume_rel),
        "price_abs_tolerance_usdt":str(limit_price),
        "volume_rel_tolerance":str(limit_volume),
        "market_source_gate_pass":bool(passed),
        "reason":"pass" if passed else "price_or_volume_reconstruction_mismatch"
    })
    return output


def execute(protocol_path,output_path):
    if output_path.exists():raise ValueError("refuse_overwrite")
    policy=json.loads(protocol_path.read_bytes())
    if (policy["schema"]!="nexus.mr40.backup_4h_1m_source_integrity.v1"
        or policy["requirements"]["min_1m_bars_per_4h"]!=240
        or policy["safety"]["orders"]!=0 or policy["safety"]["live"] is not False):
        raise ValueError("protocol_changed")
    anchor=int(time.time()*1000)
    target=( (anchor-120000)//STEP4 )*STEP4 -STEP4
    source_data={}
    result={}
    for venue in VENUES:
        receipts={}
        try:
            for interval in ("4h","1m"):
                url=make_url(venue,interval,target)
                receipts[interval]=fetch(url)
            minute=parse(receipts["1m"]["raw_json"],venue,"1m")
            four=parse(receipts["4h"]["raw_json"],venue,"4h")
            evaluated=evaluate(minute,four,target,anchor,policy)
            source_data[venue]=receipts
            result[venue]={**evaluated,"four_hour_rows_returned":len(four),
                           "one_minute_rows_returned":len(minute)}
        except Exception as exc:
            # Persist the negative result; never silently proceed to another bar.
            source_data[venue]=receipts
            result[venue]={"market_source_gate_pass":False,
                "bybit_4h_1m_quality_proven":False,
                "reason":"request_or_validation_failed",
                "exception_type":type(exc).__name__,
                "detail":str(exc)[:240]}
    doc={"schema":"nexus.mr40.backup_4h_1m_source_integrity.result.v1",
         "protocol_sha256":hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
         "anchor_utc_ms":anchor,"anchor_utc":utc(anchor),
         "target_4h_start_utc_ms":target,"target_4h_start_utc":utc(target),
         "venue_results":result,
         "public_source_receipts":source_data,
         "both_backup_same_venue_aggregation_pass":all(result[k]["market_source_gate_pass"] for k in VENUES),
         "bybit_reference_source_gate_pass":False,
         "genuine_unseen_forward_trading_validation":False,
         "paper_modified":False,"orders_sent":0,"private_api_used":False,
         "live_enabled":False,"merge":False,"promote":False}
    doc["digest"]=hashlib.sha256(canonical(doc)).hexdigest()
    output_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_text(json.dumps(doc,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({
        "digest":doc["digest"],"target_utc":doc["target_4h_start_utc"],
        "results":result,"bybit_source_gate":False},ensure_ascii=False))


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--protocol",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    a=ap.parse_args()
    execute(a.protocol,a.output)
