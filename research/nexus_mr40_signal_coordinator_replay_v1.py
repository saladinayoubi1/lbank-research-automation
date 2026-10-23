"""NO-MONEY closed-MR40-signal -> coordinator EVENT REPLAY.

This adapter has no broker/exchange client, no paper writes, no order payload,
no portfolio accounting, and no real fill simulator. Prior account ledger is
read ONLY as a post-hoc comparator after the synthetic event sequence exists.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from decimal import Decimal as D
from pathlib import Path
from research.nexus_mr40_independent_closed_signal_v1 import (
    ClosedMR40, frozen_rows, oracle_ledger, canon, digest_file, ms)
from research.nexus_mr40_entry_event_contract_v1 import EntryEventCoordinator, Position

EXPECTED_ROWS="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
EXPECTED_LEDGER="2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e"


def no_money_replay(rows):
    """Return only open-bar indices for scheduled markers, NEVER fills."""
    signals=ClosedMR40()
    events=EntryEventCoordinator(arm2_gross_entry_stop=False)
    held=None
    open_entries=[]
    open_exits=[]
    all_open_kinds={}
    for row in rows:
        i=len(signals.rows)
        bar_ms,op,hi,lo,cl,_=row
        if i and bar_ms-rows[i-1][0]!=14400000:
            raise ValueError("missing_4h_bar_earlier_than_signal")
        e=events.open(i,D(str(op)),position=held,source_ok=True)
        if e.executable:raise ValueError("executable_event_is_forbidden")
        all_open_kinds[e.kind]=all_open_kinds.get(e.kind,0)+1
        if e.kind=="ENTRY_NEXT_OPEN":
            if held is not None:raise ValueError("repeated_entry_event")
            open_entries.append(i)
            # Dummy unit, solely a clock ACK. Not an execution/fill.
            held=Position(D(str(op)),D(1))
        elif e.kind=="NATURAL_EXIT_NEXT_OPEN":
            if held is None:raise ValueError("orphan_natural_exit")
            open_exits.append(i)
            held=None
        elif e.kind not in ("HOLD","FLAT"):
            raise ValueError("unexpected_open_marker_"+e.kind)

        # This signal is constructed exclusively AFTER the current candle
        # is completely closed. The current open never sees it.
        signal=signals.feed(row,confirmed=True,source_verified=True)
        close_event=events.close(
            i,D(str(cl)),entry_signal=signal.final_target,
            exit_signal=signal.natural_exit_close,
            position=held,high_price=D(str(hi)),low_price=D(str(lo)),
            confirmed=True,source_ok=True,quality_allowed=True)
        if close_event.kind!="CLOSE_CONFIRMED" or close_event.executable:
            raise ValueError("failed_confirmed_close_event")
    return {"entry_bars":open_entries,"exit_bars":open_exits,
            "open_kinds":all_open_kinds,
            "closed_source_bars":len(rows),
            "end_dummy_unit_held":held is not None}


def main(inputs,ledger,protocol,output):
    if output.exists():raise ValueError("refuse_overwrite")
    p=json.loads(protocol.read_bytes())
    if (p["schema"]!="nexus.mr40.closed-signal-to-event-replay.v1"
        or p["source"]["market_digest"]!=EXPECTED_ROWS
        or p["source"]["ledger_sha"]!=EXPECTED_LEDGER
        or p["safety"]["orders"]!=0 or p["safety"]["promote"] is not False):
        raise ValueError("protocol_drift")
    rows=frozen_rows(inputs)
    result=no_money_replay(rows)
    # Post-run ledger oracle ONLY; never influences signals/clock.
    prior=oracle_ledger(ledger)
    compared=[]
    for window,start,end in (("train",ms("2023-01-01"),ms("2025-01-01")),
                             ("evaluation",ms("2025-01-01"),ms("2026-10-20"))):
        actual_entries=[i for i in result["entry_bars"] if start<=rows[i][0]<end]
        actual_exits=[i for i in result["exit_bars"] if start<=rows[i][0]<end]
        frozen=prior[window]["positions"]
        expected_entries=[x["entry"]["bar_index"] for x in frozen]
        expected_exits=[x["exit"]["bar_index"] for x in frozen]
        if actual_entries!=expected_entries or actual_exits!=expected_exits:
            raise ValueError("nonmatching_independent_pipeline_"+window+":"+
                             repr({"entries":actual_entries,"expected_entries":expected_entries,
                                   "exits":actual_exits,"expected_exits":expected_exits}))
        compared.append({"window":window,
                         "first_entry_next_open_events":len(actual_entries),
                         "natural_exit_next_open_events":len(actual_exits),
                         "entry_indices_identical":True,
                         "exit_indices_identical":True})
    if sum(z["first_entry_next_open_events"] for z in compared)!=47 or sum(z["natural_exit_next_open_events"] for z in compared)!=47:
        raise ValueError("expected_47_47_not_matched")
    doc={"schema":"nexus.mr40.closed-signal-to-event-replay.results.v1",
         "market_rows_sha256":EXPECTED_ROWS,"prior_ledger_sha256":EXPECTED_LEDGER,
         "protocol_sha256":digest_file(protocol),
         "total_closed_source_bars":result["closed_source_bars"],
         "event_kinds":result["open_kinds"],
         "matches":compared,
         "no_ledger_driven_decisions":True,"events_executable":False,
         "orders_generated":0,"paper_changed":False,
         "real_fills_simulated":False,"no_money_unit_ack_only":True,
         "histories_previously_seen":True,
         "source_4h_1m_parity_not_proven":True,
         "bybit_current_api_403_unresolved":True,
         "promote":False,"merge":False}
    doc["digest"]=hashlib.sha256(canon(doc)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(doc,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"digest":doc["digest"],"matches":compared,
                      "event_kinds":result["open_kinds"]},ensure_ascii=False))


if __name__=="__main__":
    a=argparse.ArgumentParser()
    for key in ("inputs","ledger","protocol","output"):
        a.add_argument("--"+key,required=True,type=Path)
    main(**vars(a.parse_args()))
