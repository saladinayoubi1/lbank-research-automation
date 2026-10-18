"""Independent, stdlib reference for the four composite 1h/4h context fields.

No producer resampling, rolling, merge_asof, signal or execution code is used.
Dataset bindings identify inputs; they are not exchange authentication proofs.
The receipt preserves every as-of source index and source-prefix identity.
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median
from typing import Any

SCHEMA = "nexus.composite-higher-timeframe-audit.v1"
STEP = 900_000
INTERVALS = {"hour1": 3_600_000, "hour4": 14_400_000}
FIELDS = {"hour1": ("h1_compression", "h1_vol_ok"), "hour4": ("h4_up", "h4_range")}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
CONTRACT = {
    "clock": "UTC open timestamp plus full interval; close<=15m decision; latest closed row",
    "h1_compression": "mean(range[j-5:j+1]) < median(range[j-48:j])*0.8; j>=48",
    "h1_vol_ok": "range[j] < median(range[j-72:j])*1.65; j>=72; range=(high-low)/close, not volume",
    "h4_up": "close[j]>median(close[j-12:j]) and low[j]>min(low[j-11:j-3]); j>=12",
    "h4_range": "min(low[j-12:j])<=close[j]<=max(high[j-12:j]); j>=12",
    "warmup": "source row exists but insufficient rolling history: false; no closed source: null",
}
BOUNDARIES = {"independent_h1_h4_equations_verified": True,
              "independent_15m_features_verified": False,
              "independent_signal_equations_verified": False,
              "source_authenticity_proof": False,
              "paper_execution_authority": False, "live_trading_authority": False}


class HigherTimeframeAuditError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _utc_ms(at: Any) -> int:
    if (getattr(at, "tzinfo", None) is None or at.utcoffset().total_seconds() != 0
            or at.value % 1_000_000):
        raise HigherTimeframeAuditError("source/decision timestamps must be exact UTC milliseconds")
    return int(at.value // 1_000_000)


def _raw(frame: Any, interval: int) -> list[list]:
    rows = []
    for values in frame[["timestamp", "open", "high", "low", "close", "volume"]].itertuples(index=False, name=None):
        at = _utc_ms(values[0])
        prices = [float(x) for x in values[1:]]
        o, h, lo, c, v = prices
        if (at <= 0 or at % interval or (rows and at != rows[-1][0] + interval)
                or not all(math.isfinite(x) for x in prices)
                or min(o, h, lo, c) <= 0 or v < 0
                or h < max(o, c, lo) or lo > min(o, c, h)):
            raise HigherTimeframeAuditError("source OHLCV or UTC grid is invalid")
        rows.append([at, *prices])
    if not rows:
        raise HigherTimeframeAuditError("source rows are missing")
    return rows


def _reference(rows: list[list], timeframe: str) -> dict[str, str]:
    highs, lows, closes = ([r[i] for r in rows] for i in (2, 3, 4))
    first, second = [], []
    if timeframe == "hour1":
        ranges = [(h - lo) / c for h, lo, c in zip(highs, lows, closes)]
        for j, current in enumerate(ranges):
            first.append(j >= 48 and math.fsum(ranges[j-5:j+1]) / 6
                         < median(ranges[j-48:j]) * .8)
            second.append(j >= 72 and current < median(ranges[j-72:j]) * 1.65)
    else:
        for j, current in enumerate(closes):
            first.append(j >= 12 and current > median(closes[j-12:j])
                         and lows[j] > min(lows[j-11:j-3]))
            second.append(j >= 12 and min(lows[j-12:j]) <= current <= max(highs[j-12:j]))
    return {name: "".join("1" if value else "0" for value in mask)
            for name, mask in zip(FIELDS[timeframe], (first, second))}


def _joined(sources: Mapping[str, Any], indices: Mapping[str, Any], n: int) -> list[list]:
    return [[None if indices[tf][i] == -1 else int(sources[tf]["feature_masks"][field][indices[tf][i]])
             for tf in INTERVALS for field in FIELDS[tf]] for i in range(n)]


def audit_features(frames: Mapping[str, Any], observed: Any, *, candidate_digest: str,
                   source_sha: str, symbol: str, datasets: Mapping[str, Any],
                   source_kind: str = "canonical_runtime_rows") -> dict:
    """Compare ALL observed decisions to raw-source reconstruction, before fills."""
    decisions = [_utc_ms(at) for at in observed["decision_at"]]
    base = _raw(frames["minute15"], STEP)
    if decisions != [r[0] + STEP for r in base]:
        raise HigherTimeframeAuditError("observed decisions differ from raw 15m close clock")
    sources, indices = {}, {}
    for tf, interval in INTERVALS.items():
        raw = _raw(frames[tf], interval)
        data = datasets[tf]
        if (len(raw) != data["row_count"] or raw[0][0] != data["first_open_time_ms"]
                or raw[-1][0] != data["last_open_time_ms"]):
            raise HigherTimeframeAuditError("raw source rows differ from their dataset binding")
        prefix, chain = [], digest({"symbol": symbol, "timeframe": tf})
        for row in raw:
            chain = digest({"previous": chain, "row": row})
            prefix.append(chain)
        sources[tf] = {"raw_rows_sha256": digest(raw), "prefix_sha256": prefix,
                       "feature_masks": _reference(raw, tf)}
        close_clock = [r[0] + interval for r in raw]
        indices[tf] = [bisect_right(close_clock, at) - 1 for at in decisions]
    expected = _joined(sources, indices, len(decisions))
    fields = [field for tf in INTERVALS for field in FIELDS[tf]]
    actual = []
    for i, values in enumerate(observed[fields].itertuples(index=False, name=None)):
        row = []
        for field, value, want in zip(fields, values, expected[i]):
            number = float(value)
            if (want is None and not math.isnan(number)) or (want is not None and number != want):
                raise HigherTimeframeAuditError(f"independent {field} mismatch at decision {i}")
            row.append(None if want is None else int(number))
        actual.append(row)
    core = {"schema_version": SCHEMA,
            "identity": {"candidate_digest": candidate_digest, "source_sha": source_sha, "symbol": symbol},
            "source_kind": source_kind, "datasets_digest": digest(dict(datasets)),
            "reference_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "formula_contract": CONTRACT,
            "decision_grid": {"rows": len(decisions), "first_close_ms": decisions[0], "last_close_ms": decisions[-1]},
            "sources": sources, "asof_source_indices": indices,
            "observed_values_sha256": digest(actual), **BOUNDARIES}
    result = {**core, "audit_digest": digest(core)}
    verify_audit(result, candidate_digest=candidate_digest, source_sha=source_sha,
                 symbol=symbol, datasets=datasets, source_kind=source_kind)
    return result


def verify_audit(value: Any, *, candidate_digest: str, source_sha: str, symbol: str,
                 datasets: Mapping[str, Any], source_kind: str = "canonical_runtime_rows") -> None:
    """Verify receipt identity, full coverage and exact as-of indices without pandas.

    The actual raw-source math is checked by audit_features during producer/QA
    replay; receipt hashes alone do not independently authenticate market data.
    """
    try:
        core = dict(value)
        claimed = core.pop("audit_digest")
        identity = {"candidate_digest": candidate_digest, "source_sha": source_sha, "symbol": symbol}
        if (not HEX64.fullmatch(str(candidate_digest)) or not HEX40.fullmatch(str(source_sha))
                or symbol not in {"BTCUSDT", "ETHUSDT"} or claimed != digest(core)
                or set(core) != {"schema_version", "identity", "source_kind", "datasets_digest", "reference_code_sha256",
                                 "formula_contract", "decision_grid", "sources", "asof_source_indices",
                                 "observed_values_sha256", *BOUNDARIES}
                or core["schema_version"] != SCHEMA or core["identity"] != identity
                or source_kind not in {"canonical_runtime_rows", "pinned_archive_parquet_rows"}
                or core["source_kind"] != source_kind or core["datasets_digest"] != digest(dict(datasets))
                or core["formula_contract"] != CONTRACT
                or not HEX64.fullmatch(str(core["reference_code_sha256"]))
                or any(core.get(k) is not v for k, v in BOUNDARIES.items())):
            raise HigherTimeframeAuditError("higher-timeframe receipt identity or scope is invalid")
        base = datasets["minute15"]
        grid = {"rows": base["row_count"], "first_close_ms": base["first_open_time_ms"] + STEP,
                "last_close_ms": base["last_open_time_ms"] + STEP}
        if (core["decision_grid"] != grid or any(type(v) is not int for v in core["decision_grid"].values())
                or grid["rows"] < 2 or grid["last_close_ms"] - grid["first_close_ms"] != (grid["rows"]-1)*STEP
                or grid["first_close_ms"] % STEP or grid["last_close_ms"] % STEP
                or set(core["sources"]) != set(INTERVALS) or set(core["asof_source_indices"]) != set(INTERVALS)):
            raise HigherTimeframeAuditError("higher-timeframe decision coverage is invalid")
        for tf, interval in INTERVALS.items():
            data, proof = datasets[tf], core["sources"][tf]
            n, first, last = data["row_count"], data["first_open_time_ms"], data["last_open_time_ms"]
            if (any(type(x) is not int for x in (n, first, last)) or n < 1 or first <= 0
                    or first % interval or last != first + (n-1)*interval
                    or not HEX64.fullmatch(str(data["binding_sha256"]))
                    or set(proof) != {"raw_rows_sha256", "prefix_sha256", "feature_masks"}
                    or not HEX64.fullmatch(str(proof["raw_rows_sha256"]))
                    or type(proof["prefix_sha256"]) is not list or len(proof["prefix_sha256"]) != n
                    or any(not HEX64.fullmatch(str(x)) for x in proof["prefix_sha256"])
                    or set(proof["feature_masks"]) != set(FIELDS[tf])
                    or any(type(s) is not str or len(s) != n or set(s)-{"0", "1"} for s in proof["feature_masks"].values())):
                raise HigherTimeframeAuditError("higher-timeframe source proof is invalid")
            expected = [max(-1, min(n-1, (grid["first_close_ms"] + i*STEP - first)//interval - 1))
                        for i in range(grid["rows"])]
            observed = core["asof_source_indices"][tf]
            if type(observed) is not list or any(type(i) is not int for i in observed) or observed != expected:
                raise HigherTimeframeAuditError("higher-timeframe candle was consumed before/after its correct UTC close")
        if core["observed_values_sha256"] != digest(_joined(core["sources"], core["asof_source_indices"], grid["rows"])):
            raise HigherTimeframeAuditError("higher-timeframe observed values do not match the source join")
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        if isinstance(exc, HigherTimeframeAuditError):
            raise
        raise HigherTimeframeAuditError("malformed higher-timeframe audit") from exc
