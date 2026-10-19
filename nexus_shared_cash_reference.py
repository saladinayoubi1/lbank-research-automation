"""Independent stdlib/Decimal oracle for the fixed prior-range shared cash book.

Accepts numerical witnesses and captured masks, never calls the production
engine, feature builder, signal generator or broker. Source authenticity still
requires the existing independent QA replay against canonical Bybit inputs.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR, localcontext
import math

SYMBOLS = ("BTCUSDT", "ETHUSDT")
PROFILES = {"conservative": (10, 5), "stress": (25, 15)}
PARTITIONS = ("training", "validation_already_inspected", "historical_test_already_inspected")
STEP = 900_000
COLUMNS = ("symbol", "entry_open_ms", "exit_event_ms", "exit_bar_close_ms", "exit_reason",
           "qty", "entry_mid", "exit_mid", "entry_fill", "exit_fill", "entry_fee_usdt",
           "exit_fee_usdt", "slippage_usdt", "gross_price_pnl_usdt", "total_friction_usdt",
           "exit_clock", "stop", "target", "pnl_usdt")
FIELDS = ("ending_shared_cash_usdt", "net_pnl_usdt", "max_drawdown_pct", "trades", "positive_trades",
          "mean_pnl_usdt", "fees_paid_usdt", "gross_price_pnl_usdt", "slippage_usdt",
          "total_friction_usdt", "signals_due_at_next_open", "denial_reasons", "attempt_counts",
          "exit_reasons", "monthly", "ledger")


class SharedCashReferenceError(ValueError):
    pass


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise SharedCashReferenceError("nonfinite shared cash input")
    return Decimal(str(value))


def validate_inputs(inputs, captures):
    if type(inputs) is not dict or set(inputs) != set(SYMBOLS):
        raise SharedCashReferenceError("complete shared book inputs required")
    grids = [captures[s]["decision_grid"] for s in SYMBOLS]
    if grids[0] != grids[1]:
        raise SharedCashReferenceError("shared book grids differ")
    n = grids[0]["rows"]
    if type(n) is not int or n < 10 or n > 3072:
        raise SharedCashReferenceError("shared book window outside reviewed bounds")
    for s in SYMBOLS:
        rows = inputs[s]
        if type(rows) is not list or len(rows) != n:
            raise SharedCashReferenceError("unaligned physical input table")
        for row in rows:
            if type(row) is not list or len(row) != 5:
                raise SharedCashReferenceError("invalid physical input row")
            op, hi, lo, cl = map(number, row[:4])
            if not 0 < lo <= min(op, cl) <= max(op, cl) <= hi:
                raise SharedCashReferenceError("nonphysical shared cash OHLC")
            if row[4] is not None:
                number(row[4])
        if len(captures[s]["signal_mask"]) != n:
            raise SharedCashReferenceError("unaligned captured mask")
    return n


def partition(inputs, captures, lo, hi, profile):
    """Independent position, accounting and event-clock state machine."""
    with localcontext() as ctx:
        ctx.prec = 40
        fee_bps, slip_bps = PROFILES[profile]
        fee, slip = Decimal(fee_bps) / 10000, Decimal(slip_bps) / 10000
        cash = peak = Decimal(500)
        drawdown = Decimal(0)
        position = None
        attempts, denials = Counter(), Counter()
        ledger, seen = [], 0
        fees = Decimal(0)
        first_close = captures[SYMBOLS[0]]["decision_grid"]["first_close_ms"]
        for i in range(lo, hi):
            due = [s for s in SYMBOLS if i > lo and captures[s]["signal_mask"][i-1] == "1"]
            seen += len(due)
            # Orders are resolved before an existing lot can exit at this open.
            if position is not None:
                denials["SHARED_CASH_POSITION_OCCUPIED"] += len(due)
                if not due and denials["SHARED_CASH_POSITION_OCCUPIED"] == 0:
                    del denials["SHARED_CASH_POSITION_OCCUPIED"]
            elif due:
                for s in due:
                    attempts["next_open_intent"] += 1
                    prior = inputs[s][i-1][4]
                    if prior is None or number(prior) <= 0:
                        denials["UNAVAILABLE_PRIOR_ATR"] += 1
                        continue
                    mid = number(inputs[s][i][0])
                    fill = mid * (1 + slip)
                    stop = fill - Decimal("1.5") * number(prior)
                    target = fill + 2 * (fill-stop)
                    if not 0 < stop < fill < target:
                        denials["INVALID_ATR_STOP_GEOMETRY"] += 1
                        continue
                    unit_spend = fill * (1 + fee)
                    risk = unit_spend - stop * (1-slip) * (1-fee)
                    qty = (min(250/fill, Decimal("2.5")/risk, cash/unit_spend)
                           * 100_000_000).to_integral_value(rounding=ROUND_FLOOR) / 100_000_000
                    if qty <= 0:
                        denials["NO_SHARED_CASH_OR_RISK_CAPACITY"] += 1
                        continue
                    entry_fee = qty*fill*fee
                    spent = qty*unit_spend
                    if spent > cash or qty*fill > 250 or qty*risk > Decimal("2.5"):
                        raise SharedCashReferenceError("independent shared cash capacity overrun")
                    cash -= spent
                    fees += entry_fee
                    position = dict(symbol=s, index=i, mid=mid, fill=fill, fee=entry_fee,
                                    spent=spent, qty=qty, stop=stop, target=target)
                    attempts["admitted"] += 1
                    break
                if position is not None and len(due) > 1:
                    denials["SAME_OPEN_LOWER_PRIORITY_PEER"] += len(due)-due.index(position["symbol"])-1
            if position is not None:
                p = position
                op, high, low, close = map(number, inputs[p["symbol"]][i][:4])
                reason, level = None, None
                if op <= p["stop"]:
                    reason, level = "STOP_GAP_AT_WORSE_OPEN", op
                elif i-p["index"] >= 64:
                    reason, level = "TIMEOUT_AT_PHYSICAL_NEXT_OPEN", op
                elif low <= p["stop"]:
                    reason = "STOP_FIRST_INTRABAR_BOTH" if high >= p["target"] else "STRUCTURAL_STOP"
                    level = p["stop"]
                elif high >= p["target"]:
                    reason, level = "PRECOMMITTED_TARGET", p["target"]
                elif i == hi-1:
                    reason, level = "PARTITION_LAST_COMPLETED_CLOSE", close
                if reason is not None:
                    sell = level*(1-slip)
                    exit_fee = p["qty"]*sell*fee
                    pnl = p["qty"]*sell-exit_fee-p["spent"]
                    cash += p["qty"]*sell-exit_fee
                    fees += exit_fee
                    gross = p["qty"]*(level-p["mid"])
                    slippage = p["qty"]*((p["fill"]-p["mid"])+(level-sell))
                    friction = slippage+p["fee"]+exit_fee
                    if abs(gross-friction-pnl) > Decimal("1e-25"):
                        raise SharedCashReferenceError("independent gross/cost/net mismatch")
                    at = first_close+i*STEP
                    legacy_open = reason in {"STOP_GAP_AT_WORSE_OPEN", "TIMEOUT_AT_PHYSICAL_NEXT_OPEN"}
                    row = dict(symbol=p["symbol"], entry_open_ms=first_close+(p["index"]-1)*STEP,
                               exit_event_ms=at, exit_bar_close_ms=at, exit_reason=reason,
                               qty=p["qty"], entry_mid=p["mid"], exit_mid=level,
                               entry_fill=p["fill"], exit_fill=sell, entry_fee_usdt=p["fee"],
                               exit_fee_usdt=exit_fee, slippage_usdt=slippage,
                               gross_price_pnl_usdt=gross, total_friction_usdt=friction,
                               exit_clock="open_execution_recorded_at_legacy_bar_close" if legacy_open
                                          else "bounded_to_completed_15m_bar",
                               stop=p["stop"], target=p["target"], pnl_usdt=pnl)
                    ledger.append({k: float(round(v, 8)) if isinstance(v, Decimal) else v for k,v in row.items()})
                    position = None
            equity = cash if position is None else cash+position["qty"]*number(inputs[position["symbol"]][i][3])
            peak = max(peak, equity)
            drawdown = max(drawdown, 1-equity/peak)
            if cash < 0:
                raise SharedCashReferenceError("negative independent shared cash")
        if position is not None:
            raise SharedCashReferenceError("unclosed independent lot")
        months = defaultdict(list)
        for row in ledger:
            month = datetime.fromtimestamp(row["exit_event_ms"]/1000, timezone.utc).strftime("%Y-%m")
            months[month].append(Decimal(str(row["pnl_usdt"])))
        net = cash-500
        result = dict(ending_shared_cash_usdt=cash, net_pnl_usdt=net,
                      max_drawdown_pct=100*drawdown, trades=len(ledger),
                      positive_trades=sum(r["pnl_usdt"] > 0 for r in ledger),
                      mean_pnl_usdt=net/len(ledger) if ledger else None,
                      fees_paid_usdt=fees, signals_due_at_next_open=seen,
                      denial_reasons=dict(sorted(denials.items())), attempt_counts=dict(sorted(attempts.items())),
                      exit_reasons=dict(sorted(Counter(r["exit_reason"] for r in ledger).items())), ledger=ledger,
                      monthly=[dict(month=m, round_trips=len(v), net_pnl_usdt=float(round(sum(v),8)),
                                    mean_pnl_usdt=float(round(sum(v)/len(v),8))) for m,v in sorted(months.items())])
        for key in ("gross_price_pnl_usdt", "slippage_usdt", "total_friction_usdt"):
            result[key] = sum(Decimal(str(r[key])) for r in ledger)
        return {k: float(round(v,8)) if isinstance(v, Decimal) else v for k,v in result.items()}


def compare(observed, expected, path="book"):
    """Rounding tolerances only; quantities and counts cannot conceal resizing."""
    if type(expected) is dict:
        if type(observed) is not dict or set(observed) != set(expected):
            raise SharedCashReferenceError(f"shared cash fields disagree: {path}")
        for key in expected:
            compare(observed[key], expected[key], path+"."+key)
    elif type(expected) is list:
        if type(observed) is not list or len(observed) != len(expected):
            raise SharedCashReferenceError(f"shared cash coverage disagrees: {path}")
        for a,b in zip(observed,expected):
            compare(a,b,path)
    elif type(expected) is float:
        tolerance = Decimal("0.000000011") if path.endswith(".qty") else Decimal("0.000001")
        actual, target = number(observed), number(expected)
        # Rounding tolerance must never turn a loss/zero into a positive gate.
        if path.endswith(".net_pnl_usdt") and ((actual > 0)-(actual < 0)) != ((target > 0)-(target < 0)):
            raise SharedCashReferenceError(f"shared cash net sign disagrees: {path}")
        if abs(actual-target) > tolerance:
            raise SharedCashReferenceError(f"independent shared cash arithmetic disagrees: {path}")
    elif type(observed) is not type(expected) or observed != expected:
        raise SharedCashReferenceError(f"shared cash evidence disagrees: {path}")
