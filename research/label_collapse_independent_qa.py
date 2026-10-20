"""Independent Decimal QA for the frozen label-collapse v1 study."""
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 60
D = lambda x: Decimal(str(x))
ZERO, ONE, STEP = D(0), D(1), 14_400_000
SYMS = ("BTCUSDT", "ETHUSDT")
PROFILES = {"conservative": (10, 5), "stress": (15, 10), "severe": (25, 15)}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def number(x):
    require(not isinstance(x, bool), "Boolean numeric value")
    y = D(x)
    require(y.is_finite(), "Nonfinite value")
    return y


def compare(actual, expected, path="result"):
    if isinstance(expected, dict):
        require(isinstance(actual, dict), path + ": not an object")
        if path.endswith(".monthly_pnl_usdt"):
            require(set(actual) == set(expected), path + ": month set")
        for k, v in expected.items():
            require(k in actual, path + ": missing " + k)
            compare(actual[k], v, path + "." + k)
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), path + ": list length")
        for i, (a, e) in enumerate(zip(actual, expected)):
            compare(a, e, path + "[" + str(i) + "]")
    elif isinstance(expected, Decimal):
        a = number(actual)
        tight = path.endswith((".quantity", ".max_close_drawdown_fraction"))
        tolerance = (D("2e-12") if tight else D("2e-7")) + abs(expected) * D("1e-11")
        require(abs(a - expected) <= tolerance, path + ": numeric mismatch")
    elif isinstance(expected, bool):
        require(type(actual) is bool and actual is expected, path + ": boolean mismatch")
    elif isinstance(expected, int):
        require(type(actual) is int and actual == expected, path + ": integer mismatch")
    else:
        require(actual == expected, path + ": value mismatch")


def prepare(features, contract):
    require(contract["candidate_id"] == "label_collapse_reclaim_4h_v1", "Contract identity")
    compare(contract["signal"]["constants"], {
        "event_min_abs_imbalance": D(".20"), "response_max_abs_imbalance": D(".05"),
        "min_stop_distance_fraction": D(".01"), "max_stop_distance_fraction": D(".04"),
        "target_R": 2, "holding_bars": 6}, "contract.signal")
    ex = contract["execution"]
    compare(ex, {"initial_cash_usdt": 500, "max_entry_gross_usdt": 250,
                 "stop_budget_including_entry_exit_costs_usdt": D("2.5"),
                 "max_positions": 1}, "contract.execution")
    require(set(ex["cost_profiles"]) == set(PROFILES), "Cost profile set")
    for name, (fee, slip) in PROFILES.items():
        compare(ex["cost_profiles"][name], {"fee_bps": fee, "slippage_bps": slip})
    scope = contract["scope"]
    require(scope["start_inclusive_utc"] == "2026-08-01T00:00:00Z" and
            scope["end_exclusive_utc"] == "2026-10-19T00:00:00Z", "Scope changed")
    start = int(datetime.fromisoformat(scope["start_inclusive_utc"].replace("Z", "+00:00"))
                .timestamp() * 1000)
    require(set(features["bars"]) == set(SYMS), "Symbol set")
    bars = {}
    for s in SYMS:
        rows = features["bars"][s]
        require(len(rows) == 474, s + ": expected 474 bars")
        bars[s] = []
        for j, raw in enumerate(rows):
            b = dict(raw)
            require(type(b["timestamp"]) is int and b["timestamp"] == start + j * STEP,
                    s + ": time grid")
            require(type(b["first_trade_ms"]) is int and type(b["last_trade_ms"]) is int and
                    b["timestamp"] <= b["first_trade_ms"] <= b["last_trade_ms"] <
                    b["timestamp"] + STEP, s + ": trade timestamps")
            require(type(b["trades"]) is int and b["trades"] > 0, s + ": trade count")
            h = b["source_raw_sha256"]
            require(isinstance(h, str) and len(h) == 64 and
                    all(c in "0123456789abcdef" for c in h), s + ": raw digest")
            for k in ("open", "high", "low", "close", "volume"):
                b[k] = number(b[k])
                require(b[k] > 0, s + ": nonpositive " + k)
            require(b["low"] <= min(b["open"], b["close"]) <=
                    max(b["open"], b["close"]) <= b["high"], s + ": OHLC bounds")
            buy, sell = number(b["buy_quote_decimal"]), number(b["sell_quote_decimal"])
            require(buy >= 0 and sell >= 0 and buy + sell > 0, s + ": quote sums")
            for k, exact in (("buy_quote", buy), ("sell_quote", sell)):
                require(abs(number(b[k]) - exact) <= D("1e-7") + abs(exact) * D("1e-10"),
                        s + ": float/exact quote mismatch")
            b["I"] = abs(buy - sell) / (buy + sell)
            require(abs(number(b["imbalance"]) - b["I"]) <= D("2e-12"),
                    s + ": imbalance mismatch")
            bars[s].append(b)
    return bars


def monthly(marks):
    out, previous = {}, D(500)
    for mark in marks:
        month = datetime.fromtimestamp((mark["timestamp"] - 1) / 1000,
                                       timezone.utc).strftime("%Y-%m")
        out[month] = out.get(month, ZERO) + mark["equity"] - previous
        previous = mark["equity"]
    return out


class Ledger:
    def __init__(self, bars, fee_bps, slip_bps):
        self.bars, self.fee, self.slip = bars, D(fee_bps) / 10000, D(slip_bps) / 10000
        self.cash, self.fees, self.peak, self.dd = D(500), ZERO, D(500), ZERO
        self.positions, self.fills, self.trades, self.marks = {}, [], [], []

    def buy(self, s, j, quantity):
        b, q = self.bars[s][j], quantity
        price = b["open"] * (ONE + self.slip)
        fee = q * price * self.fee
        self.cash -= q * price + fee
        require(self.cash >= D("-1e-40") and q > 0, "Borrowing/invalid quantity")
        self.fees += fee
        self.positions[s] = {"entry_index": j, "entry_price": price,
                             "quantity": q, "entry_fee": fee}
        self.fills.append(dict(bar_index=j, symbol=s, side="buy", reason="entry",
                               reference_price=b["open"], fill_price=price, quantity=q,
                               fee=fee, cash_after=self.cash, decision_time_ms=b["timestamp"],
                               execution_time_ms=b["first_trade_ms"]))

    def sell(self, s, j, reference, reason):
        b, p = self.bars[s][j], self.positions.pop(s)
        price, q = reference * (ONE - self.slip), p["quantity"]
        fee = q * price * self.fee
        self.cash += q * price - fee
        self.fees += fee
        intrabar, terminal = reason in ("stop", "target"), reason == "terminal"
        execution = None if intrabar else b["last_trade_ms"] if terminal else b["first_trade_ms"]
        decision = b["last_trade_ms"] if terminal else b["timestamp"]
        fill = dict(bar_index=j, symbol=s, side="sell", reason=reason,
                    reference_price=reference, fill_price=price, quantity=q, fee=fee,
                    cash_after=self.cash, decision_time_ms=decision, execution_time_ms=execution)
        if intrabar or terminal:
            fill["time_precision"] = "4h_interval" if intrabar else "last_trade"
        self.fills.append(fill)
        self.trades.append(dict(entry_index=p["entry_index"], exit_index=j, symbol=s,
                                entry_price=p["entry_price"], exit_price=price, quantity=q,
                                entry_fee=p["entry_fee"], exit_fee=fee,
                                net_pnl_usdt=q * (price - p["entry_price"]) - p["entry_fee"] - fee,
                                reason=reason))

    def mark(self, j, passive=False):
        equity = self.cash + sum((p["quantity"] * self.bars[s][j]["close"]
                                  for s, p in self.positions.items()), ZERO)
        self.peak = max(self.peak, equity)
        self.dd = max(self.dd, (self.peak - equity) / self.peak)
        mark = dict(bar_index=j, timestamp=self.bars[SYMS[0]][j]["timestamp"] + STEP,
                    cash=self.cash, equity=equity)
        if not passive:
            s = next(iter(self.positions), None)
            mark.update(symbol=s, quantity=self.positions[s]["quantity"] if s else ZERO)
        self.marks.append(mark)

    def report(self):
        require(not self.positions, "Unliquidated terminal position")
        return dict(cash=self.cash, net_pnl_usdt=self.cash - 500, fees_usdt=self.fees,
                    max_close_drawdown_fraction=self.dd, closed_trades=len(self.trades),
                    fills=self.fills, trades=self.trades, marks=self.marks,
                    monthly_pnl_usdt=monthly(self.marks))


def active(bars, fee, slip, flow):
    book = Ledger(bars, fee, slip)
    for j in range(474):
        held_at_open = bool(book.positions)
        if held_at_open:
            s = next(iter(book.positions))
            p, b = book.positions[s], bars[s][j]
            if b["open"] <= p["S"]:
                book.sell(s, j, b["open"], "stop_gap")
            elif b["open"] >= p["T"]:
                book.sell(s, j, p["T"], "target_gap")
            elif j >= p["entry_index"] + 6:
                book.sell(s, j, b["open"], "time")
        elif j >= 2:
            for s in SYMS:
                e, t, b = bars[s][j - 2], bars[s][j - 1], bars[s][j]
                signal = e["close"] < e["open"] and t["close"] > e["high"]
                signal = signal and (not flow or (e["I"] >= D(".20") and t["I"] <= D(".05")))
                if not signal:
                    continue
                E, S = b["open"] * (ONE + book.slip), min(e["low"], t["low"])
                if not D(".01") <= (E - S) / E <= D(".04"):
                    continue
                unit_risk = E * (ONE + book.fee) - S * (ONE - book.slip) * (ONE - book.fee)
                q = min(D(250) / E, D("2.5") / unit_risk, book.cash / (E * (ONE + book.fee)))
                book.buy(s, j, q)
                book.positions[s].update(S=S, T=E + 2 * (E - S))
                break
        if book.positions:
            s = next(iter(book.positions))
            p, b = book.positions[s], bars[s][j]
            if b["low"] <= p["S"]:
                book.sell(s, j, p["S"], "stop")
            elif b["high"] >= p["T"]:
                book.sell(s, j, p["T"], "target")
        if j == 473 and book.positions:
            s = next(iter(book.positions))
            book.sell(s, j, bars[s][j]["close"], "terminal")
        book.mark(j)
    return book.report()


def passive(bars, fee, slip, name):
    book = Ledger(bars, fee, slip)
    symbols = (name,) if name in SYMS else SYMS if name != "cash" else ()
    for s in symbols:
        E = bars[s][0]["open"] * (ONE + book.slip)
        q = (D(125) / E if name == "capped_50_50" else
             (D(500) if len(symbols) == 1 else D(250)) / (E * (ONE + book.fee)))
        book.buy(s, 0, q)
    for j in range(474):
        if j == 473:
            for s in symbols:
                book.sell(s, j, bars[s][j]["close"], "terminal")
        book.mark(j, passive=True)
    report = book.report()
    return {k: report[k] for k in ("cash", "net_pnl_usdt", "fees_usdt",
            "max_close_drawdown_fraction", "marks", "monthly_pnl_usdt")}


def verify(features, result, contract):
    bars = prepare(features, contract)
    expected = {"books": {"candidate": {}, "price_only": {}}, "passive": {}}
    require(set(result["books"]) == {"candidate", "price_only"}, "Book set")
    for name, (fee, slip) in PROFILES.items():
        expected["books"]["candidate"][name] = active(bars, fee, slip, True)
        expected["books"]["price_only"][name] = active(bars, fee, slip, False)
        expected["passive"][name] = {k: passive(bars, fee, slip, k)
                                    for k in (*SYMS, "full_50_50", "capped_50_50", "cash")}
        require(set(result["passive"][name]) == set(expected["passive"][name]), "Passive set")
    for name in expected["books"]:
        require(set(result["books"][name]) == set(PROFILES), "Book cost set")
    require(set(result["passive"]) == set(PROFILES), "Passive cost set")
    c, p = expected["books"]["candidate"], expected["books"]["price_only"]["stress"]
    b = expected["passive"]["stress"]["capped_50_50"]
    gates = {
        "all_three_costs_positive": all(r["net_pnl_usdt"] > 0 for r in c.values()),
        "stress_beats_no_flow": c["stress"]["net_pnl_usdt"] > p["net_pnl_usdt"],
        "stress_beats_capped_passive": c["stress"]["net_pnl_usdt"] > b["net_pnl_usdt"],
        "stress_dd_no_worse_capped_passive":
            c["stress"]["max_close_drawdown_fraction"] <= b["max_close_drawdown_fraction"],
    }
    passed = all(gates.values())
    expected.update(decision_gates=gates, exploratory_pass=passed,
                    outcome="exploratory_lead_only" if passed else "terminal_negative_no_retune",
                    paper_eligible=False, live_enabled=False, orders=0)
    compare(result, expected)
    return {"schema": "nexus.label-collapse-independent-decimal-qa.v1", "verified": True,
            "bars_checked": 948, "reports_checked": 21, "decision_gates": gates,
            "exploratory_pass": passed, "outcome": expected["outcome"],
            "paper_eligible": False, "live_enabled": False, "orders": 0}


if __name__ == "__main__":
    contract, features, result = [json.loads(Path(p).read_text(encoding="utf-8-sig"))
                                  for p in sys.argv[1:4]]
    receipt = verify(features, result, contract)
    Path(sys.argv[4]).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt))
