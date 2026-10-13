# Isolated jump v6 research decision

Both preregistered shock-response hypotheses produced negative net returns in every training asset/cost cell. Keep both outside Demo admission. The selected upward-shock continuation is the less-negative training candidate, not a positive strategy.

## Frozen study identity

Original producer source: `8899ec6bec4927fc39795f2867be91e2431178c6`; lease `isolated-jump-v6-20261013-8899ec6`; report digest `02c7a7b1dd0a78ed13d8dbefcfec7824d11c9eedd22e3d337b5e658eb0e099b3`. Training alone determined selection. Historical validation/test observations must not be used to retune these candidates. The archive is not a pristine future holdout.

## Training results

| Frozen hypothesis | Asset | Conservative net return | Stress net return |
| --- | --- | ---: | ---: |
| Isolated upward shock follow-through | BTCUSDT | -1.17177748% | -2.65596795% |
| Isolated upward shock follow-through | ETHUSDT | -0.98940336% | -3.11873768% |
| Isolated downward shock recovery | BTCUSDT | -1.47693518% | -4.31040685% |
| Isolated downward shock recovery | ETHUSDT | -1.18575398% | -4.66750337% |

The upward-shock candidate ranked first from four negative training cells; median net return was -1.91387272%, with stress median -2.88735281%. The downward-shock candidate ranked second; median -2.89367101%, stress median -4.48895511%. These are dependent asset/cost evaluations and are not independent statistical trials. No minimum trade-count threshold was added.

## Selected candidate after training

| Asset | Validation conservative | Validation stress | Inspected historical test conservative | Inspected historical test stress |
| --- | ---: | ---: | ---: | ---: |
| BTCUSDT | -0.46247782% | -1.14191583% | -0.07984932% | -0.31938911% |
| ETHUSDT | +0.11101871% | -0.79178750% | -0.48361293% | -0.86419824% |

Validation runs from 2025-02-11 09:45 through 2025-11-06 04:45 UTC, approximately nine months. The inspected historical test runs from 2025-11-06 05:00 through 2026-08-01 00:00 UTC. These returns are whole-partition results, not monthly returns. The small positive ETH validation result under conservative costs does not persist under stress costs or either historical-test cost case.

Conservative fee/slippage is 10/5 bps per leg; stress is 25/15 bps per leg. Each cell uses simulated initial capital 10000 USDT. This is separate from the 500 USDT owner reference. Modeled fill differences can change paths and trade counts; cost-case return differences are not a direct fee-only attribution.

## Verification and next research boundary

The calendar-day cache computes day keys once and retains the study's signals, fills and risk rules. The original producer/report identity and the reviewed computation identity are separate. Verification checkpoints and exact source bindings live under `docs/evidence/isolated-jump-v6-20261013/8899ec6/qa-distinct-host/day-cache-comparison/`.

Numerical replay agreement is a correctness result. It does not create positive expectancy, an independent accounting proof, or a pristine prospective test. Independent Decimal accounting and original-source full strict replay must retain their actual unfinished status unless separate receipts complete them.

A new discovery study needs a materially distinct hypothesis and a frozen research contract before outcome inspection. Preserve the terminal novelty ledger, check both evaluated and screened mechanisms for duplicates, and select using Training only. Do not repeat v5 or this frozen producer to seek a favorable scenario. A later qualification claim needs its own unseen prospective data.

Research only; Demo admission=false; Live=false; official Coordinator advancement=false. No owner installation, journal or registry change is made by this decision.
