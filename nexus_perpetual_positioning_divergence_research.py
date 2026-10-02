"""Research-only A9 perpetual positioning divergence strategy.

Uses verified public Bybit USDT perpetual funding/open-interest only as lagged
context for a strictly Spot long/flat strategy. It never executes derivatives,
never promotes to Paper automatically, and never grants Live authority.
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

from bybit_derivatives_core_v1 import (
    Client,
    ValidationError,
    expected_funding_count,
    fetch_funding,
    fetch_instrument,
    fetch_open_interest,
    milliseconds,
)

SCHEMA = "nexus.perpetual-positioning-divergence-research.v1"
PROOF_SCHEMA = "nexus.perpetual-positioning-input-proof.v1"
MECHANISM = "perpetual_positioning_divergence"
SYMBOLS = {"btc_usdt": "BTCUSDT", "eth_usdt": "ETHUSDT"}
START_DATE = "2026-07-03"
END_DATE = "2026-08-01"
START = pd.Timestamp(START_DATE, tz="UTC")
END_EXCLUSIVE = pd.Timestamp(END_DATE, tz="UTC") + pd.Timedelta(days=1)
BARS = 30 * 96
TRAIN_FRAC = 0.60
VALID_FRAC = 0.20
FUNDING_Q = 0.20
OI_Q = 0.70
STOP_ATR = 1.5
TARGET_ATR = 2.5
TIME_EXIT_BARS = 32
SIM_CASH = 10_000.0
POSITION_FRACTION = 0.10
RISK_FRACTION = 0.001
COST_PROFILES = {
    "conservative": (10.0, 5.0),
    "stress": (25.0, 15.0),
}
API_BASE_URLS = [
    "https://api.bybit.nl",
    "https://api.bybit.tr",
    "https://api.bybit.kz",
    "https://api.bybitgeorgia.ge",
    "https://api.bybit.ae",
    "https://api.bybit.id",
    "https://api.byhkbit.com",
    "https://api.manepa.jp",
    "https://api.bybit.com",
    "https://api.bytick.com",
]


class PositioningResearchError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def canonical_frame_digest(frame: pd.DataFrame) -> str:
    value = frame.copy()
    value = value.sort_values("timestamp").reset_index(drop=True)
    value["timestamp"] = pd.to_datetime(value["timestamp"], utc=True).map(
        lambda x: x.isoformat()
    )
    return digest(value.to_dict(orient="records"))


def _utc_ns(values: pd.Series) -> pd.Series:
    """Canonicalize exact UTC instants across Parquet datetime resolutions."""
    normalized = pd.to_datetime(values, utc=True, errors="raise")
    if normalized.isna().any():
        raise PositioningResearchError("missing timestamp in A9 inputs")
    return normalized.astype("datetime64[ns, UTC]")


def load_spot(root: Path, symbol: str) -> pd.DataFrame:
    path = root / symbol / "minute15.parquet"
    if path.is_symlink() or not path.is_file():
        raise PositioningResearchError(f"missing verified spot input: {symbol}")
    frame = pd.read_parquet(path).copy()
    frame["timestamp"] = _utc_ns(frame["timestamp"])
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    expected = pd.Series(
        pd.date_range(START, END_EXCLUSIVE, freq="15min", inclusive="left"),
        name="timestamp",
    ).astype("datetime64[ns, UTC]")
    if len(frame) != BARS or not frame["timestamp"].equals(expected):
        raise PositioningResearchError(f"incomplete exact 15m Spot grid: {symbol}")
    for name in ("open", "high", "low", "close", "volume"):
        frame[name] = pd.to_numeric(frame[name], errors="raise")
    return frame


def fetch_positioning(
    client: Client, symbol: str
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    history_start = START - pd.Timedelta(days=1)
    start_ms = milliseconds(history_start)
    end_ms = milliseconds(END_EXCLUSIVE)
    funding = fetch_funding(client, symbol, start_ms, end_ms)
    oi = fetch_open_interest(client, symbol, start_ms, end_ms, "15min")
    spec = fetch_instrument(client, symbol)

    if funding.empty or oi.empty:
        raise PositioningResearchError(f"missing positioning data: {symbol}")
    oi["timestamp"] = _utc_ns(oi["timestamp"])
    funding["timestamp"] = _utc_ns(funding["timestamp"])
    oi = oi.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    expected_oi = pd.DatetimeIndex(
        pd.date_range(history_start, END_EXCLUSIVE, freq="15min", inclusive="left")
    ).astype("datetime64[ns, UTC]")
    actual_oi = pd.DatetimeIndex(oi["timestamp"]).astype("datetime64[ns, UTC]")
    if not actual_oi.equals(expected_oi):
        missing = len(expected_oi.difference(actual_oi))
        unexpected = len(actual_oi.difference(expected_oi))
        raise PositioningResearchError(
            f"incomplete exact open-interest grid: {symbol} missing={missing} unexpected={unexpected}"
        )

    expected_funding = expected_funding_count(
        history_start, END_EXCLUSIVE, spec.funding_interval_minutes
    )
    if len(funding) != expected_funding:
        raise PositioningResearchError(
            f"incomplete funding history: {symbol} rows={len(funding)} expected={expected_funding}"
        )
    if funding["timestamp"].duplicated().any():
        raise PositioningResearchError(f"duplicate funding timestamp: {symbol}")
    return funding, oi, {
        "symbol": symbol,
        "funding_interval_minutes": spec.funding_interval_minutes,
        "funding_rows": int(len(funding)),
        "expected_funding_rows": int(expected_funding),
        "open_interest_rows": int(len(oi)),
        "expected_open_interest_rows": int(len(expected_oi)),
        "funding_semantic_sha256": canonical_frame_digest(funding),
        "open_interest_semantic_sha256": canonical_frame_digest(oi),
    }


def build_features(
    spot: pd.DataFrame, funding: pd.DataFrame, oi: pd.DataFrame
) -> pd.DataFrame:
    frame = spot.copy()
    idx = pd.DatetimeIndex(frame["timestamp"])

    oi_series = oi.set_index("timestamp")["open_interest"].reindex(idx)
    if oi_series.isna().any():
        raise PositioningResearchError("open-interest alignment gap")
    # Lag one full 15m bar to avoid timestamp-boundary ambiguity.
    frame["oi_lagged"] = oi_series.shift(1).to_numpy()
    frame["oi_change_4h"] = frame["oi_lagged"] / frame["oi_lagged"].shift(16) - 1.0

    funding_series = (
        funding.set_index("timestamp")["funding_rate"]
        .reindex(idx.union(pd.DatetimeIndex(funding["timestamp"])))
        .sort_index()
        .ffill()
        .reindex(idx)
    )
    # Also lag funding by one complete 15m bar.
    frame["funding_lagged"] = funding_series.shift(1).to_numpy()

    frame["price_return_4h_lagged"] = frame["close"].shift(1) / frame["close"].shift(17) - 1.0
    frame["prior_high_2h"] = frame["high"].shift(1).rolling(8, min_periods=8).max()
    prior_close = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prior_close).abs(),
            (frame["low"] - prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr"] = tr.rolling(14, min_periods=14).mean()
    frame["decision_at"] = frame["timestamp"] + pd.Timedelta(minutes=15)
    return frame


def train_thresholds(frame: pd.DataFrame, train_end: int) -> dict[str, float]:
    train = frame.iloc[:train_end]
    funding = train["funding_lagged"].dropna()
    oi_positive = train.loc[train["oi_change_4h"] > 0, "oi_change_4h"].dropna()
    if len(funding) < 100 or len(oi_positive) < 100:
        raise PositioningResearchError("insufficient train-only positioning observations")
    funding_q20 = float(funding.quantile(FUNDING_Q))
    oi_q70 = float(oi_positive.quantile(OI_Q))
    if not math.isfinite(funding_q20) or not math.isfinite(oi_q70) or oi_q70 <= 0:
        raise PositioningResearchError("invalid train-only positioning thresholds")
    return {
        "funding_extreme_max": min(0.0, funding_q20),
        "oi_growth_min": oi_q70,
    }


def build_signal(frame: pd.DataFrame, thresholds: dict[str, float]) -> np.ndarray:
    prior_crowding = (
        (frame["funding_lagged"].shift(1) <= thresholds["funding_extreme_max"])
        & (frame["oi_change_4h"].shift(1) >= thresholds["oi_growth_min"])
        & (frame["price_return_4h_lagged"].shift(1) <= 0.0)
    )
    confirmation = (
        (frame["close"] > frame["prior_high_2h"])
        & (frame["close"] > frame["open"])
        & frame["atr"].notna()
    )
    return (prior_crowding & confirmation).fillna(False).to_numpy(dtype=bool)


def simulate(
    frame: pd.DataFrame,
    signals: np.ndarray,
    *,
    fee_bps: float,
    slip_bps: float,
) -> dict[str, Any]:
    fee = fee_bps / 10_000.0
    slip = slip_bps / 10_000.0
    cash = peak = SIM_CASH
    position: dict[str, float] | None = None
    pending_entry: dict[str, float] | None = None
    pending_exit = False
    closed = wins = exposure = 0
    gross_profit = gross_loss = turnover = 0.0
    worst_dd = 0.0

    def close_position(raw_price: float) -> None:
        nonlocal cash, position, closed, wins, gross_profit, gross_loss, turnover
        assert position is not None
        exit_price = raw_price * (1.0 - slip)
        qty = position["qty"]
        exit_fee = qty * exit_price * fee
        cash += qty * exit_price - exit_fee
        pnl = qty * (exit_price - position["entry"]) - position["entry_fee"] - exit_fee
        gross_profit += max(0.0, pnl)
        gross_loss += max(0.0, -pnl)
        wins += int(pnl > 0)
        closed += 1
        turnover += qty * exit_price
        position = None

    for i, row in enumerate(frame.itertuples(index=False)):
        open_, high, low, close = map(float, (row.open, row.high, row.low, row.close))

        if pending_exit and position is not None:
            close_position(open_)
        pending_exit = False

        if pending_entry is not None and position is None:
            atr = float(pending_entry["atr"])
            entry = open_ * (1.0 + slip)
            stop = entry - STOP_ATR * atr
            target = entry + TARGET_ATR * atr
            risk_cash = cash * RISK_FRACTION
            qty = min(
                cash * POSITION_FRACTION / (entry * (1.0 + fee)),
                risk_cash / max(entry - stop, 1e-12),
            )
            if qty > 0 and stop > 0 and qty * entry * (1.0 + fee) <= cash:
                entry_fee = qty * entry * fee
                cash -= qty * entry + entry_fee
                turnover += qty * entry
                position = {
                    "qty": qty, "entry": entry, "entry_fee": entry_fee,
                    "stop": stop, "target": target, "age": 0.0,
                }
        pending_entry = None

        if position is not None:
            exposure += 1
            position["age"] += 1
            if low <= position["stop"]:
                close_position(min(open_, position["stop"]))
            elif high >= position["target"]:
                close_position(position["target"])
            elif i == len(frame) - 1:
                close_position(close)
            elif (
                (math.isfinite(float(row.funding_lagged)) and float(row.funding_lagged) >= 0.0)
                or (math.isfinite(float(row.oi_change_4h)) and float(row.oi_change_4h) < 0.0)
                or position["age"] >= TIME_EXIT_BARS
            ):
                pending_exit = True

        equity = cash + (position["qty"] * close if position is not None else 0.0)
        peak = max(peak, equity)
        worst_dd = max(worst_dd, 1.0 - equity / peak)

        if (
            i < len(frame) - 1
            and signals[i]
            and position is None
            and pending_entry is None
            and math.isfinite(float(row.atr))
        ):
            pending_entry = {"atr": float(row.atr)}

    pf = gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0)
    return {
        "starting_cash_usdt": SIM_CASH,
        "ending_cash_usdt": round(cash, 8),
        "net_return_pct": round((cash / SIM_CASH - 1.0) * 100.0, 6),
        "max_drawdown_pct": round(worst_dd * 100.0, 6),
        "closed_trades": int(closed),
        "win_rate_pct": round((wins / closed * 100.0) if closed else 0.0, 6),
        "profit_factor": round(pf, 6) if math.isfinite(pf) else "inf",
        "turnover_usdt": round(turnover, 6),
        "exposure_bar_ratio": round(exposure / len(frame), 6) if len(frame) else 0.0,
        "fee_bps": fee_bps,
        "slippage_bps": slip_bps,
        "trade_count_limit": None,
        "derivative_execution": False,
        "spot_long_flat_only": True,
    }


def run(spot_root: Path, output: Path, source_sha: str) -> dict[str, Any]:
    if len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha):
        raise PositioningResearchError("source_sha must be exact lower-case git SHA")

    client = Client(API_BASE_URLS, timeout=30.0, attempts=20, pause=0.03)
    rows: list[dict[str, Any]] = []
    thresholds: dict[str, dict[str, float]] = {}
    proof_rows: list[dict[str, Any]] = []

    for spot_symbol, linear_symbol in SYMBOLS.items():
        spot = load_spot(spot_root, spot_symbol)
        funding, oi, proof = fetch_positioning(client, linear_symbol)
        proof_rows.append(proof)
        frame = build_features(spot, funding, oi)
        n = len(frame)
        cut1 = int(n * TRAIN_FRAC)
        cut2 = int(n * (TRAIN_FRAC + VALID_FRAC))
        threshold = train_thresholds(frame, cut1)
        thresholds[spot_symbol] = threshold
        signals = build_signal(frame, threshold)

        for part, (lo, hi) in {
            "train": (0, cut1),
            "validation": (cut1, cut2),
            "historically_inspected_test": (cut2, n),
        }.items():
            part_frame = frame.iloc[lo:hi].reset_index(drop=True)
            part_signals = signals[lo:hi]
            for profile, (fee, slip) in COST_PROFILES.items():
                rows.append({
                    "symbol": spot_symbol,
                    "linear_symbol": linear_symbol,
                    "mechanism": MECHANISM,
                    "part": part,
                    "profile": profile,
                    "bars": hi - lo,
                    "signals": int(part_signals.sum()),
                    "funding_extreme_max_train_only": round(threshold["funding_extreme_max"], 10),
                    "oi_growth_min_train_only": round(threshold["oi_growth_min"], 10),
                    **simulate(part_frame, part_signals, fee_bps=fee, slip_bps=slip),
                })

    proof_core = {
        "schema": PROOF_SCHEMA,
        "venue": "bybit",
        "market": "usdt_linear_perpetual_public_v5",
        "spot_execution_market": "bybit_spot_public_archive",
        "period": {"start_date": START_DATE, "end_date": END_DATE},
        "endpoints": ["/v5/market/funding/history", "/v5/market/open-interest"],
        "open_interest_interval": "15min",
        "positioning_rows": proof_rows,
        "derivative_execution": False,
        "research_only": True,
        "paper_only": True,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    input_proof = {**proof_core, "proof_sha256": digest(proof_core)}

    core = {
        "schema": SCHEMA,
        "source_sha": source_sha,
        "mechanism": MECHANISM,
        "input_proof_sha256": input_proof["proof_sha256"],
        "period": {"start_date": START_DATE, "end_date": END_DATE},
        "threshold_method": "per_symbol_train_only_funding_q20_capped_at_zero_and_positive_oi_growth_q70",
        "thresholds": thresholds,
        "execution_model": "lag_positioning_one_full_15m_bar;confirm_on_closed_spot_bar;fill_next_spot_open",
        "historical_test_pristine": False,
        "independent_future_data_required": True,
        "research_only": True,
        "paper_only": True,
        "derivative_execution": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
        "qualification": "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT",
        "rows": rows,
    }
    report = {**core, "report_sha256": digest(core)}
    output.mkdir(parents=True, exist_ok=True)
    (output / "perpetual-positioning-input-proof.json").write_text(
        json.dumps(input_proof, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output / "perpetual-positioning-divergence-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spot-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    report = run(args.spot_root, args.output, args.source_sha)
    print(json.dumps({
        "mechanism": report["mechanism"],
        "qualification": report["qualification"],
        "rows": len(report["rows"]),
        "derivative_execution": report["derivative_execution"],
        "auto_promotion": report["automatic_strategy_promotion"],
        "live_authority": report["live_trading_authority"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
