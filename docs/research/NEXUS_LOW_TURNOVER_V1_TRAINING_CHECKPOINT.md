# Low-turnover v1: historical development checkpoint (NOT candidate validation)

- Freeze: hypothesis/manifest PR #1820, source `aca436fff20f1d208d4ec67f54099f7d3fc75d89`; exact two preregistered alternatives (20 bars / 1.0% deadband and 40 bars / 1.5% deadband), both six-bar hold and three-bar cooldown.
- Data: public **Bybit spot** BTCUSDT and ETHUSDT closed 4h candles via the canonical registry and provenance validator. Exactly 320 aligned bars per asset ending **2026-08-20 00:00 UTC**, earlier than #984's failed prospective period. The collector persists complete canonical public datasets locally; no exchange secrets or real orders.
- BTC binding: `f701b803339dc689ce9c9d55ac6e065167ab23e9caf46bc4d63f504c87e27b40`; manifest `6e3df87a7bf4a752f09af112a238ca906f297b4902de6fe6dea8a898f4a79f9f`.
- ETH binding: `baac17ce337a23a5527f0d06a55067e008df5adc7237169450a641302a8a1463`; manifest `1ef77cc8d6941a055dcac59ead5c399342a72f6f8704b971f1300287d3df8de3`.
- Execution: corrected shared next-open long/flat simulator; conservative 10+5 bps, stress 25+15 bps **per leg**. The shared historical simulator uses **10,000-USDT research notional**, not the separate **500-USDT** owner desktop Paper wallet. These results cannot prove 500-USDT executable minimum lot or liquidity.

## Observed historical DEVELOPMENT results

The two alternatives and unchanged old 12-bar / 0.2% momentum control were evaluated across both assets and both cost profiles. These are historical training diagnostics, not a pristine test or profitability claim.

| Full-window strategy | BTC stress return | ETH stress return | BTC actual fills | ETH actual fills |
|---|---:|---:|---:|---:|
| Unchanged 12-bar control | -7.35% | -5.24% | 38 | 58 |
| Frozen A: 20 / 1.0% | +2.22% | +12.71% | 14 | 18 |
| Frozen B: 40 / 1.5% | -3.31% | -7.03% | 12 | 16 |

Overlapping historical **training-only** windows (first 240 and last 240 bars)
show frozen A is not yet robust: BTC stress return **-2.43%** early
and **-1.21%** late; ETH stress return **-0.16%** early and
**+4.00%** late. The apparent positive whole-period totals are
insufficient for admission. No historic holdout, future data, derivatives
funding, margin or executable bid/ask gate has been passed.

- Exact first local real diagnostic JSON digest: `9e40ac50d8d016bf0c55b86b47e3b167a637f7a1e51792149bf21c1ebb416c30`.
- Owner Lenovo public dataset snapshots and full per-cell JSON retained under `%LOCALAPPDATA%\\NEXUS\\lowturnover-dev-proof-aca436f`; reloading and replaying those exact saved canonical datasets reproduced the same digest.
- Training runner explicitly rejects a future or shifted bar, insufficient or tampered provenance, extra variants, altered stress costs, or incomplete BTC/ETH surface.
- State: **no candidate**; no old #984 requalification and no new 30-day Paper run. Any genuinely independent new holdout must come strictly after freeze and not before **2026-09-26 00:00 UTC**; evaluate once without selection. Derivatives/funding, exact risk, and 500-USDT executability need independent checks afterward.
