"""Research-only A9 perpetual-positioning divergence evaluation.

The execution instrument is Spot long/cash only. Public Bybit USDT-linear
perpetual funding and open interest are context signals, never derivative
execution authority. All strategy decisions use completed observations and
entries/signal exits occur no earlier than the next Spot 15m open.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bybit_derivatives_core_v1 import Client, fetch_funding, milliseconds

SCHEMA = "nexus.perpetual-positioning-divergence-research.v1"
PROOF_SCHEMA = "nexus.verified-perpetual-positioning.v1"
MECHANISM = "perpetual_positioning_divergence"
SPOT_SYMBOLS = ("btc_usdt", "eth_usdt")
LINEAR_SYMBOLS = ("BTCUSDT", "ETHUSDT")
MIN_BARS = 30 * 96
STEP = pd.Timedelta(minutes=15)
TRAIN_FRAC = 0.60
VALID_FRAC = 0.20
FUNDING_LOW_Q = 0.25
OI_GROWTH_HIGH_Q = 0.75
SIM_CASH = 10_000.0
POSITION_FRACTION = 0.10
RISK_FRACTION = 0.001
MAX_DAILY_LOSS = 0.05
MAX_DRAWDOWN = 0.10
TIME_EXIT_BARS = 16
STOP_ATR = 1.5
TARGET_ATR = 2.0
COST_PROFILES = {
    "conservative": (10.0, 5.0),
    "stress": (25.0, 15.0),
}


class PositioningResearchError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 5_000_000:
        raise PositioningResearchError("source manifest unavailable, linked, or oversized")
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_ns(values: pd.Series) -> pd.Series:
    normalized = pd.to_datetime(values, utc=True, errors="raise")
    if normalized.isna().any():
        raise PositioningResearchError("missing timestamp in A9 inputs")
    return normalized.astype("datetime64[ns, UTC]")


def inclusive_dates(start_date: str, end_date: str) -> list[pd.Timestamp]:
    start = pd.Timestamp(start_date, tz="UTC")
    end = pd.Timestamp(end_date, tz="UTC")
    if end < start:
        raise PositioningResearchError("end_date precedes start_date")
    return list(pd.date_range(start, end, freq="1D"))
def fetch_open_interest_15m(
    client: Client,
    symbol: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    rows: dict[int, float] = {}
    for day in inclusive_dates(start_date, end_date):
        day_end = day + pd.Timedelta(days=1)
        payload = client.get(
            "/v5/market/open-interest",
            {
                "category": "linear",
                "symbol": symbol,
                "intervalTime": "15min",
                "startTime": int(day.timestamp() * 1000),
                "endTime": int(day_end.timestamp() * 1000),
                "limit": 200,
            },
        )
        items = payload.get("result", {}).get("list", [])
        local: dict[int, float] = {}
        for item in items:
            stamp = int(item["timestamp"])
            if int(day.timestamp() * 1000) <= stamp < int(day_end.timestamp() * 1000):
                value = float(item["openInterest"])
                if not math.isfinite(value) or value <= 0:
                    raise PositioningResearchError(f"invalid OI for {symbol}")
                local[stamp] = value
        expected = pd.date_range(day, day_end, freq=STEP, inclusive="left")
        local_index = pd.to_datetime(sorted(local), unit="ms", utc=True)
        if len(local) != 96 or not pd.DatetimeIndex(local_index).equals(expected):
            raise PositioningResearchError(
                f"incomplete 15m OI day for {symbol} {day.strftime('%Y-%m-%d')}"
            )
        overlap = set(rows).intersection(local)
        if overlap:
            raise PositioningResearchError(f"duplicate OI timestamps for {symbol}")
        rows.update(local)

    ordered = sorted(rows)
    expected_rows = len(inclusive_dates(start_date, end_date)) * 96
    if len(ordered) != expected_rows:
        raise PositioningResearchError(f"incomplete OI coverage for {symbol}")
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(ordered, unit="ms", utc=True),
            "open_interest": [rows[x] for x in ordered],
        }
    )


def fetch_positioning(
    client: Client,
    symbol: str,
    start_date: str,
    end_date: str,
) -> dict[str, pd.DataFrame]:
    oi = fetch_open_interest_15m(client, symbol, start_date, end_date)
    start = pd.Timestamp(start_date, tz="UTC")
    end_exclusive = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)
    funding = fetch_funding(
        client,
        symbol,
        int((start - pd.Timedelta(days=1)).timestamp() * 1000),
        int(end_exclusive.timestamp() * 1000),
    )
    if funding.empty or len(funding) < 4:
        raise PositioningResearchError(f"insufficient funding history for {symbol}")
    funding = funding.copy().sort_values("timestamp").drop_duplicates("timestamp")
    funding["timestamp"] = utc_ns(funding["timestamp"])
    if not np.isfinite(funding["funding_rate"].astype(float).to_numpy()).all():
        raise PositioningResearchError(f"non-finite funding for {symbol}")
    return {"oi": oi, "funding": funding}
def positioning_digest(data: dict[str, dict[str, pd.DataFrame]]) -> str:
    payload = []
    for symbol in LINEAR_SYMBOLS:
        oi = data[symbol]["oi"].copy()
        funding = data[symbol]["funding"].copy()
        oi["timestamp"] = utc_ns(oi["timestamp"]).map(lambda x: x.isoformat())
        funding["timestamp"] = utc_ns(funding["timestamp"]).map(lambda x: x.isoformat())
        payload.append(
            {
                "symbol": symbol,
                "oi": [
                    {"timestamp": t, "open_interest": round(float(v), 12)}
                    for t, v in zip(oi["timestamp"], oi["open_interest"])
                ],
                "funding": [
                    {"timestamp": t, "funding_rate": round(float(v), 12)}
                    for t, v in zip(funding["timestamp"], funding["funding_rate"])
                ],
            }
        )
    return digest(payload)


def build_positioning_proof(
    data: dict[str, dict[str, pd.DataFrame]],
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    dates = inclusive_dates(start_date, end_date)
    expected_oi_rows = len(dates) * 96
    counts = {}
    for symbol in LINEAR_SYMBOLS:
        oi = data[symbol]["oi"]
        funding = data[symbol]["funding"]
        if len(oi) != expected_oi_rows:
            raise PositioningResearchError("OI proof coverage mismatch")
        counts[symbol] = {
            "open_interest_rows": int(len(oi)),
            "funding_rows_with_lookback": int(len(funding)),
        }
    core = {
        "schema": PROOF_SCHEMA,
        "venue": "bybit",
        "product": "usdt_linear_perpetual_public_market_data",
        "symbols": list(LINEAR_SYMBOLS),
        "start_date": start_date,
        "end_date": end_date,
        "open_interest_endpoint": "/v5/market/open-interest",
        "open_interest_interval": "15min",
        "open_interest_availability_model": "one_completed_15m_interval_lag",
        "funding_endpoint": "/v5/market/funding/history",
        "funding_availability_model": "last_settled_event_at_or_before_decision_time",
        "counts": counts,
        "positioning_semantic_sha256": positioning_digest(data),
        "research_only": True,
        "spot_execution_only": True,
        "derivative_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "proof_sha256": digest(core)}
def prepare_symbol(
    spot_root: Path,
    spot_symbol: str,
    positioning: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    candles = pd.read_parquet(spot_root / spot_symbol / "minute15.parquet").copy()
    candles["timestamp"] = utc_ns(candles["timestamp"])
    candles = candles.sort_values("timestamp").reset_index(drop=True)
    if len(candles) < MIN_BARS:
        raise PositioningResearchError(f"{spot_symbol} needs at least {MIN_BARS} Spot bars")
    expected = pd.date_range(
        candles["timestamp"].iloc[0],
        periods=len(candles),
        freq=STEP,
    )
    if not pd.DatetimeIndex(candles["timestamp"]).equals(expected):
        raise PositioningResearchError(f"non-contiguous Spot 15m grid for {spot_symbol}")

    oi = positioning["oi"].copy()
    oi["timestamp"] = utc_ns(oi["timestamp"])
    oi = oi.sort_values("timestamp").reset_index(drop=True)
    if len(oi) != len(candles) or not oi["timestamp"].equals(candles["timestamp"]):
        raise PositioningResearchError(f"Spot/OI timestamp identity mismatch for {spot_symbol}")

    frame = candles[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    frame["decision_at"] = frame["timestamp"] + STEP

    # OI is deliberately lagged by one full 15m interval to avoid assuming
    # instant availability at the API timestamp.
    frame["open_interest_observed"] = pd.to_numeric(
        oi["open_interest"], errors="raise"
    ).shift(1)
    frame["oi_growth_1h"] = (
        frame["open_interest_observed"]
        / frame["open_interest_observed"].shift(4)
        - 1.0
    )

    funding = positioning["funding"][["timestamp", "funding_rate"]].copy()
    funding["timestamp"] = utc_ns(funding["timestamp"])
    funding = funding.sort_values("timestamp").reset_index(drop=True)
    decision = frame[["decision_at"]].copy().sort_values("decision_at")
    aligned = pd.merge_asof(
        decision,
        funding.rename(columns={"timestamp": "funding_timestamp"}),
        left_on="decision_at",
        right_on="funding_timestamp",
        direction="backward",
        allow_exact_matches=True,
    )
    frame["funding_rate"] = pd.to_numeric(aligned["funding_rate"], errors="coerce")

    prev_close = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr"] = tr.rolling(14, min_periods=14).mean()
    frame["price_return_1h"] = frame["close"] / frame["close"].shift(4) - 1.0
    return frame
def training_thresholds(frame: pd.DataFrame, train_end: int) -> dict[str, float]:
    train = frame.iloc[:train_end]
    funding = train["funding_rate"].dropna()
    oi_growth = train["oi_growth_1h"].replace([np.inf, -np.inf], np.nan).dropna()
    if len(funding) < 100 or len(oi_growth) < 500:
        raise PositioningResearchError("insufficient train positioning observations")
    thresholds = {
        "funding_low_q25": float(funding.quantile(FUNDING_LOW_Q)),
        "funding_median": float(funding.median()),
        "oi_growth_high_q75": float(oi_growth.quantile(OI_GROWTH_HIGH_Q)),
    }
    if not all(math.isfinite(x) for x in thresholds.values()):
        raise PositioningResearchError("non-finite A9 train thresholds")
    return thresholds


def build_signal(frame: pd.DataFrame, thresholds: dict[str, float]) -> np.ndarray:
    prior = (
        (frame["funding_rate"].shift(1) <= thresholds["funding_low_q25"])
        & (frame["oi_growth_1h"].shift(1) >= thresholds["oi_growth_high_q75"])
        & (frame["oi_growth_1h"].shift(1) > 0.0)
        & (frame["price_return_1h"].shift(1) <= 0.0)
    )
    response = (
        (frame["close"] > frame["high"].shift(1))
        & (frame["close"] > frame["open"])
    )
    valid = (
        frame["atr"].notna()
        & frame["funding_rate"].notna()
        & frame["oi_growth_1h"].notna()
    )
    return (prior & response & valid).fillna(False).to_numpy(dtype=bool)


def invalidation(frame: pd.DataFrame, thresholds: dict[str, float]) -> np.ndarray:
    invalid = (
        (frame["funding_rate"] > thresholds["funding_median"])
        | (frame["oi_growth_1h"] < 0.0)
    )
    return invalid.fillna(False).to_numpy(dtype=bool)
def simulate(
    frame: pd.DataFrame,
    signals: np.ndarray,
    invalid: np.ndarray,
    *,
    fee_bps: float,
    slip_bps: float,
) -> dict[str, Any]:
    if len(frame) != len(signals) or len(frame) != len(invalid):
        raise PositioningResearchError("invalid simulator vector lengths")
    fee = fee_bps / 10_000.0
    slip = slip_bps / 10_000.0
    cash = peak = SIM_CASH
    worst_dd = 0.0
    position = None
    pending_entry = False
    pending_exit = False
    day = None
    day_start = SIM_CASH
    day_paused = halted = False
    closed = wins = exposure = 0
    gross_profit = gross_loss = turnover = 0.0
    pending_atr = 0.0

    def close_position(raw_price: float) -> None:
        nonlocal cash, position, closed, wins, gross_profit, gross_loss, turnover
        exit_price = max(0.0, raw_price * (1.0 - slip))
        qty = position["qty"]
        exit_fee = qty * exit_price * fee
        cash += qty * exit_price - exit_fee
        pnl = qty * (exit_price - position["entry"]) - position["entry_fee"] - exit_fee
        gross_profit += max(0.0, pnl)
        gross_loss += max(0.0, -pnl)
        wins += int(pnl > 0.0)
        closed += 1
        turnover += qty * exit_price
        position = None

    for i, row in enumerate(frame.itertuples(index=False)):
        at = pd.Timestamp(row.decision_at)
        op, hi, lo, cl = map(float, (row.open, row.high, row.low, row.close))
        if day != at.floor("D"):
            day = at.floor("D")
            day_start = cash if position is None else cash + position["qty"] * op
            day_paused = False

        if pending_exit and position is not None:
            close_position(op)
        pending_exit = False

        if pending_entry and position is None and not halted and not day_paused:
            entry = op * (1.0 + slip)
            stop = entry - STOP_ATR * pending_atr
            target = entry + TARGET_ATR * pending_atr
            if pending_atr > 0.0 and stop > 0.0:
                risk_budget = max(cash, 0.0) * RISK_FRACTION
                qty = min(
                    cash * POSITION_FRACTION / (entry * (1.0 + fee)),
                    risk_budget / (entry - stop),
                )
                if qty > 0.0 and qty * entry * (1.0 + fee) <= cash:
                    entry_fee = qty * entry * fee
                    cash -= qty * entry + entry_fee
                    position = {
                        "qty": qty,
                        "entry": entry,
                        "entry_fee": entry_fee,
                        "stop": stop,
                        "target": target,
                        "age": 0,
                    }
                    turnover += qty * entry
        pending_entry = False

        if position is not None:
            exposure += 1
            position["age"] += 1
            if lo <= position["stop"]:
                close_position(min(op, position["stop"]))
            elif hi >= position["target"]:
                close_position(position["target"])
            elif i == len(frame) - 1:
                close_position(cl)
            elif invalid[i] or position["age"] >= TIME_EXIT_BARS:
                pending_exit = True

        equity = cash + (position["qty"] * cl if position is not None else 0.0)
        peak = max(peak, equity)
        worst_dd = max(worst_dd, 1.0 - equity / peak)
        if equity < day_start * (1.0 - MAX_DAILY_LOSS):
            day_paused = True
        if worst_dd > MAX_DRAWDOWN:
            halted = True

        if (
            i < len(frame) - 1
            and signals[i]
            and position is None
            and not pending_entry
            and not halted
            and not day_paused
            and math.isfinite(float(row.atr))
        ):
            pending_entry = True
            pending_atr = float(row.atr)

    net_return = cash / SIM_CASH - 1.0
    pf = gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0)
    return {
        "starting_cash_usdt": SIM_CASH,
        "ending_cash_usdt": round(cash, 8),
        "net_return_pct": round(net_return * 100.0, 6),
        "max_drawdown_pct": round(worst_dd * 100.0, 6),
        "closed_trades": int(closed),
        "win_rate_pct": round((wins / closed * 100.0) if closed else 0.0, 6),
        "profit_factor": round(pf, 6) if math.isfinite(pf) else "inf",
        "turnover_usdt": round(turnover, 6),
        "exposure_bar_ratio": round(exposure / len(frame), 6) if len(frame) else 0.0,
        "halted_on_drawdown": bool(halted),
        "fee_bps": fee_bps,
        "slippage_bps": slip_bps,
        "trade_count_limit": None,
        "execution_instrument": "spot_long_or_cash_only",
    }
def evaluate(
    spot_root: Path,
    positioning_data: dict[str, dict[str, pd.DataFrame]],
    start_date: str,
    end_date: str,
    source_sha: str,
    spot_source_manifest_sha256: str,
) -> dict[str, Any]:
    if len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha):
        raise PositioningResearchError("source_sha must be exact lower-case git SHA")
    if len(spot_source_manifest_sha256) != 64 or any(
        c not in "0123456789abcdef" for c in spot_source_manifest_sha256
    ):
        raise PositioningResearchError("Spot source manifest SHA256 is invalid")
    proof = build_positioning_proof(positioning_data, start_date, end_date)
    rows = []
    spot_payload = []
    threshold_map = {}
    for spot_symbol, linear_symbol in zip(SPOT_SYMBOLS, LINEAR_SYMBOLS):
        frame = prepare_symbol(spot_root, spot_symbol, positioning_data[linear_symbol])
        spot_payload.append(
            {
                "symbol": spot_symbol,
                "rows": [
                    {
                        "timestamp": pd.Timestamp(t).isoformat(),
                        "open": round(float(o), 12),
                        "high": round(float(h), 12),
                        "low": round(float(l), 12),
                        "close": round(float(c), 12),
                        "volume": round(float(v), 12),
                    }
                    for t, o, h, l, c, v in zip(
                        frame["timestamp"], frame["open"], frame["high"],
                        frame["low"], frame["close"], frame["volume"]
                    )
                ],
            }
        )
        n = len(frame)
        cut1 = int(n * TRAIN_FRAC)
        cut2 = int(n * (TRAIN_FRAC + VALID_FRAC))
        thresholds = training_thresholds(frame, cut1)
        threshold_map[spot_symbol] = {k: round(v, 10) for k, v in thresholds.items()}
        signals = build_signal(frame, thresholds)
        invalid = invalidation(frame, thresholds)
        parts = {
            "train": (0, cut1),
            "validation": (cut1, cut2),
            "historically_inspected_test": (cut2, n),
        }
        for part, (lo, hi) in parts.items():
            local = frame.iloc[lo:hi].reset_index(drop=True)
            for profile, (fee, slip) in COST_PROFILES.items():
                result = simulate(
                    local,
                    signals[lo:hi],
                    invalid[lo:hi],
                    fee_bps=fee,
                    slip_bps=slip,
                )
                rows.append(
                    {
                        "symbol": spot_symbol,
                        "context_contract": linear_symbol,
                        "timeframe": "minute15",
                        "mechanism": MECHANISM,
                        "part": part,
                        "profile": profile,
                        "bars": hi - lo,
                        "signals": int(signals[lo:hi].sum()),
                        "first_decision_utc": str(local["decision_at"].iloc[0]),
                        "last_decision_utc": str(local["decision_at"].iloc[-1]),
                        **result,
                    }
                )

    core = {
        "schema": SCHEMA,
        "source_sha": source_sha,
        "mechanism": MECHANISM,
        "selection_basis": "pre_registered_A9_positioning_divergence_not_OOS_ranking",
        "start_date": start_date,
        "end_date": end_date,
        "threshold_method": "per_symbol_train_only_funding_q25_median_and_oi_growth_q75",
        "thresholds": threshold_map,
        "spot_source_manifest_sha256": spot_source_manifest_sha256,
        "spot_semantic_sha256": digest(spot_payload),
        "execution_model": "closed_15m_context;OI_lagged_one_interval;entry_and_positioning_exit_next_open",
        "positioning_proof": proof,
        "historical_test_pristine": False,
        "independent_future_data_required": True,
        "research_only": True,
        "paper_only": True,
        "automatic_strategy_promotion": False,
        "derivative_execution_authority": False,
        "live_trading_authority": False,
        "qualification": "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT",
        "rows": rows,
    }
    return {**core, "report_sha256": digest(core)}
def run(
    spot_root: Path,
    output: Path,
    source_sha: str,
    config_path: Path,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    client = Client(
        config["api_base_urls"],
        float(config["timeout_seconds"]),
        int(config["maximum_attempts"]),
        float(config["request_pause_seconds"]),
    )
    positioning_data = {
        symbol: fetch_positioning(client, symbol, start_date, end_date)
        for symbol in LINEAR_SYMBOLS
    }
    report = evaluate(
        spot_root,
        positioning_data,
        start_date,
        end_date,
        source_sha,
        file_sha256(spot_root / "_source_manifest.json"),
    )
    output.mkdir(parents=True, exist_ok=True)
    path = output / "perpetual-positioning-divergence-report.json"
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spot-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--start-date", default="2026-07-03")
    parser.add_argument("--end-date", default="2026-08-01")
    args = parser.parse_args()
    report = run(
        args.spot_root,
        args.output,
        args.source_sha,
        args.config,
        args.start_date,
        args.end_date,
    )
    print(
        json.dumps(
            {
                "mechanism": report["mechanism"],
                "qualification": report["qualification"],
                "rows": len(report["rows"]),
                "positioning_sha256": report["positioning_proof"]["positioning_semantic_sha256"],
                "research_only": report["research_only"],
                "auto_promotion": report["automatic_strategy_promotion"],
                "derivative_execution_authority": report["derivative_execution_authority"],
                "live_authority": report["live_trading_authority"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())