# Causal bullish Butterfly v8

One fixed, research-only, long-only Spot hypothesis following the owner's request.
Price geometry uses strict alternating confirmed X/A/B/C/D pivots. Three candles
to each side are required: pivot D at j is first known at the close of j+3, the
factory context is additionally lagged to j+4, and an entry signal at that close
can fill only at j+5 OPEN. Past events never move when later candles arrive.
Tied/dual high-low extrema are rejected because OHLC cannot reveal their order.

The preregistration fixes B near0.786 XA and D near1.27 XA, bounded C/BC/CD
relationships,192-bar maximum span and one separate bullish closed response.
Bounds are research implementation choices; this is not a reproduction of a
proprietary indicator, a claim to cover every discretionary Butterfly variant,
or evidence of positive expectancy. Ratio roundoff1e-12 handles binary floating
representation only; no market-data fitting/tolerance relaxation is permitted.

References: Scott Carney's public Butterfly geometry description,
https://harmonictrader.com/harmonic-patterns/butterfly-pattern/ .
The source motivates the geometry; it does not validate this Bybit strategy.

The shared risk0 engine remains exact: stop1.5ATR, target2R,64-bar time exit,
one collateral-backed long per symbol, cash exposure/risk/daily-loss/drawdown
guards, next-open entry, adverse same-bar stop priority, all per-leg costs.
Conservative10/5bps and stress25/15bps fee/slippage remain exact. Each isolated
cell starts at10000USDT, separate from the owner's500USDT Paper account.
No minimum trade-count gate or maximum trades limit is introduced.

The parent's actual v7 inventory is92factory specs/119total mechanism IDs;
v8 appends exactly one to93/120. The original before-implementation precheck
mentioned91/118, the pre-v7 inventory; the source-derived fixture corrects that
description without changing any frozen pattern parameter, old contract or
frontier tier. All earlier IDs/order/contracts and risk function hash are
checked; completed old producers/accounting runs remain untouched.

The old archive has already been inspected. Training-only ranking, validation
and historical-test diagnostics are exploratory; later pristine data and
independent numeric/accounting/leakage verification are separate gates.
No owner admission, Coordinator advancement, registry write or automatic
Demo/Live promotion. No owner install/profile/journal/failover/remote change.

