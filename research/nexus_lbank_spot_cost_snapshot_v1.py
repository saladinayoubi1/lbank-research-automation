"""Three bounded public LBank depth samples; no orders or private requests."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib, json, time, urllib.parse, urllib.request
from pathlib import Path

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("public_redirect_rejected")

def positive(value):
    if isinstance(value, bool):
        raise ValueError("boolean_decimal")
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError("nonpositive_or_nonfinite_depth")
    return result

def parse_book(body, observed_ms):
    if (body.get("result") not in (True, "true") or type(body.get("error_code")) is not int
            or body["error_code"] != 0 or not isinstance(body.get("data"), dict)):
        raise ValueError("invalid_public_book_envelope")
    data = body["data"]
    for stamp in (body.get("ts"), data.get("timestamp")):
        if type(stamp) is not int or not -10000 <= observed_ms-stamp <= 15000:
            raise ValueError("book_not_fresh")
    books = {}
    for side in ("asks", "bids"):
        raw = data.get(side)
        if not isinstance(raw, list) or not 1 <= len(raw) <= 200:
            raise ValueError("invalid_depth_size")
        if any(not isinstance(r,list) or len(r)!=2 for r in raw):
            raise ValueError("invalid_depth_row")
        levels = [(positive(r[0]), positive(r[1])) for r in raw]
        prices = [p for p,q in levels]
        if len(set(prices)) != len(prices):
            raise ValueError("duplicate_depth_price")
        if prices != sorted(prices) and prices != sorted(prices,reverse=True):
            raise ValueError("unordered_depth")
        books[side] = sorted(levels, reverse=(side=="bids"))
    if books["bids"][0][0] >= books["asks"][0][0]:
        raise ValueError("locked_or_crossed_book")
    return books

def walk(levels, amount, buy):
    remaining, units, quote = amount, Decimal(0), Decimal(0)
    for price, size in levels:
        take = min(size, remaining/price if buy else remaining)
        units += take
        quote += take*price
        remaining -= take*price if buy else take
        if remaining <= Decimal("1e-35"):
            return quote/units
    raise ValueError("insufficient_visible_depth")

def measure(books, notional):
    ask, bid = books["asks"][0][0], books["bids"][0][0]
    mid = (ask+bid)/2
    buy = walk(books["asks"],Decimal(notional),True)
    sell = walk(books["bids"],Decimal(notional)/mid,False)
    return {"notional_usdt":notional,"mid_usdt":str(mid),
            "full_spread_bps":str((ask-bid)/mid*10000),
            "buy_vwap_usdt":str(buy),"sell_vwap_usdt":str(sell),
            "buy_shortfall_from_mid_bps":str((buy/mid-1)*10000),
            "sell_shortfall_from_mid_bps":str((1-sell/mid)*10000),
            "buy_walk_beyond_best_ask_bps":str((buy/ask-1)*10000),
            "sell_walk_beyond_best_bid_bps":str((1-sell/bid)*10000)}

def fetch(path, params):
    url = "https://api.lbank.info"+path+"?"+urllib.parse.urlencode(params)
    req = urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"NEXUS-public-cost-research/1"})
    start = datetime.now(timezone.utc).isoformat()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with opener.open(req,timeout=12) as response:
        raw = response.read(1_000_001)
        status, date = response.status, response.headers.get("Date")
    if len(raw)>1_000_000 or status!=200:
        raise ValueError("public_response_rejected")
    body=json.loads(raw,parse_float=str)
    return body,{"url":url,"started_at_utc":start,
                "finished_at_utc":datetime.now(timezone.utc).isoformat(),
                "http_status":status,"response_date":date,
                "body_sha256":hashlib.sha256(raw).hexdigest(),
                "raw_body":raw.decode()}

def probe(output):
    if output.exists():
        raise ValueError("refuse_existing_probe")
    body, accuracy = fetch("/v2/accuracy.do",{"symbol":"btc_usdt"})
    if body.get("result") not in (True,"true") or body.get("error_code")!=0:
        raise ValueError("accuracy_envelope_rejected")
    samples=[]
    for index in range(3):
        if index:
            time.sleep(2)
        body,receipt=fetch("/v2/depth.do",{"symbol":"btc_usdt","size":"200"})
        observed=int(time.time()*1000)
        books=parse_book(body,observed)
        sample={"observed_ms":observed,"receipt":receipt,"measurements":[measure(books,n) for n in (500,10000)]}
        samples.append(sample)
    result={"schema":"nexus.lbank-current-public-depth-cost.v1","samples":samples,
            "accuracy_receipt":accuracy,"executed_utc":datetime.now(timezone.utc).isoformat(),
            "driver_sha256":hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n",b"\n")).hexdigest(),
            "account_fee_verified":False,"actual_historical_slippage_measured":False,
            "exchange_orders":0,"live_enabled":False}
    result["digest"]=digest(result)
    output.write_bytes(canonical(result)+b"\n")
    print(json.dumps({"digest":result["digest"],"accuracy":json.loads(accuracy["raw_body"]),
        "measurements":[{"observed_ms":s["observed_ms"],"values":s["measurements"]} for s in samples]}),flush=True)

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    probe(parser.parse_args().output)
