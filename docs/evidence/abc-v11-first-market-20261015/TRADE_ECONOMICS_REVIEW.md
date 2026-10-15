# ABC v11 — accepted-trade economic forensic review

Date: **2026-10-15 UTC**. Scope: **read-only postmortem of the single completed preregistered ABC v11 historical Bybit evaluation**; no repeat market run, tuning, factory registration or Demo order. Decision: **DO NOT PROMOTE**.

## Original frozen evidence

- Computational GitHub head **`c96b2f2a8ba447c14acea1594f6db811163944e6`**; this forensic report lives in the evidence-only later commits of **draft PR #2662**.
- Source market result byte SHA-256: `2aa967092412ea8edff27793cc190b4b036208ea1c3dc068d99b2a262a77a49d`.
- Source fill trace byte SHA-256: `dedf89ff796b958f1afe1e930414e3f7718ac77924831e2946020face295836d`.
- Original complete market invocation SHA-256: `fd72694d72bc67d46e9673b385e1c56d4090ff7a87c745ac3a9616a435849ffb`.
- Bybit archive identity: `2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422`; source raw six-file hashes and terminal v9 journal still match the frozen manifest.
- Original market producer completed native exit **0**; independent Decimal fill/P&L QA and independent raw closed-15m chronology/stop-first exit QA both passed.
- New independent decomposition artifact: [`TRADE_ECONOMICS_QA.json`](./TRADE_ECONOMICS_QA.json), byte SHA-256: **`ffa5b4d9317282cdca71ff63374e445fa118a7f5193c4380186a5e982dd4306c`**. Its source-specific 12-cell accounting reconciles within 0.00001 USDT; 69 unique decisions / 138 profile-specific trade records, 0 added market evaluations.

## What the accepted trades actually earned

All values are **USDT**, sums of three **separately funded 10,000 USDT research cells** per symbol/profile, *not* a continuous compounded portfolio. The “gross reference” is computed using the **observed quantity and observed exit bar** at original pre-slip entry/exit reference prices. It is **not** a new no-fee strategy backtest: changing costs can alter actual position size, stop/target prices and exit bars.

| Asset, cost profile | Closed trades | Observed reference gross | Actual fees | Actual entry + exit slippage | Total friction | Net realized |
|---|---:|---:|---:|---:|---:|---:|
| BTC conservative | 29 | +10.61373008 | 57.88733736 | 28.94367133 | 86.83100869 | **−76.21727861** |
| BTC stress | 29 | +28.48607883 | 143.96332661 | 86.37806006 | 230.34138667 | **−201.85530784** |
| ETH conservative | 40 | −24.75970862 | 78.50857196 | 39.25427979 | 117.76285175 | **−142.52256037** |
| ETH stress | 40 | −42.47436160 | 195.05547763 | 117.03319101 | 312.08866864 | **−354.56303024** |

Identity checked for every closed fill: `reference_gross = qty × (exit_reference − entry_reference)`; `net = reference_gross − qty × (entry_slipped − entry_reference) − qty × (exit_reference − exit_slipped) − entry_fee − exit_fee`. The native cost schedule is exactly **10 bps fee + 5 bps slippage per leg** in conservative and **25 bps fee + 15 bps slippage per leg** in stress. Both components reconcile independently with the recorded fills and fees.

**Interpretation:** On BTC the observed pre-friction payoff is only slightly positive, vastly smaller than realistic tested friction; on ETH even this conditional reference payoff is negative. Thus the loss is **not fixable merely by improving execution** while preserving other conditions.

## The structural problem is more than fees

| Symbol | Conservative stop exits | Conservative target exits | Stress stop exits | Stress target exits |
|---|---:|---:|---:|---:|
| BTC (29 closed) | 20 | 9 | 21 | 8 |
| ETH (40 closed) | 29 | 11 | 33 | 7 |

**BTC validation:** 8/8 trades stopped, in both profiles. The previously inspected last partition also had 3/3 stop exits. Their conservative **observed gross references** are negative, respectively **−32.19807221** and **−18.69168592 USDT**, *before fees and slip*. **ETH validation:** 11 stops and 5 target exits (both cost profiles). Conservative observed reference gross was **+5.16893893 USDT**, but execution friction **47.09901370 USDT** rendered its net **−41.93007477 USDT**. No positive out-of-sample admission inference is warranted.

Cost profile sensitivity is **path-dependent**: among 69 identical decision IDs, **36 exit-bar indices differ** across fee profiles, and **5 exits become stop instead of target** under stress; the opening decision and source signal identities were independently paired and verified. Therefore simply multiplying observed conservative friction to estimate alternative cost conditions is invalid.

## Signal admission

The 325 unique first closed-candle price breaks were each observed in both cost profiles; per profile **69 events were scheduled for next-open entry** and **256 had signal-denied disposition**. Overlapping field-denial counts per profile: `h4_up=178`, `abc_stress_cost_feasible=131`, `h1_vol_ok=47`. These **cannot be summed as independent rejections**. The `h1_vol_ok` rule measures normalized closed one-hour **range/volatility**, not transaction volume. These counts do not prove that bypassing a gate improves expectancy and are not grounds to relax cost or safety checks.

## Conclusion and next research gate

ABC four-pivot hypothesis improved event frequency versus the previous five-swing topology, but **both BTC and ETH validation are negative under conservative and stress costs**; **no Demo promotion**. The observed pre-cost weakness of BTC validation and excess stop exits argue that **entry quality / structural confirmation and the stop-versus-target outcome should be investigated in a separately preregistered topology**, not by retrospective filter/ATR optimization on the already-inspected final fold. Only additional genuinely forward unseen, prospective diagnostic data could serve as an independent promotion gate.

**Unresolved limitations:** historic final partition previously inspected; not a fresh clean holdout; conditional reference gross is not a cost-free counterfactual; no independent line-by-line verification of every higher-timeframe feature or out-of-sample stationarity; no live execution or estimated monthly income claims.

**Safety invariant:** Research only; Bybit only; Live disabled; sole Laptop1 Paper writer and installed NEXUS unchanged; VPS remains paused; GitHub PR remains Draft; no automatic factory registration or auto-admission.
