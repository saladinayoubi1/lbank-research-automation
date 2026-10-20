"""Independent fixed-portfolio signal and Decimal execution reconstruction.

No producer, signal helper, fill observer or engine implementation is imported.
The public audit fixes the prospective interval. It grants numerical evidence
only; market admission and worker/lease verification remain separate contracts.
"""
from __future__ import annotations

from collections import deque
from decimal import Decimal, localcontext
import math
from statistics import median

import numpy as np
import pandas as pd

SYMBOLS = ["btc_usdt", "eth_usdt"]
ANCHOR = pd.Timestamp("2022-12-01T00:00:00Z")
PERIOD = {"start": "2026-10-19", "end": "2027-01-17"}
SCHEMA = "nexus.portfolio-v3-forward-independent-numerical-qa.v1"
D = Decimal
ZERO = D(0)
EPS = D("1e-12")


class IndependentQAError(ValueError):
    pass


def _market(market):
    times = market.get("timestamps")
    if (market.get("symbols") != SYMBOLS or not isinstance(times, pd.Series)
            or str(times.dtype) != "datetime64[ns, UTC]" or len(times) < 3
            or times.isna().any() or times.duplicated().any()
            or times.iloc[0] != ANCHOR
            or not (times.diff().dropna() == pd.Timedelta(hours=4)).all()):
        raise IndependentQAError("Independent QA requires the original anchored UTC 4h grid")
    for name in ("open", "high", "low", "close"):
        values = market.get(name)
        if (not isinstance(values, np.ndarray) or values.dtype.kind != "f"
                or values.shape != (len(times), 2) or not np.isfinite(values).all()
                or (values <= 0).any()):
            raise IndependentQAError("Invalid physical source prices")
    if ((market["high"] < np.maximum(market["open"], market["close"])).any()
            or (market["low"] > np.minimum(market["open"], market["close"])).any()
            or (market["high"] < market["low"]).any()):
        raise IndependentQAError("Invalid physical OHLC envelope")
    return times


def reference_weights(market):
    """Rebuild the one frozen candidate at original global review rows.

    Arithmetic uses Python math/statistics rather than the producer's rolling
    pandas implementation. Original ties select BTC; rounding is ties-to-even.
    No future row contributes to the target of an earlier review.
    """
    times = _market(market)
    close = market["close"]
    result = np.zeros((len(times), 2), dtype=float)
    for row in range(0, len(times), 42):
        candidates = []
        for asset in range(2):
            if row < 540 or close[row, asset] / close[row - 540, asset] - 1 <= 0:
                continue
            components = [
                math.log1p(max(float(close[row, asset] / close[row - days * 6, asset] - 1),
                                 -0.999999)) / math.sqrt(days)
                for days in (30, 90, 180) if row >= days * 6
            ]
            if components:
                candidates.append((median(components), asset))
        if not candidates:
            continue
        # Stable ascending asset order retains BTC for an exact ranking tie.
        _, asset = max(candidates, key=lambda item: item[0])
        changes = [float(close[k, asset] / close[k - 1, asset] - 1)
                   for k in range(row - 179, row + 1)]
        mean = math.fsum(changes) / 180
        variance = math.fsum((value - mean) ** 2 for value in changes) / 180
        vol = math.sqrt(variance * 2191.5)
        if vol > 0:
            scale = min(1.0, max(0.0, 0.3 / vol))
            result[row:row + 42, asset] = min(1.0, max(0.0, round(scale / 0.25) * 0.25))
    return result


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise IndependentQAError("Nonfinite, boolean or nonnumeric evidence")
    return D(str(value))


def _match(expected, actual, path="evidence"):
    if isinstance(expected, dict):
        if type(actual) is not dict or set(actual) != set(expected):
            raise IndependentQAError("Evidence fields differ: " + path)
        for key, value in expected.items():
            _match(value, actual[key], path + "." + key)
    elif isinstance(expected, list):
        if type(actual) is not list or len(actual) != len(expected):
            raise IndependentQAError("Evidence length differs: " + path)
        for index, (a, b) in enumerate(zip(expected, actual)):
            _match(a, b, path + "." + str(index))
    elif type(expected) in (int, bool, str) or expected is None:
        if type(actual) is not type(expected) or actual != expected:
            raise IndependentQAError("Evidence identity differs: " + path)
    else:
        value = _number(actual)
        reference = expected if isinstance(expected, D) else D(str(expected))
        tolerance = D("0.000002")
        if path.endswith(".closed_bar_threshold_fraction"):
            tolerance = ZERO
        elif "quantit" in path or "price_usdt" in path:
            tolerance = D("0.00000001")
        elif "max_drawdown" in path or "average_exposure" in path:
            tolerance = D("0.000000001")
        elif "total_return" in path or "turnover" in path:
            tolerance = D("0.00000001")
        elif "sharpe" in path:
            tolerance = D("0.0000001") + abs(reference) * D("1e-10")
        if abs(reference - value) > tolerance:
            raise IndependentQAError("Independent numeric mismatch: " + path)


def audit_cell(market, weights, trace, metrics, profile, *, scheduled, guarded):
    """Audit all 540 prospective rows against source and exact fixed costs."""
    times = _market(market)
    expected = pd.date_range(ANCHOR, "2027-01-17T00:00:00Z", freq="4h", inclusive="left")
    if not pd.DatetimeIndex(times).equals(expected):
        raise IndependentQAError("Full fixed historical/future grid required")
    return _audit(market, weights, trace, metrics, profile, scheduled=scheduled,
                  guarded=guarded, period=PERIOD, expected_rows=540)


def _audit(market, weights, trace, metrics, profile, *, scheduled, guarded,
           period, expected_rows=None):
    """Private reusable arithmetic kernel; shorter periods are test fixtures."""
    times = _market(market)
    if type(scheduled) is not bool or type(guarded) is not bool:
        raise IndependentQAError("Explicit fixed schedule and risk controls required")
    if (type(profile) is not dict or set(profile) != {"initial_cash", "fee_bps", "slippage_bps"}
            or _number(profile["initial_cash"]) != D(500)
            or (_number(profile["fee_bps"]), _number(profile["slippage_bps"]))
            not in {(D(10), D(5)), (D(15), D(10)), (D(25), D(15))}):
        raise IndependentQAError("Original shared-500 cost profile required")
    if (not isinstance(weights, np.ndarray) or weights.dtype.kind != "f"
            or weights.shape != (len(times), 2) or not np.isfinite(weights).all()
            or (weights < 0).any() or (weights.sum(axis=1) > 1 + 1e-10).any()):
        raise IndependentQAError("Invalid source-bound book targets")
    start, end = (pd.Timestamp(period[key], tz="UTC") for key in ("start", "end"))
    idx = np.flatnonzero(((times >= start) & (times < end)).to_numpy())
    if (len(idx) < 3 or (expected_rows is not None and len(idx) != expected_rows)
            or times.iloc[idx[0]] != start or times.iloc[idx[-1]] + pd.Timedelta(hours=4) != end):
        raise IndependentQAError("Missing fixed study rows")
    with localcontext() as context:
        context.prec = 50
        expected_trace, expected_metrics = _reconstruct(
            market, weights, profile, idx, period, scheduled, guarded)
        _match(expected_trace, trace, "trace")
        _match(expected_metrics, metrics, "metrics")
        return _summary(expected_trace, market, idx, expected_metrics)


def _reconstruct(market, weights, profile, idx, period, scheduled, guarded):
    times = market["timestamps"]
    cash = initial = _number(profile["initial_cash"])
    fee_rate = _number(profile["fee_bps"]) / D(10000)
    slip = _number(profile["slippage_bps"]) / D(10000)
    quantity = [ZERO, ZERO]
    total_fees = total_notional = ZERO
    counts = [0, 0]
    minimum_cash, events = cash, 0
    peak, armed, halted = cash, False, False
    trigger_time = exit_time = trigger_equity = exit_cash = None
    forced_count = 0
    tape = {"schema": "nexus.portfolio-v3-original-fill-trace.v1",
            "initial_cash_usdt": initial, "period": dict(period),
            "symbols": list(SYMBOLS), "fills": [], "equity_marks": []}

    def fill(asset, side, global_row, amount, base_price, terminal=False):
        nonlocal cash, total_fees, total_notional
        px = base_price * (D(1) + slip if side == "buy" else D(1) - slip)
        gross = amount * px
        fee = gross * fee_rate
        if side == "buy":
            cash -= gross + fee
            quantity[asset] += amount
        else:
            cash += gross - fee
            quantity[asset] -= amount
            if terminal:
                quantity[asset] = ZERO
        total_fees += fee
        total_notional += gross
        counts[asset] += 1
        opened = times.iloc[global_row]
        executed = opened + pd.Timedelta(hours=4) if terminal else opened
        tape["fills"].append({
            "sequence": len(tape["fills"]), "symbol": SYMBOLS[asset], "side": side,
            "fill_kind": "terminal_bar_close" if terminal else "next_bar_open",
            "source_bar_open_utc": opened.isoformat(), "executed_at_utc": executed.isoformat(),
            "quantity": amount, "price_usdt": px, "fee_usdt": fee,
            "cash_after_usdt": cash, "asset_quantity_after": quantity[asset]})

    for row, g in enumerate(idx):
        opened = [_number(float(value)) for value in market["open"][g]]
        closed = [_number(float(value)) for value in market["close"][g]]
        changed = row > 1 and not np.array_equal(weights[g - 1], weights[g - 2])
        due = scheduled and row > 0 and (int(g) - 1) % 42 == 0
        if guarded and armed and row > 0:
            sold = False
            for asset in range(2):
                if quantity[asset] > EPS:
                    fill(asset, "sell", g, quantity[asset], opened[asset])
                    quantity[asset] = ZERO
                    forced_count += 1
                    sold = True
            minimum_cash = min(minimum_cash, cash)
            events += int(sold)
            halted, armed = True, False
            exit_time, exit_cash = times.iloc[g].isoformat(), cash
        if row > 0 and not halted and not armed and (row == 1 or changed or due):
            at_open = cash + sum(q * px for q, px in zip(quantity, opened))
            desired = [at_open * _number(float(weights[g - 1, a])) / opened[a] for a in range(2)]
            changes = [desired[a] - quantity[a] for a in range(2)]
            traded = False
            for asset in range(2):
                if changes[asset] < -EPS:
                    fill(asset, "sell", g, -changes[asset], opened[asset])
                    traded = True
            purchases = [a for a in range(2) if changes[a] > EPS]
            wanted = sum((changes[a] * opened[a] * (D(1) + slip) * (D(1) + fee_rate)
                          for a in purchases), ZERO)
            ratio = min(D(1), max(cash, ZERO) / wanted) if wanted > 0 else ZERO
            for asset in purchases:
                amount = changes[asset] * ratio
                if amount > EPS:
                    fill(asset, "buy", g, amount, opened[asset])
                    traded = True
            if cash < D("-0.0000001") or any(q < -EPS for q in quantity):
                raise IndependentQAError("Independent Spot reconstruction breached wallet")
            cash = max(cash, ZERO)
            minimum_cash = min(minimum_cash, cash)
            events += int(traded)
        equity = cash + sum(q * px for q, px in zip(quantity, closed))
        if guarded and not halted and not armed:
            peak = max(peak, equity)
            if equity <= peak * D("0.8"):
                armed = True
                trigger_time = (times.iloc[g] + pd.Timedelta(hours=4)).isoformat()
                trigger_equity = equity
        tape["equity_marks"].append({
            "bar_closed_at_utc": (times.iloc[g] + pd.Timedelta(hours=4)).isoformat(),
            "equity_usdt": equity, "cash_usdt": cash, "asset_quantities": list(quantity)})
    last = int(idx[-1])
    for asset in range(2):
        if quantity[asset] > EPS:
            fill(asset, "sell", last, quantity[asset], _number(float(market["close"][last, asset])), True)
    minimum_cash = min(minimum_cash, cash)
    tape["equity_marks"][-1].update(equity_usdt=cash, cash_usdt=cash, asset_quantities=list(quantity))
    tape.update(terminal_cash_usdt=cash, terminal_quantities=list(quantity))
    equity = [mark["equity_usdt"] for mark in tape["equity_marks"]]
    mark_peak, drawdown = equity[0], ZERO
    for value in equity:
        mark_peak = max(mark_peak, value)
        drawdown = max(drawdown, D(1) - value / mark_peak)
    changes = [float(b / a - 1) for a, b in zip(equity, equity[1:])]
    mean = math.fsum(changes) / len(changes)
    sd = math.sqrt(math.fsum((x - mean) ** 2 for x in changes) / len(changes))
    metrics = {"total_return": cash / initial - 1, "max_drawdown": drawdown,
               "sharpe": mean / sd * math.sqrt(2191.5) if sd > 0 else 0.0,
               "fill_count": sum(counts), "asset_fill_counts": counts,
               "turnover": total_notional / initial, "total_fees": total_fees,
               "average_exposure": math.fsum(float(weights[g].sum()) for g in idx[:-1]) / (len(idx) - 1),
               "minimum_cash_usdt": minimum_cash, "rebalance_event_count": events}
    if guarded:
        metrics["causal_risk_audit"] = {
            "schema": "nexus.portfolio-v3-causal-close-dd20-nextopen.v1",
            "closed_bar_threshold_fraction": 0.2,
            "trigger_observed_after_close_utc": trigger_time,
            "trigger_mark_to_market_equity_usdt": trigger_equity,
            "first_actual_next_open_exit_utc": exit_time,
            "liquidation_cash_after_all_sales_usdt": exit_cash,
            "forced_sell_fill_count": forced_count, "halted_for_rest_of_period": halted,
            "trigger_on_last_bar_no_next_open": armed,
            "could_gap_beyond_threshold": True, "no_reentry_after_exit": True,
            "research_only": True, "paper_eligible": False, "live_enabled": False}
    return tape, metrics


def _summary(tape, market, idx, metrics):
    """Attribute verified cash flows without calling FIFO segments positions."""
    monthly = {}

    def month(key):
        return monthly.setdefault(key, {"closed_positions": 0, "closed_fifo_lot_segments": 0,
                                       "realized_position_net_pnl_usdt": ZERO,
                                       "fifo_exit_net_pnl_usdt": ZERO,
                                       "execution_fees_usdt": ZERO, "execution_slippage_usdt": ZERO,
                                       "mark_to_market_net_pnl_usdt": ZERO})

    previous = tape["initial_cash_usdt"]
    for g, mark in zip(idx, tape["equity_marks"]):
        month(market["timestamps"].iloc[g].strftime("%Y-%m"))["mark_to_market_net_pnl_usdt"] += mark["equity_usdt"] - previous
        previous = mark["equity_usdt"]
    inventory = {s: deque() for s in SYMBOLS}
    episodes = {s: None for s in SYMBOLS}
    closed_positions = []
    segments = 0
    all_slippage = ZERO
    source_rows = {stamp.isoformat(): i for i, stamp in enumerate(market["timestamps"])}
    for fill in tape["fills"]:
        symbol, quantity, fee = fill["symbol"], fill["quantity"], fill["fee_usdt"]
        gross = quantity * fill["price_usdt"]
        a, g = SYMBOLS.index(symbol), source_rows[fill["source_bar_open_utc"]]
        field = "close" if fill["fill_kind"] == "terminal_bar_close" else "open"
        raw_price = _number(float(market[field][g, a]))
        slippage = quantity * abs(fill["price_usdt"] - raw_price)
        all_slippage += slippage
        row = month(fill["executed_at_utc"][:7])
        row["execution_fees_usdt"] += fee
        row["execution_slippage_usdt"] += slippage
        episode = episodes[symbol]
        if fill["side"] == "buy":
            if episode is None:
                episode = {"symbol": symbol, "entry_at_utc": fill["executed_at_utc"],
                           "net_pnl_usdt": ZERO, "fees_usdt": ZERO, "slippage_usdt": ZERO}
                episodes[symbol] = episode
            episode["net_pnl_usdt"] -= gross + fee
            inventory[symbol].append([quantity, gross + fee])
        else:
            if episode is None:
                raise IndependentQAError("Unmatched closed-position exit")
            episode["net_pnl_usdt"] += gross - fee
            remaining = quantity
            while remaining > EPS:
                if not inventory[symbol]:
                    raise IndependentQAError("Unmatched independent FIFO sell")
                lot = inventory[symbol][0]
                amount = min(remaining, lot[0])
                basis = lot[1] * amount / lot[0]
                pnl = (gross - fee) * amount / quantity - basis
                row["fifo_exit_net_pnl_usdt"] += pnl
                row["closed_fifo_lot_segments"] += 1
                segments += 1
                lot[0] -= amount
                lot[1] -= basis
                remaining -= amount
                if lot[0] <= EPS:
                    inventory[symbol].popleft()
        episode["fees_usdt"] += fee
        episode["slippage_usdt"] += slippage
        if fill["side"] == "sell" and abs(fill["asset_quantity_after"]) <= EPS:
            episode["exit_at_utc"] = fill["executed_at_utc"]
            closed_positions.append(episode)
            row["closed_positions"] += 1
            row["realized_position_net_pnl_usdt"] += episode["net_pnl_usdt"]
            episodes[symbol] = None
    net = tape["terminal_cash_usdt"] - tape["initial_cash_usdt"]
    totals = [sum((p["net_pnl_usdt"] for p in closed_positions), ZERO),
              sum((m["fifo_exit_net_pnl_usdt"] for m in monthly.values()), ZERO),
              sum((m["mark_to_market_net_pnl_usdt"] for m in monthly.values()), ZERO)]
    if (any(abs(value - net) > D("0.000002") for value in totals)
            or any(e is not None for e in episodes.values())
            or any(inventory[s] for s in SYMBOLS)):
        raise IndependentQAError("Independent monthly/position/FIFO totals do not reconcile")
    for row in monthly.values():
        count = row["closed_positions"]
        row["mean_net_per_closed_position_usdt"] = row["realized_position_net_pnl_usdt"] / count if count else None
    result = {"schema": SCHEMA, "independent_numerical_qa_complete": True,
              "signal_source_or_worker_lease_approval_implied": False,
              "observed_bars": len(idx), "fill_events": len(tape["fills"]),
              "closed_positions": len(closed_positions), "closed_fifo_lot_segments": segments,
              "closed_position_definition": "per-symbol flat-to-flat inventory episode; partial reductions are not new positions",
              "monthly_mark_assignment": "source_bar_open_UTC_month; mark observed at bar close",
              "net_pnl_usdt": net, "terminal_cash_usdt": tape["terminal_cash_usdt"],
              "mean_net_per_closed_position_usdt": net / len(closed_positions) if closed_positions else None,
              "fees_usdt": metrics["total_fees"], "slippage_usdt": all_slippage,
              "max_drawdown_fraction": metrics["max_drawdown"],
              "monthly": dict(sorted(monthly.items())), "closed_position_ledger": closed_positions,
              "execution_evidence": "OBSERVED_EXECUTION" if tape["fills"] else "NO_OBSERVED_EXECUTION",
              "economic_edge_established": False, "paper_eligible": False, "live_enabled": False, "orders": 0}

    def serial(value):
        if isinstance(value, D):
            return float(value)
        if isinstance(value, dict):
            return {key: serial(item) for key, item in value.items()}
        if isinstance(value, list):
            return [serial(item) for item in value]
        return value

    return serial(result)
