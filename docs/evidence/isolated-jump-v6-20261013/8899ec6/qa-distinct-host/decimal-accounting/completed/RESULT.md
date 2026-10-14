# Completed independent Decimal accounting for the selected v6 report

The native Laptop1 audit completed all 12 selected report cells on 2026-10-13T16:18:56.3322112Z with actual native exit 0. Final audit digest: `13a16e4d308c94ab804706505c95dd1ae59d61ae735a12475b5ed323a488855f`. Worker elapsed time was 403.750 seconds; RDC process runtime was 432.14 seconds.

The selected upward-shock hypothesis remains negative in all four Training cells, both validation stress cells and all four inspected historical-test cells. The challenger is negative in all four Training cells. Neither hypothesis qualifies for Demo admission.

## Scope and exact identities

- Original study/report source: `8899ec6bec4927fc39795f2867be91e2431178c6`; original report digest `02c7a7b1dd0a78ed13d8dbefcfec7824d11c9eedd22e3d337b5e658eb0e099b3`.
- Existing independent Decimal oracle baseline: ref `7294b2d72d2ae5a46a03a26c23242ac27a385f1a`, root module blob `d583ed655efe64b5c0c5eb73960eb217bc7ded83`.
- Reviewed oracle computation: ref `b6c6efb3cdf7ceb6e23a117df43c6803604b6187`, evidence module `../day-cache/nexus_composite_fill_oracle_day_cache.py`, blob `35488fbf90a987f83dd637db4209703eb201ea0e`, file SHA-256 `5c51c9e28bb8732784194735f4fe6f01abdf5a26477e2e2291efde039e8420f7`. This is the evidence module at that ref, not a claim about its root oracle.
- Separate completed numeric comparison: computation source `9144f888306e12a86fb4812896b137c13a6adeb9`, 16 cells, digest `2264571a50b99af12479f733cb9ba2b208038ce4467ddc614578ba82a6bce259`.
- Resumed worker SHA-256 `241bb1d641d318792da6379dff7a62b917ef20cd4c6b7f547fed41747a468654`; input file SHA-256 `094ad00eb0440fd736422585ae77052e6235d392fa2d2070a32121a9d354da2a`; canonical input digest `d4cc726dd59bf7b100ff12adbea5855699f65f14c53401c55be32cc4f63562da`.

The first bounded original-Decimal stage stopped at its 600-second deadline with native exit 124 after three successful cells. Its terminal failure and those receipts remain in `../original-terminal/` and `../first-cell/`. The continuation revalidated the prior worker/input, exact cell digests, regenerated signals, feature hashes and report fields; it reused those three receipts unchanged and calculated only nine remaining cells. No completed producer, v5 job, numeric backtest or earlier cell accounting was rerun.

## Correctness checks

Only calendar-day key calculation was cached in the existing oracle; Decimal arithmetic, modeled fills, fee/slippage, stop ordering and risk rules stayed the same. Precheck, exact baseline goldens and the native harness are retained in `../day-cache/`. Before continuation the Windows gate passed 20 unrounded Decimal metric/fill-path fixtures, six timezone/DST forms, the object fallback and the absence of scalar day-floor calls in the canonical path. AST restoration matched the baseline. Native regression elapsed 31.953 seconds with Pandas 2.3.3.

The oracle uses its existing report-field tolerances: PNL 0.0001 USDT, percentage metrics 0.00001 percentage points, turnover 0.0002 and profit factor 0.00002; discrete fields match exactly. This is report-precision accounting agreement, not a claim of bit-identical floating-point outputs.

Local readback checked the complete audit digest, all 12 cell digests, original report PNL/returns/counts/bars/costs, numeric-proof signal/config bindings, source/config/worker identities, three unchanged original scalar receipts, the native regression receipt's SHA-256 and actual native exit 0. It ran no accounting recalculation or backtest. The Windows regression receipt uses native CRLF bytes; other JSON receipts use the worker's explicit LF serialization.

## Boundaries

Accounting covers only the 12 selected asset/partition/cost report cells. The four challenger Training numeric comparisons are outside this accounting scope. Original-source full strict replay remains incomplete; this receipt does not complete that separate gate. Shared candles and signals are not independent market-data or signal proof; actual exchange fills and a pristine future holdout are not established.

Research only; owner Demo admission=false; Live=false; automatic Demo=false; official Coordinator advancement=false. No owner profile, journal, installation, registry, frontier or primary research placement changed. Both frozen hypotheses remain unqualified; no validation/test retuning or repeated producer is justified by this result.
