# UTC-slot volume v7 change precheck

Recorded before implementation on 2026-10-13. Governance read at main ed2f16b6aabe7d0d97562fd64bb4e3609dc51b32; code parent e089c175364ffc50521d22f0455bb40cda57a0a4.

Change: Append one fixed exploratory daily-clock volume mechanism and a causal feature helper to the existing composite research/factory.
System Map node(s): DATA-21, RES-30, RES-31, RES-32, VAL-40, QA-41; QUAL-42/REG-50/PAPER-62 remain gated.
Existing component being changed: nexus_mechanism_factory.py and nexus_composite_strategy_research.py.
Why existing component cannot already satisfy the need: Existing relative volume compares a contiguous 20-bar history. No evaluated/screened mechanism conditions on seven exact prior daily UTC slots or their dispersion; fixed-interval seasonality can otherwise appear as unusual participation.
Primary runner / execution lane: Laptop2 Research primary for later archived-data compute; scratch/hosted fast unit and contract preparation only now. Both laptops observed Offline; no native run launched and no failover or writer takeover.
Data source and provenance: Later execution must reuse checksum-verified Bybit Spot BTC/ETH 15m/1h/4h archive 2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422 and terminal v6 ledger 18675234ad8c981be8f8c5e348c1a39737a9c3fc4ca09ba0ae9532c8a59b567a. No data download now.
Upstream dependencies: Exact parent code/contracts; contiguous closed UTC 15m volume history; existing completed 1h/4h context, reviewed condition grammar and provenance checks.
Downstream consumers: Existing training-only frontier screen and immutable research reports. Independent validation/accounting/qualification remain separate.
Authority level: Reversible strategy research and Git draft only; not promotion.
Paper/Live boundary: Research-only, Live=false, Demo admission=false; owner 500 USDT profile/journal/install unchanged.
Duplicate-work check: Preserve all prior candidate IDs/order/contracts/fingerprints and terminal v6 ledger; no completed v5/v6 producer, numeric replay or Decimal audit repeated. Compare both evaluated and screened sets; one new feature topology, no parameter sweep or historical outcome retuning.
Failure mode: Nonfinite/negative volume, duplicate/out-of-order/gapped/off-grid time or non-UTC/naive timestamps fail closed; insufficient seven-day history/zero baseline yields unavailable features and no signal.
Rollback: Revert additive helper/contract and append-only integration; do not delete prior reports/ledgers or owner state.
Tests: Scalar time-indexed daily-slot oracle, current/future perturbation, exact lag, warmup/zero-volume, scaling, UTC/DST-equivalent inputs, malformed grid, contract authority/digest denial and prior-generation/terminal-ledger preservation.
Independent QA required: Local tests are developer evidence only. Native source-exact producer plus distinct-host numeric/Decimal/leakage checks are required after future execution; no current profitability or native-QA claim.
Deployment/cutover impact: None. Draft stacked over existing research branch; no protected workflows, runtime policy or installations changed.
Evidence required to declare DONE: Fixed source/contract identities, local meaningful tests, reviewed merge, later native training/locked diagnostic results and independent proof. This turn aims only for a source-frozen, locally tested research candidate; historical archive is not a pristine holdout.

Literature motivation: Hansen, Kim and Kimbrough, Periodicity in Cryptocurrency Volatility and Liquidity, arXiv:2109.12142v2, https://arxiv.org/abs/2109.12142. Recurrent volume/volatility patterns motivate daily-clock normalization. The paper does not establish this Bybit Spot candidate's positive expectancy, directional prediction, seven-day parameters or fill quality.
