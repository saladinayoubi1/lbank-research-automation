"""Independent MR40 first-closed-bar signal oracle, NO EXCHANGE OR ORDERS.

Never imports prior MR40 engines and never reads historical ledger in the signal
algorithm. Comparator against SHA-pinned historical ledger is separate.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime,timezone
from decimal import Decimal as D, localcontext
from pathlib import Path

ROWS_SHA="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
LEDGER_SHA="2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e"
STEP=14400000
TRAIN_START="2023-01-01"
EVAL_START="2025-01-01"
END="2026-10-20"
TWO=D(2)
FORTY=D(40)


def canon(v):
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()

def digest_file(p):
    h=hashlib.sha256()
    with p.open("rb") as inp:
        for blk in iter(lambda:inp.read(1<<20),b""):h.update(blk)
    return h.hexdigest()

def ms(date):
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp()*1000)


@dataclass(frozen=True)
class Signal:
    bar_index: int
    start_ms: int
    z_score: str|None
    raw_active: bool
    episode_admitted: bool
    final_target: bool
    first_entry_close: bool
    natural_exit_close: bool
    signal_ready: bool
    @property
    def executable(self):
        return False


class ClosedMR40:
    """Single-pass, future-blind MR40/Momentum30 state machine.

    Only closes are used by the indicator; OHLCV is validated strictly
    as evidence of a confirmed, contiguous, nonnegative-volume 4h bar.
    A validation failure latches suspension; recover with fresh verified
    181+ closed-bar bootstrap, not with a delayed entry.
    """
    def __init__(self):
        self.rows=[]
        self.close=[]
        self.raw_active=False
        self.float_raw_active=False
        self.episode_admitted=False
        self.final_target=False
        self.suspended=False

    def feed(self,row,*,confirmed=False,source_verified=False):
        if self.suspended:raise ValueError("source_suspended_rebootstrap_required")
        try:
            if not confirmed or not source_verified:
                raise ValueError("unconfirmed_or_unverified_source")
            if not isinstance(row,(tuple,list)) or len(row)!=6:
                raise ValueError("expected_6_field_ohlcv")
            ts=row[0]
            if type(ts) is not int or ts<0 or ts%STEP:
                raise ValueError("invalid_utc_4h_bar_time")
            if self.rows and ts-self.rows[-1][0]!=STEP:
                raise ValueError("missing_or_nonmonotonic_4h_candle")
            numbers=[D(str(x)) for x in row[1:]]
            if not all(n.is_finite() for n in numbers):
                raise ValueError("nonfinite_price_volume")
            op,hi,lo,cl,volume=numbers
            if min(op,hi,lo,cl)<=0 or volume<0 or hi<max(op,cl) or lo>min(op,cl):
                raise ValueError("invalid_4h_ohlcv_envelope")
            j=len(self.rows)
            raw=self.raw_active
            fraw=self.float_raw_active
            z=None
            if j>=40:
                past=self.close[-40:]
                with localcontext() as context:
                    context.prec=40
                    mean=sum(past,D(0))/FORTY
                    var=sum(((v-mean)**2 for v in past),D(0))/FORTY
                    if var>0:
                        zvalue=(cl-mean)/var.sqrt()
                        z=str(zvalue)
                        if zvalue<=-TWO:raw=True
                        elif zvalue>=0:raw=False
                fprev=[float(x) for x in past]
                fstd=statistics.pstdev(fprev)
                if fstd>0:
                    fz=(float(cl)-math.fsum(fprev)/40)/fstd
                    if fz<=-2:fraw=True
                    elif fz>=0:fraw=False
                if raw!=fraw:
                    raise ValueError("float_decimal_threshold_or_raw_signal_disagreement")
            new_episode=(raw and not self.raw_active)
            # No change of episode admission until the raw MR40 episode finishes.
            admitted=(j>=180 and cl>=self.close[j-180]) if new_episode else (
                self.episode_admitted if raw else False
            )
            target=bool(raw and admitted)
            prior_target=self.final_target
            signal=Signal(j,ts,z,bool(raw),bool(admitted),target,
                          bool(target and not prior_target),
                          bool(prior_target and not target),
                          bool(j>=180))
            # Advance state only after validated successful closed bar.
            self.rows.append((ts,*[str(v) for v in numbers]))
            self.close.append(cl)
            self.raw_active=bool(raw)
            self.float_raw_active=bool(fraw)
            self.episode_admitted=bool(admitted)
            self.final_target=target
            return signal
        except (TypeError,ValueError,ArithmeticError,OverflowError):
            self.suspended=True
            raise


def frozen_rows(folder):
    b=json.loads((folder/"bybit_prepared_inputs.json").read_bytes())["rows"]
    e=json.loads((folder/"bybit_october_input_extension.json").read_bytes())["rows"]
    rows=b+e
    if hashlib.sha256(canon(rows)).hexdigest()!=ROWS_SHA:
        raise ValueError("market_rows_sha_drift")
    return rows


def oracle_ledger(path):
    if digest_file(path)!=LEDGER_SHA:
        raise ValueError("prior_ledger_sha_drift")
    result={}
    with gzip.open(path,"rt",encoding="utf8") as src:
        for line in src:
            obj=json.loads(line);k=obj["key"]
            if (k["venue"],k["capital"],k["profile"],k["case"])!=("Bybit",10000,"normal","baseline"):
                continue
            if k["window"] not in ("train","evaluation"):continue
            if k["window"] in result:raise ValueError("duplicate_frozen_window")
            result[k["window"]]=obj
    if set(result)!={"train","evaluation"}:raise ValueError("missing_frozen_window")
    return result


def audit(rows,prior,protocol,outpath):
    if outpath.exists():raise ValueError("refuse_overwrite")
    p=json.loads(protocol.read_bytes())
    if (p["schema"]!="nexus.mr40.independent_closed_signal_parity.v1"
        or p["source"]["rows_digest"]!=ROWS_SHA
        or p["source"]["ledger_file_sha256"]!=LEDGER_SHA
        or p["safety"]["promote"] is not False):
        raise ValueError("pinned_protocol_invalid")
    engine=ClosedMR40()
    # ABSOLUTELY no prior ledger passed to this generator.
    emitted=[engine.feed(r,confirmed=True,source_verified=True) for r in rows]
    if len(emitted)!=len(rows) or engine.suspended:
        raise ValueError("emission_incomplete")
    results=[]
    for window,start,end in (("train",TRAIN_START,EVAL_START),("evaluation",EVAL_START,END)):
        a=ms(start);b=ms(end)
        emitted_entries=[x.bar_index for x in emitted if a<=x.start_ms<b and x.first_entry_close]
        emitted_exits=[x.bar_index for x in emitted if a<=x.start_ms<b and x.natural_exit_close]
        frozen=prior[window]["positions"]
        positions=[(t["entry"]["signal_index"],t["exit"]["signal_index"]) for t in frozen]
        ledger_entry=[v[0] for v in positions]
        ledger_exit=[v[1] for v in positions]
        if not (len(ledger_entry)==len(set(ledger_entry)) and len(ledger_exit)==len(set(ledger_exit))):
            raise ValueError("frozen_duplicate_signal_indices")
        if len(ledger_entry)!=p["source"]["expected_frozen_entry_count"][window] or len(ledger_exit)!=p["source"]["expected_frozen_exit_count"][window]:
            raise ValueError("prior_signal_count_drift")
        if emitted_entries!=ledger_entry or emitted_exits!=ledger_exit:
            raise ValueError("independent_closed_signal_94_temporal_points_not_equal:"+window
                             +":"+repr({"computed_entries":emitted_entries,"frozen_entries":ledger_entry,
                                        "computed_exits":emitted_exits,"frozen_exits":ledger_exit}))
        for ent,ex,pos in zip(emitted_entries,emitted_exits,frozen):
            if not (ent<ex and ent+1<len(rows) and ex+1<len(rows)
                    and rows[ent+1][0]==pos["entry"]["fill_ms"]
                    and rows[ex+1][0]==pos["exit"]["fill_ms"]):
                raise ValueError("impossible_next_open_or_paired_entry_exit")
        results.append({
            "window":window,"first_entries_from_closed_prices":len(emitted_entries),
            "natural_exits_from_closed_prices":len(emitted_exits),
            "same_as_frozen_ledger":True,
            "exact_signal_indices_sha256":hashlib.sha256(canon(positions)).hexdigest(),
            "frozen_ledger_consulted_only_after_generation":True,
            "signals_not_derived_from_ledger":True,
        })
    report={"schema":"nexus.mr40.independent_closed_signal_parity.results.v1",
            "source_rows_sha256":ROWS_SHA,"source_ledger_sha256":LEDGER_SHA,
            "protocol_sha256":digest_file(protocol),
            "total_market_rows":len(rows),
            "independent_closed_bar_entries":sum(x["first_entries_from_closed_prices"] for x in results),
            "independent_closed_bar_natural_exits":sum(x["natural_exits_from_closed_prices"] for x in results),
            "exact_independent_temporal_parity":True,
            "rows":[*results],"histories_seen":True,
            "bybit_public_reconnect_proven":False,
            "paper_changed":False,"orders":0,"private_api":False,"live":False,
            "promote":False,"merge":False,
            "is_fill_or_equity_parity":False}
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    outpath.parent.mkdir(parents=True,exist_ok=True)
    outpath.write_text(json.dumps(report,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"digest":report["digest"],"entries":report["independent_closed_bar_entries"],
                      "exits":report["independent_closed_bar_natural_exits"],"windows":results},ensure_ascii=False))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("inputs","ledger","protocol","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    arg=parser.parse_args()
    # Source ledger is loaded strictly as comparator, after market data is pinned.
    audit(frozen_rows(arg.inputs),oracle_ledger(arg.ledger),arg.protocol,arg.output)
