"""Consume the existing fixed shared-500 diagnostic inside composite VAL-40.

Numerical input witnesses and full compact trade ledgers are retained. The
independent stdlib reference verifies all six cells; separate QA still replays
canonical sources and signals. This does not certify an economic edge, source
strategy exits, portfolio drawdown protection, prospective capture or admission.
"""
from hashlib import sha256
import json
import math
from pathlib import Path

from nexus_shared_cash_reference import (COLUMNS, FIELDS, PARTITIONS, PROFILES, STEP, SYMBOLS,
                                        SharedCashReferenceError, compare, partition, validate_inputs)

SCHEMA = "nexus.composite-shared-cash-diagnostic.v1"
ENGINE_SHA = "d7509c58feac819ab7a7abbb94be928563b3cf7d582f2444767ea9217f56a0b7"
CONTRACT_SHA = "7fbd29865e0196f48e4a1ac7811c4a1f3fa775ac294b50c1271e29ad41372b3e"
BOUNDARIES = dict(research_diagnostic_only=True, independent_numerical_reconstruction=True,
                  canonical_source_authentication_requires_qa_replay=True,
                  source_strategy_risk_and_exit_certified=False, economic_edge_established=False,
                  owner_shared_500_portfolio_verified=False, paper_execution_authority=False,
                  live_trading_authority=False, orders=0)


def digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,
                             allow_nan=False).encode()).hexdigest()


def _identity(candidate, source_sha, evaluations):
    return dict(candidate_digest=candidate["candidate_digest"], source_sha=source_sha,
                strategy_config_digest=digest(candidate["strategy_config"]),
                datasets={r["symbol"]:r["datasets"] for r in evaluations},
                signal_capture_digests={r["symbol"]:r["emitted_signal_trace"]["capture"]["capture_digest"]
                                        for r in evaluations})


def _pack(result, captures):
    events = {s:{e["earliest_entry_open_ms"]:e["event_id"] for e in captures[s]["events"]} for s in SYMBOLS}
    return {**{k:result[k] for k in FIELDS if k != "ledger"},
            "ledger_rows":[[r[k] for k in COLUMNS]+[events[r["symbol"]][r["entry_open_ms"]]]
                           for r in result["ledger"]]}


def diagnostic_state(cells):
    summaries = [cell for profiles in cells.values() for cell in profiles.values()]
    if any(c["net_pnl_usdt"] < 0 for c in summaries):
        return "NEGATIVE_SHARED_CASH_CELL"
    if sum(c["trades"] for c in summaries) == 0:
        return "INCONCLUSIVE_NO_SHARED_CASH_EXECUTION"
    if any(c["net_pnl_usdt"] == 0 for c in summaries):
        return "INCONCLUSIVE_ZERO_SHARED_CASH_CELL"
    return "NUMERICALLY_POSITIVE_RESEARCH_DIAGNOSTIC_ONLY"


def build_shared_cash(frames, signals, *, candidate, source_sha, evaluations):
    if type(candidate["strategy_config"].get("risk_variant")) is not int or candidate["strategy_config"]["risk_variant"] != 0:
        raise SharedCashReferenceError("shared 500 diagnostic supports reviewed risk_variant=0 only")
    from research import strategy_finder_shared_cash_physical as production
    if sha256(Path(production.__file__).read_bytes()).hexdigest() != ENGINE_SHA:
        raise SharedCashReferenceError("shared cash engine differs from reviewed bytes")
    captures = {r["symbol"]:r["emitted_signal_trace"]["capture"] for r in evaluations}
    inputs = {}
    for symbol in SYMBOLS:
        rows = []
        for values in frames[symbol][["open","high","low","close","atr"]].itertuples(index=False,name=None):
            rows.append([None if j == 4 and math.isnan(float(v)) else float(v) for j,v in enumerate(values)])
        inputs[symbol] = rows
        mask = "".join("1" if v else "0" for v in signals[symbol])
        if mask != captures[symbol]["signal_mask"]:
            raise SharedCashReferenceError("shared cash mask differs from captured signals")
        times = [int(v.value//1_000_000) for v in frames[symbol]["decision_at"]]
        grid = captures[symbol]["decision_grid"]
        if times != [grid["first_close_ms"]+i*STEP for i in range(grid["rows"])]:
            raise SharedCashReferenceError("shared cash clock differs from captured decisions")
    # Reuse the existing engine without changing its frozen execution bytes.
    result = production.sidecar_summary(frames, signals, stop_policy="prior_range_v1")
    cells = {name:{profile:_pack(result["partitions"][name][profile], captures)
                  for profile in PROFILES} for name in PARTITIONS}
    core = dict(schema_version=SCHEMA, identity=_identity(candidate,source_sha,evaluations),
                execution_engine_sha256=ENGINE_SHA, execution_contract=production.execution_contract(),
                physical_input_columns=["open","high","low","close","atr"], physical_inputs=inputs,
                ledger_columns=[*COLUMNS,"emitted_signal_event_id"], cells=cells,
                diagnostic_state=diagnostic_state(cells), **BOUNDARIES)
    proof = {**core,"portfolio_digest":digest(core)}
    verify_shared_cash(proof,candidate=candidate,source_sha=source_sha,evaluations=evaluations)
    return proof


def verify_shared_cash(value, *, candidate, source_sha, evaluations):
    required = {"schema_version","identity","execution_engine_sha256","execution_contract",
                "physical_input_columns","physical_inputs","ledger_columns","cells",
                "diagnostic_state","portfolio_digest",*BOUNDARIES}
    if (type(value) is not dict or set(value) != required or value.get("schema_version") != SCHEMA
        or value.get("identity") != _identity(candidate,source_sha,evaluations)
        or value.get("execution_engine_sha256") != ENGINE_SHA
        or digest(value.get("execution_contract")) != CONTRACT_SHA
        or type(candidate["strategy_config"].get("risk_variant")) is not int
        or candidate["strategy_config"]["risk_variant"] != 0
        or value.get("physical_input_columns") != ["open","high","low","close","atr"]
        or value.get("ledger_columns") != [*COLUMNS,"emitted_signal_event_id"]
        or any(type(value.get(k)) is not type(v) or value.get(k) != v for k,v in BOUNDARIES.items())
        or value.get("portfolio_digest") != digest({k:v for k,v in value.items() if k != "portfolio_digest"})):
        raise SharedCashReferenceError("shared cash identity, model, digest or authority rejected")
    captures = {r["symbol"]:r["emitted_signal_trace"]["capture"] for r in evaluations}
    n = validate_inputs(value["physical_inputs"],captures)
    bounds = ((0,int(n*.6)),(int(n*.6),int(n*.8)),(int(n*.8),n))
    if type(value["cells"]) is not dict or set(value["cells"]) != set(PARTITIONS):
        raise SharedCashReferenceError("all shared cash partitions required")
    for name,(lo,hi) in zip(PARTITIONS,bounds):
        if set(value["cells"][name]) != set(PROFILES):
            raise SharedCashReferenceError("both shared cash cost profiles required")
        for profile in PROFILES:
            expected = partition(value["physical_inputs"],captures,lo,hi,profile)
            # Check numeric fields by name (quantity has a tighter tolerance),
            # then exact event identities. Packing alone loses numeric names.
            cell = value["cells"][name][profile]
            rows = cell.get("ledger_rows")
            if type(rows) is not list or any(type(r) is not list or len(r) != len(COLUMNS)+1 for r in rows):
                raise SharedCashReferenceError("complete shared cash ledger required")
            unpacked = {**{k:v for k,v in cell.items() if k != "ledger_rows"},
                        "ledger":[dict(zip(COLUMNS,r[:-1])) for r in rows]}
            compare(unpacked,expected)
            if [r[-1] for r in rows] != [r[-1] for r in _pack(expected,captures)["ledger_rows"]]:
                raise SharedCashReferenceError("shared cash ledger signal identity mismatch")
    if value.get("diagnostic_state") != diagnostic_state(value["cells"]):
        raise SharedCashReferenceError("shared cash diagnostic conclusion mismatch")
