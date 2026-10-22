"""Historical-no-money snapshot diagnostic of PUBLIC Bybit SPOT BTCUSDT L50 bid/ask.

Uses only one public WS snapshot, no private API, no orders, no broker,
and no claim an observed order book is guaranteed executable.
"""
from __future__ import annotations
import argparse,hashlib,json
from datetime import datetime,timezone
from decimal import Decimal as D,localcontext
from pathlib import Path

SCHEMA="nexus.mr40.bybit_public_spot_orderbook50_cost_snapshot.v1"
TOPIC="orderbook.50.BTCUSDT"
URL="wss://stream.bybit.com/v5/public/spot"
QUOTE=D("500")
BPS=D("10000")


def canon(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def validate_side(rows,side):
    if not isinstance(rows,list) or not 1<=len(rows)<=50:
        raise ValueError("not_spot_depth50_source_levels")
    out=[]
    for item in rows:
        if not isinstance(item,list) or len(item)!=2:
            raise ValueError("malformed_spot_book_level")
        try:
            price=D(str(item[0]));size=D(str(item[1]))
        except Exception:
            raise ValueError("nondecimal_book_level") from None
        if not(price.is_finite() and size.is_finite()) or price<=0 or size<=0:
            raise ValueError("invalid_spot_book_price_or_qty")
        if out and (price>=out[-1][0] if side=="bid" else price<=out[-1][0]):
            raise ValueError("nonmonotonic_spot_book_levels")
        out.append((price,size))
    return out


def buy_quote(asks,quote):
    remain=quote;amount=D(0);used=0
    for price,size in asks:
        part=min(remain,price*size)
        if part<=0:break
        amount+=part/price
        remain-=part
        used+=1
        if remain==0:break
    if remain!=0 or amount<=0:raise ValueError("visible_asks_cannot_cover_quote_notional")
    return amount,used


def sell_base(bids,amount):
    remain=amount;received=D(0);used=0
    for price,size in bids:
        part=min(remain,size)
        if part<=0:break
        received+=part*price
        remain-=part
        used+=1
        if remain==0:break
    if remain!=0:raise ValueError("visible_bids_cannot_cover_quote_equivalent_BTC")
    return received,used


def inspect(receipt,protocol):
    if (protocol.get("schema")!=SCHEMA
        or protocol.get("endpoint")!=URL or protocol.get("topic")!=TOPIC
        or protocol["quote_notional_usdt"]!="500"
        or protocol["safety"]["orders"]!=0):
        raise ValueError("untrusted_locked_orderbook_cost_protocol")
    if (receipt.get("schema")!="nexus.mr40.bybit_public_spot_ob50_snapshot_capture.results.v1"
        or receipt.get("endpoint")!=URL or receipt.get("topic")!=TOPIC
        or receipt.get("connected") is not True
        or receipt.get("subscription_ack") is not True
        or receipt.get("snapshot_received") is not True
        or receipt.get("orders_sent")!=0 or receipt.get("paper_modified") is not False
        or receipt.get("private_api_used") is not False):
        raise ValueError("untrusted_market_only_transport")
    raw=receipt.get("raw_snapshot_text")
    if not isinstance(raw,str) or len(raw)>200000:
        raise ValueError("missing_raw_book_snapshot")
    msg=json.loads(raw)
    if (msg.get("topic")!=TOPIC or msg.get("type")!="snapshot"
        or type(msg.get("ts")) is not int
        or not isinstance(msg.get("data"),dict)
        or msg["data"].get("s")!="BTCUSDT"
        or type(msg["data"].get("u")) is not int
        or type(msg["data"].get("seq")) is not int):
        raise ValueError("not_original_spot_book_snapshot")
    receipt_time=datetime.fromisoformat(receipt["source_received_utc"].replace("Z","+00:00"))
    if receipt_time.tzinfo is None or receipt_time.utcoffset()!=timezone.utc.utcoffset(receipt_time):
        raise ValueError("not_UTC_book_source_receipt")
    recv_ms=int(receipt_time.timestamp()*1000)
    if msg["ts"]>recv_ms or recv_ms-msg["ts"]>30000:
        raise ValueError("stale_or_future_timestamp_market_book")
    bids=validate_side(msg["data"]["b"],"bid")
    asks=validate_side(msg["data"]["a"],"ask")
    best_bid=bids[0][0];best_ask=asks[0][0]
    if best_bid>=best_ask:raise ValueError("crossed_or_locked_spot_orderbook")
    with localcontext() as ctx:
        ctx.prec=42
        mid=(best_bid+best_ask)/2
        spread_bps=(best_ask-best_bid)/mid*BPS
        obtained_btc,ask_levels=buy_quote(asks,QUOTE)
        proceeds,bid_levels=sell_base(bids,obtained_btc)
        total_cost=QUOTE-proceeds
        if total_cost<=0:raise ValueError("unexpected_book_arb_or_negative_spread_cost")
        implied_cost_bps=total_cost/QUOTE*BPS
        return {
            "source_capture_receipt_utc":receipt["source_received_utc"],
            "source_server_generated_ms":msg["ts"],
            "market_feed_lag_ms":recv_ms-msg["ts"],
            "source_update_id":msg["data"]["u"],
            "source_cross_sequence":msg["data"]["seq"],
            "levels_bid":len(bids),"levels_ask":len(asks),
            "best_bid_usdt_per_btc":str(best_bid),
            "best_ask_usdt_per_btc":str(best_ask),
            "top_spread_usdt_per_btc":str(best_ask-best_bid),
            "top_spread_bps":str(spread_bps),
            "mid_usdt_per_btc":str(mid),
            "fixed_quote_usdt":"500",
            "hypothetical_instant_ask_buy_base_BTC":str(obtained_btc),
            "hypothetical_bid_sell_proceeds_usdt":str(proceeds),
            "hypothetical_roundtrip_visible_book_friction_usdt":str(total_cost),
            "hypothetical_roundtrip_visible_book_friction_bps":str(implied_cost_bps),
            "ask_levels_needed":ask_levels,"bid_levels_needed":bid_levels,
            "transaction_fees_included":False,
            "RPI_hidden_order_flow_included":False,
            "real_fill_proven":False,
            "not_4h_mr40_signal_event":True,
        }


def run(protocol,raw_capture,output):
    if output.exists():raise ValueError("refuse_overwrite")
    p=json.loads(protocol.read_bytes());body=raw_capture.read_bytes();r=json.loads(body)
    estimates=inspect(r,p)
    doc={
        "schema":"nexus.mr40.bybit_spot_l50_spread_cost_snapshot.results.v1",
        "protocol_sha256":hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "raw_capture_sha256":hashlib.sha256(body).hexdigest(),
        "sample_count":1,
        "classification":"ONE_PUBLIC_SPOT_ORDERBOOK_SNAPSHOT_VISIBLE_LIQUIDITY_PROXY",
        "source_economic_estimates":estimates,
        "cannot_prove_fill_or_daily_average":True,
        "bybit_live_REST_still_unverified":True,
        "MR40_historical_gap_repaired":False,
        "no_MR40_strategy_deployment":True,
        "paper_changed":False,"orders":0,"private_API":False,"live":False,"promote":False
    }
    doc["digest"]=hashlib.sha256(canon(doc)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(doc,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"digest":doc["digest"],"estimates":estimates},ensure_ascii=False))


if __name__=="__main__":
    a=argparse.ArgumentParser()
    for k in ("protocol","raw_capture","output"):a.add_argument("--"+k,type=Path,required=True)
    o=a.parse_args();run(o.protocol,o.raw_capture,o.output)
