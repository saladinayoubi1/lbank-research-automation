# NEXUS Research Automation

NEXUS is a fail-closed, evidence-driven research and paper-trading platform for public crypto/FX market data. The repository began as LBank data research infrastructure and now includes canonical multi-source data contracts, deterministic backtesting, durable mission/task state, independent qualification, bounded AI-provider assistance, and paper-only execution controls.

## Current project map

The canonical navigation index for the project is [`docs/PROJECT_MAP.md`](docs/PROJECT_MAP.md). It maps the completed Phase 7 lanes, source-of-truth order, major implementation surfaces, verified acceptance path, and incremental repository-cleanup rules.

Phase 7 (`#696`) and its acceptance path are complete. The durable completion state and fixed evidence identifiers live in [`docs/project_memory/STATE.json`](docs/project_memory/STATE.json). No later phase or broader financial authority is implied; new work is bounded maintenance or must begin with a new explicit owner-approved contract. Historical phase documents remain evidence and context and do not override current executable behavior.

## Authority boundary

NEXUS is **research / backtest / paper only**.

It does not authorize:

- live-money order placement;
- private exchange credentials;
- withdrawals;
- production promotion;
- signing authority;
- billing changes;
- AI/provider overrides of deterministic Risk.

A strategy qualification result is evidence, not permission to trade live. Deterministic Risk remains final authority for any paper candidate.

## Architecture

```text
Public market data (Bybit primary; registry-defined fallbacks)
        ↓
Provenance + semantic source validation
        ↓
Canonical closed-candle dataset binding
        ↓
Preregistered strategy experiment
        ↓
Deterministic next-bar-open backtest
        ↓
Robustness / cost stress / OOS / regime evidence
        ↓
Independent Strategy Factory qualification
        ↓
Killed ───────────────┐
                      └─ or ─> Paper Candidate
                                  ↓
                         Deterministic Risk review
```

Durable orchestration is separate from strategy authority:

```text
Mission/task contract
  → hashed CAS state
  → attempts / leases / idempotency
  → independent verification
  → deny-by-default worker policy
```

Phase 7 connects those existing foundations into one replayable system:

```text
Mission
  → Supervisor / Resource Manager
  → verified Workers
  → canonical Data Intelligence / Regime
  → Strategy Factory
  → Decision
  → deterministic Risk
  → realistic Paper execution
  → Performance / Drift
  → Mission Control
```

## Canonical market data

`docs/architecture/market-data-source-registry.yaml` is the machine-readable semantic authority. It defines canonical symbols, market categories, timeframes, source roles, endpoint contracts, timestamp grids and closed-candle finality.

The current hierarchy uses Bybit as primary for canonical mappings. Secondary/tertiary sources cannot silently replace primary data. Unknown, stale, substituted or semantically mismatched data fails closed before strategy qualification.

Key modules:

- `bybit_public_klines.py` — bounded public closed-candle retrieval;
- `market_data_provenance_manifest.py` — deterministic provenance binding;
- `phase5_data_binding.py` — canonical source/semantic enforcement;
- `data_readiness.py`, `research_data.py` — legacy/local dataset readiness and guarded loading.

The original LBank collector remains useful as a public-data research lane; it is no longer the sole project architecture.

## Strategy research

`backtest_engine.py` is the strategy-neutral accounting engine. A signal emitted at candle `t` executes at candle `t+1` open. It models bounded target exposure, fees, adverse slippage, equity, drawdown and end-of-test liquidation.

`phase5_strategy_factory.py` freezes experiment identity and qualification semantics. Approved families are momentum, trend breakout and mean reversion. Qualification consumes typed evidence and either produces `killed` or a bounded `paper_candidate`; it never grants live authority.

`phase6_research_pipeline.py` connects real canonical Bybit datasets to the existing backtest and Strategy Factory path. It generates deterministic long/flat research targets, base/stress backtests, a final holdout, ordered regime evidence and a paper-only handoff artifact. It contains no private API or live-order path.

A passing pipeline is **not a profitability claim**. The dataset, hypothesis, cost model, kill criteria and fixed code SHA remain part of the evidence boundary.

## Durable state and verification

Phase 5 established the canonical durable mission/task runtime:

- `phase5_mission_contract.py`
- `phase5_state_store.py`
- `phase5_attempts.py`
- `phase5_verification.py`
- `phase5_worker_policy.py`
- `phase5_strategy_factory.py`
- `phase5_data_binding.py`

The durable Phase 5 checkpoint is `.nexus/phase5-checkpoint.json`; Gate 9 Cloud/Windows evidence is preserved under `docs/evidence/phase5/gate9/`.

## Optional AI providers

AI providers are bounded assistants only. DeepSeek is optional and must not become a startup dependency or authority holder.

`deepseek_provider.py` uses a canonical USD 5.00 monthly authorization ledger with conservative pre-I/O reservation, a protected reserve, kernel-managed serialization, ambiguous-charge quarantine and fail-closed pricing/model/ledger validation. Network traffic is separately constrained by the egress authorizer and pinned HTTPS transport.

The budget/recovery authority is documented in `docs/architecture/ADR-AI-PROVIDER-BUDGET.md`.

A `DEEPSEEK_API_KEY` must only exist in an approved secret store. Never commit or paste it into repository content. Key presence alone does not authorize paid routing.

## Testing

Install the pinned development environment and run the complete suite:

```bash
python -m pip install -r requirements-dev.lock
python -m pip check
python -m pytest -q
```

Useful focused suites:

```bash
python -m pytest -q tests/test_phase5_mission_contract.py
python -m pytest -q tests/test_phase5_state_store.py
python -m pytest -q tests/test_phase5_strategy_factory.py
python -m pytest -q tests/test_phase6_research_pipeline.py
python -m pytest -q tests/test_deepseek_budget_contract.py
```

GitHub pull requests must also satisfy the repository's required cross-platform and control-plane checks. Candidate code must not weaken tests, validators or protected workflow policy to obtain green CI.

## Data and backtest limitations

Market data can contain venue outages, listing changes, bad candles or incomplete history. Canonical validation reduces these risks but does not make historical data infallible.

The backtest is deterministic research infrastructure, not an exchange simulator. It does not claim full order-book depth, partial-fill realism, exchange liquidation behavior or intrabar stop sequencing unless explicitly modeled by a research slice.

Results must be interpreted with fees/slippage stress, OOS evidence, regime behavior, drawdown and failure modes. Research that fails its preregistered controls is killed rather than tuned around the gate.

## Project closure model

Phases 3–6 are closed historical prerequisites and remain preserved as completed contracts unless new evidence explicitly proves a false-green dependency.

**Phase 7 is complete.** The fixed-SHA replayable proof connected the control-plane, canonical data, Strategy Factory, deterministic Risk, Paper, performance/drift, and Mission Control surfaces. The authoritative completion tuple and closure state are recorded in [`docs/project_memory/STATE.json`](docs/project_memory/STATE.json); old planning text must not reopen the completed phase.

Follow-on work is maintenance, defect correction, evidence preservation, or a separately approved future contract. Infrastructure work, including Windows runner work, is not a separate product goal and must be tied to a current bounded requirement.

Any future expansion of financial authority requires a new explicit owner-approved contract. Completion of Phase 7 does not imply live trading, credential authority, withdrawals, signing, billing, or L4 execution.
