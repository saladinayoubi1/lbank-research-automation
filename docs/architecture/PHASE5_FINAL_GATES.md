# NEXUS Phase 5 final gates (6-9)

Parent contract: #583. This document records implementation intent only; the exact-head Gate 9 runtime artifacts are the closure evidence.

## Gate 6 — Evidence-driven Strategy Factory

`phase5_strategy_factory.py` is the canonical Phase 5 research qualification entry point. It accepts only a validated Gate 7 dataset artifact and requires a preregistered experiment identity bound to dataset revision, strategy family/version/config, Git source SHA, cost model, and explicit kill criteria. The frozen path is:

`Evidence -> Hypothesis -> Preregister -> Robustness -> Cost/Funding/Slippage Stress -> Walk-forward -> OOS -> Regime Analysis -> Failure Modes -> Qualification Artifact -> Paper Candidate`

Survivorship, lookahead and data-snooping controls are explicit. Benchmark and uncertainty evidence are mandatory. A deterministic kill is a valid terminal Gate 9 result and is not a profitability claim.

## Gate 7 — Canonical market-data semantic binding

`phase5_data_binding.py` binds a validated provenance manifest and its candle payload back to the machine-readable source registry. Downstream eligibility requires the registry-declared primary namespace (currently Bybit for the frozen spot mappings), exact canonical instrument/market/timeframe/category/interval/finality/endpoint semantics, and intact provenance/binding digests. Secondary/tertiary sources remain reconciliation evidence and cannot silently replace the primary source.

## Gate 8 — Shadow migration and chaos cutover

`phase5_shadow_migration.py` requires fixed-input parity (or an explicitly documented intentional difference) and all frozen chaos cases: restart, stale lease, duplicate callback, corrupted state, provider outage, GitHub outage, Windows offline/reconnect, and partial evidence failure. Cutover readiness is fail-closed. The durable Phase 5 Supervisor is the canonical Phase 5 mode only after this evidence is green; the legacy coordinator is retained as watchdog/fallback rather than destructively removed.

## Gate 9 — One exact source revision

`scripts/phase5_gate9_evidence.py` refuses to run unless the executing Git checkout equals the declared 40-character source SHA. It runs the Phase 5 Gate 1-9 proof suites and emits a digest-bound runtime artifact. `NEXUS Runtime Worker` generates the same exact-head proof on GitHub cloud and the real self-hosted Windows runner.

The Gate 9 demonstration deliberately uses an explicit deterministic `ROBUSTNESS_KILL` terminal result. It proves the qualification machinery, not strategy profitability.

## Authority boundary

Phase 5 remains research/backtest/paper-trading only. It grants no live exchange orders, private exchange credentials, withdrawals, production promotion/deployment, billing changes, signing authority, or irreversible owner actions. L4 remains owner-required and deterministic Risk remains final authority for paper execution.
