"""Frozen BTCUSDT 4h mean reversion research replay; no trading or promotion API."""
from __future__ import annotations
import hashlib,json,math,statistics
from datetime import datetime,timezone
from decimal import Decimal,localcontext
STEP=14_400_000
CAPITAL=10_000.0
PARAMS={"lookback":40,"entry_z":-2.0,"exit_z":0.0}
def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def digest(value): return hashlib.sha256(canonical(value)).hexdigest()
def iso(stamp): return datetime.fromtimestamp(stamp/1000,timezone.utc).isoformat()
def ms(text): return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()*1000)
def validate_frame(rows):
    previous=None
    for row in rows:
        if len(row)!=6 or isinstance(row[0],bool) or not isinstance(row[0],int) or row[0]%STEP: raise ValueError("invalid bar identity")
        if previous is not None and row[0]-previous!=STEP: raise ValueError("non-contiguous bars")
        previous=row[0]
        op,hi,lo,cl,vol=map(float,row[1:])
        if not all(map(math.isfinite,(op,hi,lo,cl,vol))) or min(op,hi,lo,cl)<=0 or vol<0: raise ValueError("invalid OHLCV")
        if hi<max(op,lo,cl) or lo>min(op,hi,cl): raise ValueError("invalid OHLC envelope")
    if not rows: raise ValueError("empty price history")
def targets(rows):
    close=[float(row[4]) for row in rows];state=0;out=[]
    for i,value in enumerate(close):
        if i>=40:
            past=close[i-40:i];mean=math.fsum(past)/40;std=statistics.pstdev(past)
            if std:
                z=(value-mean)/std
                if z<=-2: state=1
                elif z>=0: state=0
        out.append(state)
    return out
def decimal_targets(rows):
    with localcontext() as ctx:
        ctx.prec=40
        close=[Decimal(str(row[4])) for row in rows];state=0;out=[]
        for i,value in enumerate(close):
            if i>=40:
                past=close[i-40:i];mean=sum(past)/40
                var=sum((v-mean)**2 for v in past)/40
                if var:
                    z=(value-mean)/var.sqrt()
                    if z<=-2: state=1
                    elif z>=0: state=0
            out.append(state)
        return out
def drawdown(equity):
    peak=CAPITAL;worst=0.0
    for value in equity:
        peak=max(peak,value);worst=max(worst,1-value/peak)
    return worst*100
def monthly_attribution(curve):
    months={};previous=CAPITAL
    for row in curve:
        month=iso(row["bar_open_ms"])[:7]
        if month not in months: months[month]={"month":month,"start_equity":previous}
        months[month]["end_equity"]=row["equity"]
        previous=row["equity"]
    return [{**v,"pnl_usdt":v["end_equity"]-v["start_equity"],
             "return_pct":100*(v["end_equity"]/v["start_equity"]-1)} for v in months.values()]
def simulate(rows,signal,start,end,fee_bps,slippage_bps,*,lag=1,skip_first=False,liquidate=True):
    if not (0<=start<end<=len(rows)) or len(signal)!=len(rows) or lag not in (1,2): raise ValueError("invalid evaluation window")
    if any(s not in (0,1) for s in signal): raise ValueError("non-binary target")
    if min(fee_bps,slippage_bps)<0 or max(fee_bps,slippage_bps)>=10000: raise ValueError("invalid execution costs")
    fee=fee_bps/10000;slip=slippage_bps/10000
    cash=CAPITAL;quantity=0.0;entry=None;fills=[];trades=[];curve=[];peak=CAPITAL;low_dd=0.0;exposure=0
    def fill(i,side,reference,reason,signal_index):
        nonlocal cash,quantity,entry
        before=cash;before_qty=quantity;price=reference*(1+slip if side=="buy" else 1-slip)
        if side=="buy":
            notional=cash/(1+fee);quantity=notional/price;commission=notional*fee;cash=0.0
            entry={"entry_ms":rows[i][0],"entry_cash":before,"entry_index":i}
            traded=quantity
        else:
            traded=quantity;notional=quantity*price;commission=notional*fee;cash+=notional-commission;quantity=0.0
        stamp=rows[i][0]+(STEP if reason=="terminal_close" else 0)
        event={"bar_index":i,"fill_ms":stamp,"side":side,"reason":reason,"signal_index":signal_index,
            "signal_available_ms":None if signal_index is None else rows[signal_index][0]+STEP,
            "reference":reference,"price":price,"quantity":traded,"notional":notional,"fee_usdt":commission,
            "slippage_usdt":abs(traded*(price-reference)),"cash_before":before,"cash_after":cash,
            "asset_before":before_qty,"asset_after":quantity}
        if signal_index is not None and event["signal_available_ms"]>stamp: raise AssertionError("future signal execution")
        if abs(before-cash-(notional+commission if side=="buy" else -notional+commission))>1e-7: raise AssertionError("cash conservation")
        fills.append(event)
        if side=="sell":
            if entry is None: raise AssertionError("orphan exit")
            pnl=cash-entry["entry_cash"]
            trades.append({**entry,"exit_ms":stamp,"exit_index":i,"exit_cash":cash,"net_pnl_usdt":pnl,
                "return_pct":100*pnl/entry["entry_cash"],"holding_hours":(stamp-entry["entry_ms"])/3_600_000,
                "exit_reason":reason})
            entry=None
    for i in range(start,end):
        j=i-lag
        if j>=0 and (i>start or not skip_first):
            if signal[j]==1 and quantity==0: fill(i,"buy",float(rows[i][1]),"previous_closed_bar_signal",j)
            elif signal[j]==0 and quantity>0: fill(i,"sell",float(rows[i][1]),"previous_closed_bar_signal",j)
        low_equity=cash+quantity*float(rows[i][3]);value=cash+quantity*float(rows[i][4])
        low_dd=max(low_dd,1-low_equity/peak);peak=max(peak,value)
        in_market=quantity>0;exposure+=int(in_market)
        curve.append({"bar_open_ms":rows[i][0],"equity":value,"in_market":in_market})
    pre_terminal=curve[-1]["equity"];terminal_qty=quantity
    if quantity and liquidate:
        fill(end-1,"sell",float(rows[end-1][4]),"terminal_close",None);curve[-1]["equity"]=cash
    equity=[x["equity"] for x in curve]
    if not all(math.isfinite(x) and x>0 for x in equity): raise ValueError("invalid equity")
    if quantity==0 and abs(sum(t["net_pnl_usdt"] for t in trades)-(equity[-1]-CAPITAL))>1e-7: raise AssertionError("trade PnL reconciliation")
    gains=sum(max(0,t["net_pnl_usdt"]) for t in trades);losses=-sum(min(0,t["net_pnl_usdt"]) for t in trades)
    monthly=monthly_attribution(curve);previous=CAPITAL;returns=[]
    for value in equity: returns.append(value/previous-1);previous=value
    std=statistics.pstdev(returns) if returns else 0
    metrics={"start_utc":iso(rows[start][0]),"end_exclusive_utc":iso(rows[end-1][0]+STEP),"bars":end-start,
        "days":(end-start)/6,"initial_usdt":CAPITAL,"final_usdt":equity[-1],"net_pnl_usdt":equity[-1]-CAPITAL,
        "net_return_pct":100*(equity[-1]/CAPITAL-1),"max_close_drawdown_pct":drawdown(equity),
        "low_vs_prior_close_peak_drawdown_lower_bound_pct":max(drawdown(equity),100*low_dd),
        "fills":len(fills),"closed_positions":len(trades),"natural_exits":sum(t["exit_reason"]!="terminal_close" for t in trades),
        "terminal_exits":sum(t["exit_reason"]=="terminal_close" for t in trades),
        "wins":sum(t["net_pnl_usdt"]>0 for t in trades),"losses":sum(t["net_pnl_usdt"]<0 for t in trades),
        "win_rate_pct":None if not trades else 100*sum(t["net_pnl_usdt"]>0 for t in trades)/len(trades),
        "profit_factor_net_closed_positions":gains/losses if losses else None,
        "average_closed_position_pnl_usdt":statistics.mean(t["net_pnl_usdt"] for t in trades) if trades else None,
        "best_position_pnl_usdt":max((t["net_pnl_usdt"] for t in trades),default=None),
        "worst_position_pnl_usdt":min((t["net_pnl_usdt"] for t in trades),default=None),
        "fees_usdt":sum(f["fee_usdt"] for f in fills),"nominal_slippage_usdt":sum(f["slippage_usdt"] for f in fills),
        "exposure_pct":100*exposure/(end-start),"pre_terminal_mark_equity":pre_terminal,
        "terminal_quantity_before_close":terminal_qty,"bar_sharpe_365_25_days":statistics.mean(returns)/std*math.sqrt(365.25*6) if std else None,
        "monthly_periods":len(monthly),"positive_months":sum(x["pnl_usdt"]>0 for x in monthly),
        "negative_months":sum(x["pnl_usdt"]<0 for x in monthly)}
    return {"metrics":metrics,"fills":fills,"positions":trades,"equity_curve":curve,"monthly_attribution":monthly}
def independent_accounting(rows,independent_signal,start,end,fee_bps,slippage_bps,*,lag=1,skip_first=False):
    with localcontext() as ctx:
        ctx.prec=40
        d=Decimal;f=d(str(fee_bps))/10000;s=d(str(slippage_bps))/10000
        cash=d(10000);units=d(0);count=0;marks=[]
        for i in range(start,end):
            desired=independent_signal[i-lag] if i-lag>=0 else 0
            if not (skip_first and i==start):
                if desired and units==0:
                    units=cash/((1+f)*(d(str(rows[i][1]))*(1+s)));cash=d(0);count+=1
                elif not desired and units:
                    cash=units*d(str(rows[i][1]))*(1-s)*(1-f);units=d(0);count+=1
            marks.append(cash+units*d(str(rows[i][4])))
        if units:
            cash=units*d(str(rows[end-1][4]))*(1-s)*(1-f);marks[-1]=cash;count+=1
        return {"equity":[float(x) for x in marks],"fill_count":count,"final_usdt":float(marks[-1])}
def benchmark(rows,start,end,fee_bps,slippage_bps):
    fee=fee_bps/10000;slip=slippage_bps/10000
    quantity=CAPITAL/((1+fee)*float(rows[start][1])*(1+slip))
    curve=[quantity*float(row[4]) for row in rows[start:end]]
    curve[-1]=quantity*float(rows[end-1][4])*(1-slip)*(1-fee)
    return {"net_pnl_usdt":curve[-1]-CAPITAL,"net_return_pct":100*(curve[-1]/CAPITAL-1),
            "max_close_drawdown_pct":drawdown(curve),"exposure_pct":100.0}
