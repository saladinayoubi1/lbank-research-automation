"""Read-only, reconciled terminal projection of the shared owner Paper account.

No orders, credentials, balance resets or engine imports in the product reader.
Stress remains a comparison; only conservative enters the account totals.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "nexus.shared-paper-terminal.v1"
MAX_BYTES = 50_000_000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def seal(value):
    core = {k: v for k, v in value.items() if k != "digest"}
    return {**core, "digest": digest(core)}


def _close(a, b):
    return math.isclose(float(a), float(b), abs_tol=1e-7, rel_tol=1e-9)


def build_snapshot(state, activation, status):
    """Construct from one committed state, never merge independently read balances."""
    if seal(state) != state or seal(activation) != activation:
        raise ValueError("shared account digest mismatch")
    if state["activation_digest"] != activation["digest"] or activation["live_trading_authority"] is not False:
        raise ValueError("shared account binding/authority mismatch")
    positions, history, orders, cashflows, lanes = [], [], [], [], []
    balance = equity = fees = funding = gross = margin = 0.0
    for name, lane in state["lanes"].items():
        p = lane["profiles"]["conservative"]
        events = p.get("execution_journal", [])
        if sum(e["kind"] == "fill" for e in events) != p["fill_count"]:
            raise ValueError("fill history incomplete; cannot fabricate legacy fills")
        active = {}
        lane_fees = lane_funding = lane_gross = 0.0
        for e in events:
            symbol = e["symbol"]
            key = f"{name}:{e['sequence']}"
            common = {"id": key, "strategy": name, "symbol": symbol,
                      "time": e["execution_utc"], "timeframe": "4h"}
            if e["kind"] == "funding":
                lane_funding += e["amount"]
                if symbol in active:
                    active[symbol]["funding"] += e["amount"]
                cashflows.append({**common, "type": "funding", "amount": e["amount"],
                                 "time_precision": "execution_bar"})
                continue
            orders.append({**common, "status": "filled" if e["kind"] == "fill" else "rejected",
                "side": "buy" if e["quantity"] > 0 else "sell", "quantity": abs(e["quantity"]),
                "price": e["price"], "fee": e["fee"], "reason": e["reason"],
                "execution_model": e.get("execution_model"), "slippage_cost": e.get("slippage_cost"),
                "realized_gross": e.get("realized_gross")})
            if e["kind"] != "fill":
                continue
            lane_fees += e["fee"]
            lane_gross += e["realized_gross"]
            cashflows.append({**common, "type": "fee", "amount": -e["fee"]})
            if e["realized_gross"]:
                cashflows.append({**common, "type": "realized_gross", "amount": e["realized_gross"]})
            before = e["position_before"]["quantity"]
            after = e["position_after"]["quantity"]
            closing = min(abs(before), abs(e["quantity"])) if before*e["quantity"] < 0 else 0.0
            if closing:
                lot = active[symbol]
                ratio = closing/abs(before)
                entry_fee = lot["entry_fees_remaining"]*ratio
                allocated_funding = lot["funding"]*ratio
                exit_fee = e["fee"]*closing/abs(e["quantity"])
                history.append({**common, "position_id": lot["id"], "opened_at": lot["opened_at"],
                    "side": "long" if before > 0 else "short", "quantity": closing,
                    "entry_price": e["position_before"]["average_entry"], "exit_price": e["price"],
                    "gross_pnl": e["realized_gross"], "fees": entry_fee+exit_fee,
                    "funding": allocated_funding,
                    "net_pnl": e["realized_gross"]-entry_fee-exit_fee+allocated_funding,
                    "reason": e["reason"], "partial": abs(after)>1e-15 and after*before>0})
                lot["entry_fees_remaining"] -= entry_fee
                lot["funding"] -= allocated_funding
                if closing >= abs(before)-1e-15:
                    del active[symbol]
            opening = abs(e["quantity"])-closing
            if opening > 1e-15:
                if symbol not in active:
                    active[symbol] = {"id": key, "opened_at": e["execution_utc"],
                        "entry_fees_remaining": 0.0, "funding": 0.0}
                active[symbol]["entry_fees_remaining"] += e["fee"]*opening/abs(e["quantity"])
        expected = 125.0+lane_gross-lane_fees+lane_funding
        if not all((_close(expected, p["wallet"]), _close(lane_fees, p["fees"]),
                    _close(lane_funding, p["funding_cashflow"]))):
            raise ValueError("shared account cash ledger does not reconcile")
        lane_upnl = 0.0
        for i, symbol in enumerate(("BTCUSDT", "ETHUSDT")):
            pos = p["positions"][i]
            q = pos["quantity"]
            if abs(q) <= 1e-15:
                continue
            lot = active[symbol]
            mark = p["mark_prices"][i]
            upnl = q*(mark-pos["average_entry"])
            lane_upnl += upnl
            positions.append({"id": lot["id"], "strategy": name, "symbol": symbol,
                "timeframe": "4h", "side": "long" if q>0 else "short", "quantity": abs(q),
                "entry_price": pos["average_entry"], "mark_price": mark,
                "mark_time": p["mark_time_utc"], "opened_at": lot["opened_at"],
                "unrealized_pnl": upnl, "net_pnl_to_date": upnl-lot["entry_fees_remaining"]+lot["funding"],
                "entry_fees": lot["entry_fees_remaining"], "funding": lot["funding"],
                "notional": abs(q*mark), "leverage": p["account_leverage"],
                "stop_loss": None, "take_profit": None, "exit_policy": "strategy_signal",
                "protection_status": "no_fixed_price_orders", "liquidation_price": None})
        if not _close(p["wallet"]+lane_upnl, p["equity"]):
            raise ValueError("shared account position equity does not reconcile")
        balance += p["wallet"]; equity += p["equity"]; fees += lane_fees
        funding += lane_funding; gross += lane_gross; margin += p.get("initial_margin", 0.0)
        lanes.append({"strategy": name, "allocation": 125.0, "balance": p["wallet"],
            "equity": p["equity"], "net_pnl": p["equity"]-125, "fills": p["fill_count"],
            "halted": name in state["halted_lanes"]})
    for rows in (orders, history, cashflows):
        rows.sort(key=lambda e:(e["time"], e["id"]), reverse=True)
    snapshot = {"schema": SCHEMA, "available": True, "mode": "internal_paper", "read_only": True,
        "live_trading_authority": False, "currency": "USDT", "checked_at": status["checked_at"],
        "status": status["status"], "state_digest": state["digest"], "source_sha": activation["source_sha"],
        "start_not_before_utc": status["start_not_before_utc"], "last_execution_utc": state["last_execution_utc"],
        "valuation": "closed_4h_mark", "account": {"initial_balance": 500.0, "balance": balance,
            "equity": equity, "unrealized_pnl": equity-balance, "realized_gross": gross,
            "realized_net_cash": balance-500, "net_pnl": equity-500, "fees": fees,
            "funding": funding, "initial_margin": margin, "free_margin": equity-margin,
            "drawdown": state["aggregate_max_drawdown"]["conservative"]},
        "positions": positions, "history": history, "orders": orders, "cashflows": cashflows,
        "strategies": lanes, "pending_orders": [],
        "execution_disclosure": "Candle-driven simulated fills; no broker orders. Marks update on closed 4h bars.",
        "cost_disclosure": "Slippage is embedded in fill prices; do not subtract it twice. Net open PnL excludes future exit costs."}
    return seal(snapshot)


def load_snapshot(data_root: Path, *, now=None):
    path = data_root/"shared_paper"/"terminal.json"
    unavailable = {"available": False, "status": "unavailable", "live_trading_authority": False,
                   "positions": [], "history": [], "orders": [], "cashflows": []}
    try:
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            return {**unavailable, "reason": "snapshot_missing_or_unsafe"}
        s = json.loads(path.read_text("utf-8"))
        if (seal(s) != s or s.get("schema") != SCHEMA or s.get("live_trading_authority") is not False
                or s.get("mode") != "internal_paper" or s.get("read_only") is not True):
            raise ValueError("invalid snapshot")
        current = now or datetime.now(timezone.utc)
        age = (current-datetime.fromisoformat(s["checked_at"].replace("Z", "+00:00"))).total_seconds()
        return {**s, "stale": age > 180 or age < -60, "age_seconds": max(age, 0)}
    except (OSError, ValueError, TypeError, KeyError):
        return {**unavailable, "reason": "snapshot_invalid"}


def export_csv(snapshot, table="history"):
    if table not in ("history", "orders", "cashflows", "positions"):
        raise ValueError("unknown export table")
    rows = snapshot.get(table, [])
    fields = list(dict.fromkeys(k for r in rows for k in r)) or ["id", "strategy", "symbol", "time"]
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("'"+v if isinstance(v, str) and v[:1] in "=+-@\t\r" else v) for k,v in row.items()})
    return out.getvalue().encode("utf-8-sig")


def with_public_marks(snapshot, client, now):
    """Public mark-to-market display only; never feeds signals, execution or risk.

Bybit contract: https://bybit-exchange.github.io/docs/v5/market/tickers
All symbols must have fresh validated marks or the complete booked view remains.
"""
    from copy import deepcopy
    result=deepcopy(snapshot)
    if not snapshot['positions']:
        result['quote_status']='not_needed_flat'
        return seal(result)
    try:
        quotes={}
        for symbol in sorted({p['symbol'] for p in snapshot['positions']}):
            payload=client.get('/v5/market/tickers',{'category':'linear','symbol':symbol})
            quote_time=datetime.fromtimestamp(float(payload['time'])/1000,timezone.utc)
            age=(now-quote_time).total_seconds()
            rows=payload['result']['list']
            if not (-10 <= age <= 120) or payload['result']['category']!='linear' or len(rows)!=1 or rows[0]['symbol']!=symbol:
                raise ValueError('stale or mismatched public quote')
            mark=float(rows[0]['markPrice'])
            if not math.isfinite(mark) or mark<=0: raise ValueError('invalid public mark')
            quotes[symbol]=(mark,quote_time.isoformat())
        result['booked_account']=deepcopy(snapshot['account'])
        for p in result['positions']:
            p['booked_mark_price']=p['mark_price'];p['booked_mark_time']=p['mark_time']
            p['mark_price'],p['mark_time']=quotes[p['symbol']]
            p['notional']=p['quantity']*p['mark_price']
            p['unrealized_pnl']=(1 if p['side']=='long' else -1)*p['quantity']*(p['mark_price']-p['entry_price'])
            p['net_pnl_to_date']=p['unrealized_pnl']-p['entry_fees']+p['funding']
        a=result['account']
        a['unrealized_pnl']=sum(p['unrealized_pnl'] for p in result['positions'])
        a['equity']=a['balance']+a['unrealized_pnl'];a['net_pnl']=a['equity']-500
        # Exact live margin would require fresh risk tiers; do not approximate it.
        a['initial_margin']=None;a['free_margin']=None
        for lane in result['strategies']:
            lane['equity']=lane['balance']+sum(p['unrealized_pnl'] for p in result['positions'] if p['strategy']==lane['strategy'])
            lane['net_pnl']=lane['equity']-lane['allocation']
        result['valuation']='public_mark_snapshot';result['quote_status']='fresh'
    except Exception:
        result=deepcopy(snapshot);result['quote_status']='unavailable_using_closed_bar'
    return seal(result)
