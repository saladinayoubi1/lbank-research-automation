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

Distinct-host reviewed-code numerical comparison completed at 2026-10-13T13:45:47.301275Z with native exit 0. All 16 comparison-cell digests and reported metrics matched: 12 selected-candidate partition/cost rows compare 14 report fields, and four additional challenger Training cells compare five ranking fields. Training aggregates and the original ranking matched. QA digest: `2264571a50b99af12479f733cb9ba2b208038ce4467ddc614578ba82a6bce259`.

Completed native regression and backtest receipts were reused with source, input, canonical digest, regenerated signal and original metric checks. The final stage reused 15 cell receipts and ran only the previously unfinished ETH challenger Training stress backtest. The receipt is in `completed-comparison/qa-evidence.json`; native exit, source/reuse bindings and retrieved-proof verification are preserved beside it. Earlier deadline failures remain recorded and are not relabeled as successful runs.

Independent Decimal accounting for all 12 selected report cells completed on Laptop1 at 2026-10-13T16:18:56.3322112Z with actual native exit 0. Audit digest: `13a16e4d308c94ab804706505c95dd1ae59d61ae735a12475b5ed323a488855f`. After the original 600-second stage stopped with exit 124, the continuation reused its three verified scalar receipts unchanged and calculated only nine remaining cells. Native regressions verified that the existing oracle's calendar-day cache preserved 20 unrounded Decimal metric/fill-path fixtures and six timezone/DST forms. Exact baseline/cache source bindings, complete embedded cells, native exit and retrieved-proof checks are preserved under `docs/evidence/isolated-jump-v6-20261013/8899ec6/qa-distinct-host/decimal-accounting/completed/`.

The four challenger Training cells have completed numeric comparison but are outside this selected-report accounting scope. Original-source full strict replay remains incomplete. Numeric and independent accounting agreement are correctness results; they establish neither positive expectancy, independent market data/signals, actual exchange fills nor a pristine prospective test. Both hypotheses remain outside Demo admission.

A new discovery study needs a materially distinct hypothesis and a frozen research contract before outcome inspection. Preserve the terminal novelty ledger, check both evaluated and screened mechanisms for duplicates, and select using Training only. Do not repeat v5 or this frozen producer to seek a favorable scenario. A later qualification claim needs its own unseen prospective data.

Research only; Demo admission=false; Live=false; official Coordinator advancement=false. No owner installation, journal or registry change is made by this decision.
