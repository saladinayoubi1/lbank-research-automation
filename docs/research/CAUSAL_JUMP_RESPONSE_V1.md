# Causal jump-response research preregistration

Status: research-only hypotheses, no profitability or qualification claim.
System Map: DATA-21 -> RES-31/RES-30 -> RES-32 -> VAL-40 -> QA-41.

This adds two event-response mechanisms after the completed v5 study. Their new
context uses log-return realized variation versus bipower-inspired variation,
instead of reusing entropy, autocorrelation, wick, beta-residual or parameter
variants as a fresh hypothesis. Older IDs, ordering, fingerprints, archive and
receipts remain historical evidence at their original source SHA.

For decision bar i, the event is the completed return at i-1. Its volatility
denominator uses 96 adjacent absolute-return products ending at i-2, excluding
the event itself. The 96-return realized/excess-variation window ends at i-1.
These are finite 15-minute-grid proxies; they are not formal significance tests,
authenticated trade flow, L2 liquidity or proof of market discontinuities.

Frozen hypotheses: negative shock <= -3 followed by recovery in a completed
4h range; positive shock >= 3 followed by continuation in a completed 4h up
structure. Both require excess-variation share >= 0.10, the existing completed
1h volatility guard and a later closed price confirmation. Fill remains next
15m open with the existing adverse stop and collateral/cost model.

Use existing verified BTC/ETH 15m/1h/4h Bybit archive and existing train-only
tournament. Conservative and stress cases use the same hypothesis and data. Different
fill prices can change exits and trade counts; these cost scenarios are not
independent economic trials. Historical validation and inspected test are
diagnostics; an independently frozen prospective holdout is still required.
Live=false, automatic Demo admission=false; owner 500-USDT state is not used.

Method references:
- Barndorff-Nielsen and Shephard (2004), Power and bipower variation with stochastic volatility and jumps: https://shephard.scholars.harvard.edu/publications/power-and-bipower-variation-stochastic-volatility-and-jumps
- Jump risk and high moment connectedness among cryptocurrencies (2026): https://link.springer.com/article/10.1186/s40854-026-00934-9

These papers motivate volatility/shock measurement, not the profitability of
the two preregistered trading rules. The 2026 study uses 5-minute data and
threshold bipower statistics; this research does not claim to reproduce it.
