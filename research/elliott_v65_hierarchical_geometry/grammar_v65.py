"""V65 isolated structural grammar for seven alternating elementary moves.

Two pre-enumerated ways to express a FIVE-leg rising impulse where exactly
one bearish correction (wave 2 or wave 4) subdivides into three elementary
A-B-C legs. Enforces narrow V40 non-diagonal impulse + strict zigzag shape.
NO adaptive pivot deletion, no candle or source authentication, no trading,
no claim of recursive Elliott proof. Derived after inspected V63 data:
HISTORICAL EXPLORATION, NOT independent prospective validation.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal,InvalidOperation
from typing import Sequence
from nested_elliott_v40 import _price_geometry_5,_price_geometry_3

RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
AUTO_DEMO=False
LIVE_ENABLED=False
HYPOTHESIS_SELECTED_AFTER_HISTORICAL_INSPECTION=True
FROZEN_V52_COMPATIBLE_SCORING=False
# Expanded negative correction positions: 1-4 (wave 2) or 3-6 (wave 4).
EXPANSIONS=(("WAVE2_ABC",(0,1,4,5,6,7),(1,2,3,4)),
            ("WAVE4_ABC",(0,1,2,3,6,7),(3,4,5,6)))

@dataclass(frozen=True)
class Vertex:
    minute_index:int
    kind:str
    price:str

@dataclass(frozen=True)
class ExpansionAssessment:
    name:str
    five_leg_impulse_geometry:bool
    countertrend_abc_zigzag_geometry:bool
    accepted:bool

@dataclass(frozen=True)
class HierarchyAssessment:
    state:str
    expansions:tuple[ExpansionAssessment,...]
    valid_expansion_count:int
    source_authenticated:bool=False
    recursively_complete:bool=False
    entry_signal:bool=False
    paper_eligible:bool=False
    live_enabled:bool=False
    forward_validated:bool=False

def _price(v):
    if isinstance(v,(bool,float)):raise ValueError("floats and booleans forbidden for source prices")
    try:x=Decimal(str(v))
    except (InvalidOperation,TypeError,ValueError) as e:
        raise ValueError("malformed price") from e
    if not x.is_finite() or x<=0:raise ValueError("invalid price")
    return x

def assess_seven_moves(vertices:Sequence[Vertex])->HierarchyAssessment:
    """Read-only vertex geometry. Caller must separately prove every source pivot.

    The initial/eight-point sequence MUST include every observed alternating
    primitive swing; no trimming or selection. Both possible corrective-wave
    placements are evaluated, including negative cases. An ambiguous double
    match is rejected rather than cherry-picking the most favorable one.
    """
    if not isinstance(vertices,(tuple,list)) or len(vertices)!=8:
        raise ValueError("exactly eight verified-looking vertices required")
    expected=("low","high","low","high","low","high","low","high")
    if any(type(v) is not Vertex or v.kind!=expected[i] or
           type(v.minute_index) is not int or v.minute_index<0
           for i,v in enumerate(vertices)):
        raise ValueError("alternating low/high 1m centers required")
    if any(b.minute_index<=a.minute_index for a,b in zip(vertices,vertices[1:])):
        raise ValueError("duplicate or unordered pivot centers")
    values=tuple(_price(v.price) for v in vertices)
    if any((values[i+1]<=values[i] if i%2==0
            else values[i+1]>=values[i]) for i in range(7)):
        raise ValueError("invalid elementary swing polarity")
    assessments=[]
    for name,main_idx,correction_idx in EXPANSIONS:
        main=tuple(values[i] for i in main_idx)
        correction=tuple(values[i] for i in correction_idx)
        main_ok=bool(_price_geometry_5(main,1))
        correction_ok=bool(_price_geometry_3(correction,-1))
        assessments.append(ExpansionAssessment(name,main_ok,correction_ok,
                                                main_ok and correction_ok))
    n=sum(item.accepted for item in assessments)
    state=("NO_ADMISSIBLE_5_PLUS_ABC_GEOMETRY" if n==0 else
           "ONE_HIERARCHICAL_GEOMETRY_ONLY_NOT_A_SIGNAL" if n==1 else
           "AMBIGUOUS_HIERARCHIES_FAIL_CLOSED")
    return HierarchyAssessment(state,tuple(assessments),n)
