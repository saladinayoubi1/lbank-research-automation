"""V82 read-only causal parent/child pivot witness, NOT recursive Elliott proof.

Independent historical Binance Spot 1m source -> 3m child / 15m parent.
Every detected primitive is retained; no pivot subset optimization.
No signal, orders, strategy promotion, or V52 changes.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

RESEARCH_ONLY = True
ENTRY_SIGNAL = False
PAPER_ELIGIBLE = False
LIVE_ENABLED = False
FROZEN_V52_CHANGED = False
MINUTE_MS = 60_000
MINUTE_WIDTH = 3
CHILD_SPAN = 3
CHILD_WIDTH = 1
PARENT_SPAN = 15
PARENT_WIDTH = 3
BASE = Path(r"E:\NEXUS-QA\elliott-v80-binance-source-20261016")
ROOT = Path(r"E:\NEXUS-QA\elliott-v82-causal-degree-observer-20261016")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def numeric(raw: object) -> Decimal:
    if type(raw) is bool or isinstance(raw, float):
        raise ValueError("lossy/boolean source values rejected")
    try:
        val = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid price") from exc
    if not val.is_finite() or val <= 0:
        raise ValueError("nonpositive/nonfinite price")
    return val


@dataclass(frozen=True)
class Minute:
    ms: int
    high: Decimal
    low: Decimal


@dataclass(frozen=True)
class Witness:
    kind: str
    center_ms: int
    source_minute_index: int
    confirmed_ms: int
    price: str
    degree: str


def validate_minutes(minutes: list[Minute]) -> None:
    if not isinstance(minutes, list) or not minutes:
        raise ValueError("nonempty complete minute source required")
    for i, m in enumerate(minutes):
        if type(m) is not Minute or type(m.ms) is not int:
            raise ValueError("typed minute source required")
        if m.ms % MINUTE_MS or m.ms != minutes[0].ms + i * MINUTE_MS:
            raise ValueError("minute gap, duplicate, or misaligned timestamp")
        if (type(m.high) is not Decimal or type(m.low) is not Decimal or
                not m.high.is_finite() or not m.low.is_finite() or
                m.low <= 0 or m.high < m.low):
            raise ValueError("invalid 1m high/low")


def completed_prefix(all_minutes: list[Minute], decision_ms: int) -> list[Minute]:
    if type(decision_ms) is not int or decision_ms % (15 * MINUTE_MS):
        raise ValueError("decision as-of requires a UTC 15m close")
    prefix = [x for x in all_minutes if x.ms + MINUTE_MS <= decision_ms]
    validate_minutes(prefix)
    if prefix[0].ms + len(prefix) * MINUTE_MS != decision_ms:
        raise ValueError("decision outside a gapless complete source prefix")
    if len(prefix) % PARENT_SPAN:
        raise ValueError("incomplete 15m parent")
    return prefix


def coarse_candles(minutes: list[Minute], span: int):
    if len(minutes) % span:
        raise ValueError("partial parent/child bar")
    return [
        (minutes[i].ms,
         max(x.high for x in minutes[i:i+span]),
         min(x.low for x in minutes[i:i+span]))
        for i in range(0, len(minutes), span)
    ]


def primitive(minutes: list[Minute], span: int, width: int, degree: str):
    """Strict extrema, unique matching raw 1m center, right confirmed at BOTH degrees.

    Intentionally NO same-kind compression, re-ranking, or retrospective trimming.
    """
    bars = coarse_candles(minutes, span)
    out: list[Witness] = []
    reasons: Counter[str] = Counter()
    for i in range(width, len(bars) - width):
        neighbors = [j for j in range(i-width, i+width+1) if j != i]
        hi = all(bars[i][1] > bars[j][1] for j in neighbors)
        lo = all(bars[i][2] < bars[j][2] for j in neighbors)
        if hi == lo:
            if hi:
                reasons["DOUBLE_EXTREMUM_REJECTED"] += 1
            continue
        kind, price = ("high",bars[i][1]) if hi else ("low",bars[i][2])
        centers = [j for j in range(i*span,(i+1)*span)
                   if (minutes[j].high if hi else minutes[j].low) == price]
        if len(centers) != 1:
            reasons["NONUNIQUE_PHYSICAL_CENTER"] += 1
            continue
        center = centers[0]
        if center < MINUTE_WIDTH or center + MINUTE_WIDTH >= len(minutes):
            reasons["INCOMPLETE_PHYSICAL_RIGHT_CONFIRMATION"] += 1
            continue
        neighborhood = [j for j in range(center-MINUTE_WIDTH,center+MINUTE_WIDTH+1)
                        if j != center]
        exact = (all(price > minutes[j].high for j in neighborhood) if hi
                 else all(price < minutes[j].low for j in neighborhood))
        if not exact:
            reasons["NOT_STRICT_1M_PIVOT"] += 1
            continue
        coarse_confirmation = bars[i + width][0] + span * MINUTE_MS
        physical_confirmation = minutes[center + MINUTE_WIDTH].ms + MINUTE_MS
        out.append(Witness(kind,minutes[center].ms,center,
                           max(coarse_confirmation,physical_confirmation),str(price),degree))
    return out, dict(reasons)


def classify_leg(left: Witness, right: Witness, children: list[Witness]) -> dict:
    """Hypotheses are only skeleton labels, NEVER Elliott-pattern certificates."""
    asof = max(left.confirmed_ms, right.confirmed_ms)
    middle = [c for c in children
              if left.center_ms < c.center_ms < right.center_ms
              and c.confirmed_ms <= asof]
    kinds = [left.kind] + [c.kind for c in middle] + [right.kind]
    alternating = all(a != b for a,b in zip(kinds,kinds[1:]))
    hypotheses = {
        "MOTIVE_FIVE_LEG_SKELETON": len(middle) == 4 and alternating,
        "CORRECTION_THREE_LEG_SKELETON": len(middle) == 2 and alternating,
    }
    if left.kind == right.kind:
        reason = "PARENT_SAME_KIND_NOT_A_DIRECTED_LEG"
    elif not alternating:
        reason = "NONALTERNATING_ALL_PRIMITIVES_PRESERVED"
    elif len(middle) not in (2,4):
        reason = "CHILD_COUNT_NOT_THREE_OR_FIVE_LEGS"
    else:
        reason = "SKELETON_ONLY_SUBWAVE_GEOMETRY_UNPROVEN"
    return {
        "parent_left_center_ms":left.center_ms,
        "parent_right_center_ms":right.center_ms,
        "hypothesis_first_seen_ms":asof,
        "children_observable_by_then":len(middle),
        "all_child_centers_ms":[c.center_ms for c in middle],
        "all_child_confirmation_ms":[c.confirmed_ms for c in middle],
        "hypotheses":hypotheses,
        "reason":reason,
        "complete_recursive_elliott":False,
        "entry_signal":False,
        "paper_eligible":False,
    }


def observe(all_minutes: list[Minute], decision_ms: int) -> dict:
    minutes=completed_prefix(all_minutes,decision_ms)
    child,child_rejected=primitive(minutes,CHILD_SPAN,CHILD_WIDTH,"3m/1m")
    parent,parent_rejected=primitive(minutes,PARENT_SPAN,PARENT_WIDTH,"15m/1m")
    child=[c for c in child if c.confirmed_ms <= decision_ms]
    parent=[p for p in parent if p.confirmed_ms <= decision_ms]
    legs=[classify_leg(a,b,child) for a,b in zip(parent,parent[1:])]
    summary=Counter()
    for leg in legs:
        summary[leg["reason"]]+=1
        for name,accepted in leg["hypotheses"].items():
            if accepted:
                summary[name]+=1
    return {
        "schema":"nexus.elliott-v82-readonly-causal-degree-observer.v1",
        "asof_ms":decision_ms,
        "minute_bars":len(minutes),
        "parent_15m_1m_witness_count":len(parent),
        "child_3m_1m_witness_count":len(child),
        "parent_witnesses":[asdict(p) for p in parent],
        "child_witnesses":[asdict(p) for p in child],
        "raw_rejection_counts":{"parent":parent_rejected,"child":child_rejected},
        "leg_assessments":legs,
        "leg_summary":dict(summary),
        "immutable_frozen_v52":True,
        "historical_exploratory":True,
        "source_bound_1m_price_centers":True,
        "fully_recursive_elliott":False,
        "entry_signal":False,
        "paper_eligible":False,
        "live_enabled":False,
        "net_pnl":None,
    }


def load_attested_symbol(symbol: str, receipt: dict) -> list[Minute]:
    if symbol not in ("BTCUSDT","ETHUSDT"):
        raise ValueError("symbol outside declared research scope")
    entries=[x for x in receipt["files"] if x["name"].startswith(symbol+"-1m-")]
    if len(entries) != 2:
        raise ValueError("exactly two attested days required")
    points=[]
    for e in sorted(entries,key=lambda x:x["name"]):
        if e.get("verified") is not True:
            raise ValueError("unverified prior checksum")
        stem=e["name"]
        zbytes=(BASE/stem).read_bytes()
        if digest(zbytes)!=e["sha256"] or digest(zbytes)!=e["official_checksum_sha256"]:
            raise ValueError("raw source diverges from attested official checksum")
        with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
            if z.namelist()!=[stem[:-4]+".csv"]:
                raise ValueError("unexpected archive member")
            csvbytes=z.read(z.namelist()[0])
        if digest(csvbytes)!=e["csv_member_sha256"]:
            raise ValueError("member SHA mismatch")
        rows=list(csv.reader(io.StringIO(csvbytes.decode("utf-8-sig"))))
        if len(rows)!=1440:
            raise ValueError("incorrect day bar count")
        for row in rows:
            if len(row)!=12:
                raise ValueError("invalid Binance CSV schema")
            t=int(row[0])
            op,hi,lo,cl=[numeric(s) for s in row[1:5]]
            if not lo<=min(op,cl)<=max(op,cl)<=hi or int(row[6])!=t+59999:
                raise ValueError("invalid raw OHLC / close time")
            points.append(Minute(t,hi,lo))
    validate_minutes(points)
    return points


def main():
    receipt_bytes=(BASE/"V80_OFFICIAL_BINANCE_SOURCE_QA.json").read_bytes()
    receipt=json.loads(receipt_bytes)
    if receipt.get("stage")!="V80" or receipt.get("live_trading") is not False:
        raise ValueError("unexpected source receipt")
    ROOT.mkdir(parents=True,exist_ok=True)
    result={"schema":"nexus.elliott-v82-source-bound-competing-skeletons.v1",
            "generated_utc":datetime.now(timezone.utc).isoformat(),
            "source_stage":"V80","source_receipt_sha256":digest(receipt_bytes),
            "research_only":True,"live_enabled":False,"paper_eligible":False,
            "prospective_holdout":False,"changed_v52":False,"new_pnl":None,"symbols":{}}
    for symbol in ("BTCUSDT","ETHUSDT"):
        minutes=load_attested_symbol(symbol,receipt)
        day1=observe(minutes,minutes[0].ms+1440*MINUTE_MS)
        day2=observe(minutes,minutes[0].ms+2880*MINUTE_MS)
        individual=ROOT/f"V82_{symbol}_CAUSAL_WITNESSES.json"
        data=json.dumps({"day1":day1,"day2":day2},indent=2,sort_keys=True)+"\n"
        individual.write_text(data,encoding="utf-8")
        result["symbols"][symbol]={
            "day1_parent":day1["parent_15m_1m_witness_count"],
            "day1_child":day1["child_3m_1m_witness_count"],
            "day2_parent":day2["parent_15m_1m_witness_count"],
            "day2_child":day2["child_3m_1m_witness_count"],
            "day2_legs":len(day2["leg_assessments"]),
            "day2_summary":day2["leg_summary"],
            "detailed_witness_file_sha256":digest(individual.read_bytes()),
        }
    target=ROOT/"V82_RESULT.json"
    target.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"stage":"V82","result":result["symbols"],
                      "result_sha256":digest(target.read_bytes()),
                      "result_path":str(target)},indent=2))


if __name__ == "__main__":
    main()
