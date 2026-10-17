"""V102 Bybit V5 Spot PUBLIC 1m future intake contract -- OFFLINE ONLY.

As of V102 preregistration, no future source fetched. Never creates
credentials, network clients, orders, candidate scores, or P/L.
Raw response bytes and source provenance preserved; API responses are not
cryptographically signed by Bybit, so authenticity is conditional on
trusted collection/transport and independent audit, not SHA alone.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from research.elliott_v99_causal_scale import scale_v99 as v99
from research.elliott_v101_preregistered_grammar import grammar_v101 as v101

SCHEMA="nexus.elliott-v102-bybit-v5-public-spot-one-minute-future-intake.v1"
URL="https://api.bybit.com/v5/market/kline"
DOCS_URL="https://bybit-exchange.github.io/docs/v5/market/kline"
CATEGORY="spot"
INTERVAL="1"
MAX_PAGE_CANDLES=1000
MAX_RAW_PAGE_BYTES=400000
NO_NETWORK_FETCH=True
RESEARCH_ONLY=True
LIVE_ENABLED=False
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
ORDER_ADAPTER=None
V52_UNCHANGED=True
ELLIOTT_CERTIFICATES=0
PREREG_V101_SHA="735d942cdcbf802f6079e5435473e91b7d5b597831087ab4a7439ab04984e221"


@dataclass(frozen=True)
class Page:
    symbol:str
    index:int
    start_ms:int
    last_start_ms:int
    count:int


@dataclass(frozen=True)
class Candle:
    ms:int
    open:Decimal
    high:Decimal
    low:Decimal
    close:Decimal
    volume:Decimal
    turnover:Decimal


def _epoch(iso:str)->int:
    date=datetime.fromisoformat(iso.replace("Z","+00:00"))
    return int(date.timestamp()*1000)


def locked_range()->tuple[int,int]:
    if v101.prereg_sha()!=PREREG_V101_SHA:
        raise ValueError("immutable V101 prereg rulebook SHA has changed")
    start=_epoch(v101.WINDOW_START_UTC)
    end=_epoch(v101.WINDOW_END_EXCLUSIVE_UTC)
    if (end-start!=v101.COMPLETE_SOURCE_ROWS_PER_PAIR*v99.MINUTE
        or start%v99.MINUTE or end%v99.MINUTE):
        raise ValueError("future intake period differs from sealed V101")
    return start,end


def pages(symbol:str)->list[Page]:
    if symbol not in v101.PAIRS:
        raise ValueError("symbol not in frozen Bybit Spot universe")
    start,end=locked_range()
    result=[]
    for index,offset in enumerate(range(0,v101.COMPLETE_SOURCE_ROWS_PER_PAIR,
                                        MAX_PAGE_CANDLES)):
        count=min(MAX_PAGE_CANDLES,
                  v101.COMPLETE_SOURCE_ROWS_PER_PAIR-offset)
        first=start+offset*v99.MINUTE
        last=first+(count-1)*v99.MINUTE
        if last>=end:
            raise ValueError("out-of-window page")
        result.append(Page(symbol,index,first,last,count))
    if len(result)!=21 or sum(x.count for x in result)!=20160:
        raise ValueError("incomplete planned future pages")
    return result


def request_params(page:Page)->dict:
    if type(page) is not Page or page not in pages(page.symbol):
        raise ValueError("request must be exactly frozen future-page descriptor")
    return {"category":CATEGORY,"symbol":page.symbol,"interval":INTERVAL,
            "start":page.start_ms,"end":page.last_start_ms,
            "limit":page.count}


def plan()->dict:
    all_pages={symbol:[{
        "page":p.index,"expected_rows":p.count,
        "params":request_params(p),
    } for p in pages(symbol)] for symbol in v101.PAIRS}
    return {
        "schema":SCHEMA,
        "status":"PLANNED_ONLY_DATA_NOT_FETCHED",
        "api":"Bybit V5 public Get Kline",
        "api_method":"GET","api_host":"api.bybit.com",
        "api_path":"/v5/market/kline",
        "official_docs":DOCS_URL,
        "v101_rulebook_sha256":PREREG_V101_SHA,
        "start_ms":locked_range()[0],"end_exclusive_ms":locked_range()[1],
        "source_window_inclusive_start_exclusive_end":True,
        "symbols":all_pages,
        "total_pages":sum(map(len,all_pages.values())),
        "expected_total_1m_candles":20160*len(v101.PAIRS),
        "max_public_page_limit":MAX_PAGE_CANDLES,
        "public_only_no_api_keys":True,
        "raw_http_response_hash_required":True,
        "api_responses_not_cryptographically_signed":True,
        "collection_requires_independent_provenance_and_audit":True,
        "reverse_sorted_1m_pages_expected":True,
        "all_minutes_closed_before_acceptance":True,
        "no_network_in_v102":True,
        "no_market_data_opened":True,
        "source_authenticity_certified":False,
        "future_candidate_evaluation_performed":False,
        "v52_unchanged":True,
        "entry_signal":False,"paper_eligible":False,"live_enabled":False,
        "orders":0,"net_pnl":None,
    }


def plan_bytes()->bytes:
    return (json.dumps(plan(),sort_keys=True,indent=2)+"\n").encode()


def sha(raw:bytes)->str:
    return hashlib.sha256(raw).hexdigest()


def _unique_object(pairs:list[tuple[str,object]])->dict:
    obj={}
    for k,v in pairs:
        if k in obj:
            raise ValueError("duplicate JSON response key")
        obj[k]=v
    return obj


def _decimal(value:object)->Decimal:
    if type(value) is not str or not value:
        raise ValueError("Bybit candle value must be a finite decimal string")
    try:
        n=Decimal(value)
    except (InvalidOperation,ValueError) as e:
        raise ValueError("invalid Bybit numeric string") from e
    if not n.is_finite():
        raise ValueError("nonfinite Bybit numeric value")
    return n


def parse_page(raw:bytes,page:Page,received_utc_ms:int)->tuple[list[Candle],dict]:
    """Strict offline validation of one exact, reverse-chronological V5 response.

    The caller retains original raw bytes, trust-network metadata and clock.
    This parser alone cannot prove origin, TLS or authenticity.
    """
    params=request_params(page)
    if type(raw) is not bytes or not 0<len(raw)<=MAX_RAW_PAGE_BYTES:
        raise ValueError("missing or oversized raw Bybit response")
    if (type(received_utc_ms) is not int or
        received_utc_ms<page.last_start_ms+v99.MINUTE):
        raise ValueError("future, open, or unconfirmed last candle")
    try:
        payload=json.loads(raw.decode("utf-8"),object_pairs_hook=_unique_object)
    except (UnicodeDecodeError,json.JSONDecodeError) as e:
        raise ValueError("malformed source JSON") from e
    if (type(payload) is not dict or
        type(payload.get("retCode")) is not int or
        payload["retCode"]!=0 or
        type(payload.get("retMsg")) is not str):
        raise ValueError("Bybit exchange error, not an authenticated success")
    reply=payload.get("result")
    if (type(reply) is not dict or
        reply.get("category")!=params["category"] or
        reply.get("symbol")!=params["symbol"] or
        type(reply.get("list")) is not list or
        len(reply["list"])!=page.count):
        raise ValueError("wrong category/symbol, incomplete or oversize Bybit page")
    if "time" in payload and (
        type(payload["time"]) is not int or
        payload["time"]<page.last_start_ms+v99.MINUTE):
        raise ValueError("Bybit response predates closing minute")
    observed=[]
    for ix,row in enumerate(reply["list"]):
        if type(row) is not list or len(row)!=7 or (
            type(row[0]) is not str or not row[0].isdigit()
            or str(int(row[0]))!=row[0]):
            raise ValueError("Bybit V5 requires seven typed candle strings")
        start=int(row[0])
        expected=page.last_start_ms-ix*v99.MINUTE
        if start!=expected:
            raise ValueError("out-of-order, duplicated or missing 1m source minute")
        op,hi,lo,cl,volume,turnover=map(_decimal,row[1:])
        if (lo<=0 or lo>op or op>hi or lo>cl or cl>hi
            or volume<0 or turnover<0):
            raise ValueError("invalid Bybit OHLC/volume or turnover")
        observed.append(Candle(start,op,hi,lo,cl,volume,turnover))
    ordered=list(reversed(observed))
    if len(ordered)!=page.count or (
        ordered[0].ms!=page.start_ms or
        ordered[-1].ms!=page.last_start_ms):
        raise ValueError("wrong physical page bounds")
    receipt={
        "symbol":page.symbol,"page":page.index,
        "expected_request":params,"actual_row_count":len(ordered),
        "response_raw_sha256":sha(raw),
        "server_time_ms":payload.get("time"),
        "received_utc_ms":received_utc_ms,
        "source_claim":"BYBIT_V5_PUBLIC_SPOT_KLINE",
        "response_cryptographically_signed":False,
        "independent_transport_source_authentication":False,
        "page_order_and_ohlc_verified":True,
        "had_future_unclosed_row":False,
    }
    return ordered,receipt


def accept_complete_future_archive(
    raw_pages:dict[tuple[str,int],tuple[bytes,int]],
)->dict:
    """Future gated; *no network client*; all pages required atomically.

    Acceptance is DATA INTEGRITY ONLY. No signals or strategy scoring.
    """
    if type(raw_pages) is not dict:
        raise ValueError("typed complete raw response page map required")
    start,end=locked_range()
    now=int(datetime.now(timezone.utc).timestamp()*1000)
    if now<end:
        raise ValueError("preregistered market window has not ended")
    frozen={ (p.symbol,p.index):p
             for symbol in v101.PAIRS for p in pages(symbol)}
    if set(raw_pages)!=set(frozen):
        raise ValueError("source incomplete, unexpected extra page or substituted symbol")
    summary={}
    for symbol in v101.PAIRS:
        collection=[]
        receipts=[]
        for p in pages(symbol):
            pair=raw_pages[(symbol,p.index)]
            if (type(pair) is not tuple or len(pair)!=2):
                raise ValueError("raw response bytes and receipt instant required")
            batch,receipt=parse_page(pair[0],p,pair[1])
            if pair[1]<end:
                raise ValueError("all pages must be fetched after complete future window")
            receipts.append(receipt)
            collection.extend(batch)
        if (len(collection)!=v101.COMPLETE_SOURCE_ROWS_PER_PAIR
            or collection[0].ms!=start or
            collection[-1].ms+v99.MINUTE!=end):
            raise ValueError("missing full original frozen Bybit source period")
        for i,c in enumerate(collection):
            if c.ms!=start+i*v99.MINUTE:
                raise ValueError("gap, duplicate or reordered future source")
        # Full physical 1m 7-field candle ledger digest. The source is
        # not trusted merely because the later hash is deterministic.
        rows=[[x.ms,str(x.open),str(x.high),str(x.low),str(x.close),
               str(x.volume),str(x.turnover)] for x in collection]
        canonical=json.dumps(rows,ensure_ascii=False,separators=(",",":")).encode()
        summary[symbol]={
            "physical_complete_1m_rows":len(collection),
            "physical_first_ms":start,
            "physical_last_exclusive_ms":end,
            "all_physical_7field_rows_sha256":sha(canonical),
            "all_page_receipts":receipts,
            "source_claim_authenticated_by_provider_signature":False,
            "physical_ohlc_time_integrity":True,
            "source_provenance_requires_independent_collection_audit":True,
            "pattern_analysis_executed":False,
            "trades":0,
        }
    return {
        "schema":"nexus.elliott-v102-closed-Bybit-public-future-source-receipt.v1",
        "preregistered_v101_sha256":PREREG_V101_SHA,
        "start_ms":start,"end_exclusive_ms":end,
        "all_original_pages_complete":True,
        "source_signature_verified":False,
        "no_strategy_assessment_in_data_intake":True,
        "symbols":summary,
        "elliott_certificates":0,"entry_signal":False,
        "paper_eligible":False,"live_enabled":False,
        "orders":0,"pnl":None,
    }


def freeze_plan(destination:Path)->dict:
    if not isinstance(destination,Path):
        raise ValueError("explicit future plan path required")
    raw=plan_bytes()
    if destination.exists():
        if destination.read_bytes()!=raw:
            raise ValueError("V102 plan differs from frozen original")
    else:
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(raw)
    return {"status":"BYBIT_PUBLIC_1M_FUTURE_INTAKE_PLAN_ONLY",
            "sha256":sha(raw),"planned_requests":42,
            "data_rows_fetched":0,"real_elliott_candidates_evaluated":0,
            "orders":0}


if __name__=="__main__":
    import argparse
    a=argparse.ArgumentParser()
    a.add_argument("--plan-output",type=Path,required=True)
    cfg=a.parse_args()
    print(json.dumps(freeze_plan(cfg.plan_output),indent=2))
