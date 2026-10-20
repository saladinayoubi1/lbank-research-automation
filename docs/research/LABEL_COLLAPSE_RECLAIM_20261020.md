# One fixed Demo-research candidate: label concentration collapse and price reclaim

The owner asked for a concrete strategy with two AIs and the real AI Room. This branch registers **one new-input hypothesis**, implements its bounded historical diagnostic, and preserves the original portfolio study. It does not admit a strategy to Demo, change the Paper writer, or enable orders.

The contract was committed at `6f0ea6f036da8c3d6a60b79a501c359419ce6848` before opening raw prices for the new feature. The selected parameters are the design agent's .20/.05 proposal. The critic's .25/.10 alternative is not tested. Results cannot cause threshold changes.

| Item | Fixed rule |
|---|---|
| Instruments and capital | Bybit Spot BTCUSDT/ETHUSDT, long/cash, one shared500USDT book and one position |
| New input | Absolute quote-notional concentration of literal CSV buy/sell labels, including both RPI values |
| Event | Previous completed4h candle red; absolute imbalance >=.20 |
| Response | Next completed4h candle closes above event high; absolute imbalance <=.05 |
| Entry | First trade/open in following4h candle, adverse slippage; BTC first on simultaneous eligible signals |
| Stop | Lower of the two signal lows; actual entry-to-stop distance must be1%-4% |
| Size | Gross<=250USDT; calculated ordinary stop loss including fees/slippage<=2.5USDT; cash constraint |
| Target/time |2R price distance or open six bars after entry; no trailing/additions |
| Ambiguity | Opening stop gap first, opening target gap at target without favorable improvement, then time exit; intrabar both-hit uses stop first |
| Reentry/end | No entry in an exit bar; final permitted historical close liquidates positions |
| Per-side fee/slippage |10/5bps conservative;15/10stress;25/15severe |

The exact CSV-to-API taker-side mapping remains unresolved. [Bybit REST](https://bybit-exchange.github.io/docs/v5/market/recent-trade) and [WebSocket](https://bybit-exchange.github.io/docs/v5/websocket/public/trade) define their API side fields as taker side; they do not explicitly establish the archived six-column CSV mapping. The chosen absolute feature is invariant to swapping all buy/sell labels and makes no aggressor-direction or L2 absorption claim. This algebra does not certify arbitrary source labeling errors.

## Study and falsification

This separate research protocol uses only the already retained158 official daily raw files,70,815,420trades and9484h bars from Aug1 through Oct18,2026. These are inspected development observations, never untouched/OOS evidence. The old warmup purpose is not retrospectively changed. No download or Oct19-Jan17 protected source read is authorized.

The no-flow control removes only the two concentration conditions. It retains every price, risk, execution and sizing rule. All three cost profiles report candidate/control outcomes and passive BTC, ETH, full50/50, capped250-gross50/50 and cash. One fixed exploratory pass requires positive candidate net in all costs, stress net exceeding both control and capped passive, and stress close-mark drawdown no worse than capped passive. Zero trades or a failed gate is terminal for this contract without retuning. A pass remains insufficient for Demo admission.

[Kitron and Wengrowicz,2026](https://arxiv.org/abs/2608.21888) report a15-minute reversal effect with about1.3bps gross edge versus5bps round-trip benchmark cost. That finding is a reason to respect cost barriers; it does not establish this4h adaptation or clear our approximate30/50/80bps round-trip assumptions.

## Actual AI contributions

- DeepSeek supplied two fresh real UI answers, including the current exact-system critique in AI Room round `8672db1c07e24e33985ba5a6ca9dc346`, answer SHA256 `47345f50b318de40bb2a1cccd748c0c8b144d672820a4666c8982cae74bf2517`. It rejects Demo admission and permits only a limited diagnostic.
- Codex design agent `/root/demo_novelty_inventory` supplied the selected fixed design before new-feature price reads.
- Independent Codex critic `/root/demo_strategy_critic` required ablation/cost-inclusive risk and independently implemented Decimal signal/accounting verification without importing the producer.
- Perplexity was IP-blocked and Claude region-unavailable. Their fresh requests were not submitted; neither supplies an approval/vote. No circumvention was attempted.

DeepSeek's mechanical objections are evaluated against the actual contract: positive1%-4% stop distance already implies E>S; an opening target-gap branch already exists; quantity<=250/E already caps notional. Its arbitrary minimum20trades is not adopted, consistent with repository guidance against arbitrary trade-count gates. Statistical sufficiency and untouched validation remain separate unresolved admission requirements.

## Verification and current native checkpoint

On Laptop2 DESKTOP-F4SA4VL, the exact four contract/producer/independent-QA/crosscheck Git blobs were reproduced before processing. Native Python3.12.10 is the existing `E:\NEXUS-QA\pytest-env\Scripts\python.exe`.

-9 execution unit checks passed.
-14 independent synthetic integration/corruption checks passed, including stop-first, gap loss exceeding budget, target-gap pricing, exact time exit, terminal/last-bar entry, global label swap, altered fill/cash/quantity/timestamps, missing cost and fabricated months.
- Latest verified native phase: **features**, started2026-10-20T14:18:19Z. At that checkpoint no economic result or independent financial receipt had been produced.
- One bounded native process validates hashes of all158 raw files/receipts, compares pandas quote aggregates against a separate all-row scalar csv/Decimal implementation, and cross-checks948 OHLCV bars against the retained independent source QA. Per-day digest-bound checkpoints permit resume without retuning or a new source acquisition.
- If features finish within the480-second bounded stage, the one-shot runner proceeds to all21 financial reports and independent Decimal QA, then saves a SHA256-checked compressed evidence packet. No monitor, schedule, watchdog or persistent runner is installed.

Final native evidence will supersede this checkpoint only when the actual result and independent QA are retrieved. Main strategy/runtime, Laptop1 install/profile/journal, original frozen future study, Live=false and orders0 remain unchanged.

## Source and reproduction

Files:
- `research/label_collapse_reclaim_4h_v1.json`
- `scripts/nexus_label_collapse_research.py`
- `research/label_collapse_independent_qa.py`
- `research/label_collapse_synthetic_crosscheck.py`
- `research/label_collapse_native_run.py`

The native runner checks the four executable/contract Git blobs at source commit `2ea3d19d465fd075e6c7a23bb6e41b1ff6dee06f`. Its own later additive registration does not change those blobs. Compressed packet entries decode with `zlib.decompress(base64.b64decode(entry["zlib_base64"]))`; verify each resulting byte count and SHA256 before use.
