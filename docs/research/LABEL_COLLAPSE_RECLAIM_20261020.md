# Label concentration collapse and price reclaim: terminal negative

**The one preregistered system was tested and rejected by its fixed passive-benchmark gate. It is not Demo/Paper eligible.** It produced one positive closed trade, but stress net was only +2.648267 USDT versus +73.460698 for the required capped passive comparator. Lower drawdown does not replace the failed return condition.

The owner requested a concrete strategy with two AIs and the actual AI Room. Contract `6f0ea6f036da8c3d6a60b79a501c359419ce6848` was committed before new-feature price reads. The .20/.05 design was selected once; the critic's .25/.10 alternative was not tested. No thresholds changed after results.

## Fixed system

| Item | Rule |
|---|---|
| Instruments/book | Bybit Spot BTCUSDT/ETHUSDT, long/cash, shared 500 USDT and one position |
| New feature | Absolute quote-notional imbalance of literal CSV buy/sell labels; both RPI values included |
| Event/response | Previous completed 4h bar red with imbalance>=.20; following completed 4h close above event high with imbalance<=.05 |
| Entry | First trade/open in next 4h bar; adverse slippage; BTC first if both eligible |
| Stop/sizing | Lower of two signal lows; actual entry-to-stop distance1%-4%; entry gross<=250 USDT, ordinary stop loss including costs<=2.5 USDT and available-cash constraint |
| Target/time |2R price distance or open six bars after entry; no trailing/additions |
| Execution | Opening stop gap first, opening target gap at target without favorable improvement, then time exit; intrabar both-hit stop first |
| Reentry/terminal | No entry in exit bar; liquidate at last permitted historical close |
| Per-side fee/slippage |10/5 bps conservative; 15/10 stress; 25/15 severe |

The no-flow ablation removes only the two imbalance conditions. It preserves all price, stop, time, selection and cash rules. The capped passive comparator invests125 USDT gross per asset at inception and retains the remaining cash after fees;250 is an **initial entry-gross cap**, not a continuously rebalanced exposure ceiling.

## Actual historical result

Aug1–Oct18,2026 is **already-inspected development history**, not OOS or untouched validation.158 previously retained official files contain70,815,420 trades and9484h bars. No source download or Oct19-Jan17 protected price read occurred.

| Book | Costs | Closed trades | Net USDT | Fees USDT | Maximum4h close-mark DD |
|---|---|---:|---:|---:|---:|
| candidate | conservative | 1 | +3.309996 | 0.324328 | 0.282387% |
| candidate | stress | 1 | +2.648267 | 0.431512 | 0.250600% |
| candidate | severe | 1 | +1.895455 | 0.614943 | 0.214399% |
| price_only | conservative | 24 | -1.312782 | 6.685518 | 1.574040% |
| price_only | stress | 24 | -6.255051 | 9.022565 | 1.910656% |
| price_only | severe | 24 | -12.367020 | 12.987974 | 2.712564% |

Mean net per closed trade equals the candidate net because it has one trade. The price-only means are -0.054699,-0.260627 and -0.515293 USDT under conservative/stress/severe respectively. All candidate PnL occurred in September; August and October were flat. Full monthly results, fills, execution references and close marks are retained in the packet.

| Passive book | Conservative net | Stress net | Severe net | Stress close-mark DD |
|---|---:|---:|---:|---:|
| BTCUSDT | +150.900813 | +149.600311 | +147.654424 | 7.472983% |
| ETHUSDT | +145.091273 | +143.802378 | +141.873859 | 15.779748% |
| full_50_50 | +147.996043 | +146.701345 | +144.764141 | 11.392172% |
| capped_50_50 | +74.072019 | +73.460698 | +72.563026 | 6.713239% |
| cash | +0.000000 | +0.000000 | +0.000000 | 0.000000% |

| Prespecified gate | Outcome |
|---|---|
| Candidate net>0 under all three costs | Pass |
| Stress net>identical no-flow control | Pass |
| Stress net>capped passive50/50 | **Fail** |
| Stress close-mark DD<=capped passive50/50 | Pass |

The exact contract is terminal without retuning. Rejection follows the recorded financial gate, not an arbitrary minimum trade count. One profitable trade and the losing24-trade ablation do not establish statistically reliable alpha or incremental prediction. No broad impossibility claim about other strategies follows.

## Verification and evidence

Native Laptop2 DESKTOP-F4SA4VL used the existing Python3.12.10 environment. The four executable/contract Git blobs at source commit `2ea3d19d465fd075e6c7a23bb6e41b1ff6dee06f` matched before execution and their SHA256 identities still matched afterward.

- 9 execution unit checks and14 independent synthetic/corruption checks passed.
- All 158 raw files and receipts matched the pinned capture. Vectorized quote aggregation matched a separate scalar csv/Decimal implementation over every raw row. All 948 OHLCV bars matched the retained independent source QA.
- Independently authored Decimal replay, with no producer import, verified all 6 active and 15 passive reports,9954 close marks, signals, fills, cash, fees, drawdown, monthly PnL and exact decision gates.
- The initial480-second bounded feature stage checkpointed147 files. One180-second continuation reused those exact-source checkpoints and completed11newfiles in58.969 seconds. It did not repeat execution tests or retune a rule. Final state was `completed_verified` at2026-10-20T14:28:13.676591Z.
- The 20-entry compressed packet was decoded, every original byte count/SHA256 checked against native files, and its persisted Git blob reproduced exactly.

Packet bytes:338717; SHA256 `4fdcea89d7069931f21a13d57180cc5e7696e977141b8d78a892c6d2fde030a7`; Git blob `254ddb602d1d17b1aed2a1c566ba313f302ffc35`. Result canonical digest: `544ae621cf0b3b8064c7eda9e8651e99e2bb0eb2aa7c0e76274adfdba2610ace`.

Evidence:
- [summary](../evidence/label-collapse-reclaim-20261020/summary.json)
- [full compressed native packet](../evidence/label-collapse-reclaim-20261020/evidence-packet.json)
- [packet validation](../evidence/label-collapse-reclaim-20261020/packet-validation.json)
- [final AI Room decision](../evidence/label-collapse-reclaim-20261020/ai-room-final-decision.json)
- [real AI Room consultation](../evidence/label-collapse-reclaim-20261020/ai-room-review.json)
- [earlier pre-economic checkpoint](../evidence/label-collapse-reclaim-20261020/pre-economic-native-checkpoint.json)

Each packet entry decodes with `zlib.decompress(base64.b64decode(entry["zlib_base64"]))`; verify the resulting bytes and SHA256. The packet contains original features, financial results, independent QA, logs and receipts. Same-input arithmetic verification is not independent exchange/provider attestation or an authenticated Manager worker lease.

## Actual AI contributions and source interpretation

DeepSeek supplied two fresh UI answers in the real room, including exact-system round `8672db1c07e24e33985ba5a6ca9dc346`, answer SHA256 `47345f50b318de40bb2a1cccd748c0c8b144d672820a4666c8982cae74bf2517`. It rejected Demo admission and accepted only a limited diagnostic. Codex agent `/root/demo_novelty_inventory` supplied the fixed design and reviewed implementation. Separate critic `/root/demo_strategy_critic` required ablation/cost-inclusive risk, authored independent Decimal QA and confirmed the final gate failure. Their identities are explicitly recorded; they are not Claude/Perplexity. Those providers' fresh requests were unsubmitted because actual access was blocked. No circumvention or fabricated vote occurred.

DeepSeek's three alleged mechanical omissions were checked: the positive1%-4% stop distance implies E>S, quantity<=250/E caps notional, and an explicit opening target-gap branch exists. Its suggested arbitrary20-trade minimum was not adopted.

[Bybit REST](https://bybit-exchange.github.io/docs/v5/market/recent-trade) and [WebSocket](https://bybit-exchange.github.io/docs/v5/websocket/public/trade) define their API side fields as taker side. Exact six-column historical CSV mapping remains unresolved. The tested absolute publisher-label feature is globally label-swap invariant; no taker-direction/L2 absorption claim is made. This algebra does not certify arbitrary row-level label errors.

[Kitron and Wengrowicz,2026](https://arxiv.org/abs/2608.21888) report about1.3 bps gross15-minute reversal edge versus5 bps round-trip benchmark cost. Their research does not validate this4h adaptation or clear our approximate30/50/80 bps round-trip assumptions.

The original dual-rotation system and protected Oct19-Jan17 study, Laptop1 Paper install/profile/journal and existing closed hypotheses are unchanged. No new monitor, schedule, watchdog, real order or Demo admission was created. Live=false;orders=0.
