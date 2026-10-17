# NEXUS V83 — Bounded physical impulse geometry audit (research-only)

## Purpose and source
An **additive, non-trading** follow-up to V82, evaluating hard rules for **non-diagonal, non-truncated five-leg motive skeletons** on independently checksum-verified Binance Spot BTCUSDT/ETHUSDT **2024-03-01/02** 1m data. All 15m parent and 3m child source-pivot witness events come from V82 and are independently replayed against V80 raw ZIP hashes; the closed right-hand observation time is kept distinct from the historical pivot center.

The original source of the qualitative rules is Elliott Wave International's impulse/motive grammar, as catalogued in V81. This is **not** a fully recursive 5-3-5-3-5 impulse classifier. No V52 future-scored data, Bybit Demo, or paper journal was modified.

## Rules and consequences
- Explicitly test: wave-2 no origin breach; wave-3 beyond wave-1; wave-4 no overlap with wave-1 price territory **for an ordinary impulse, not diagonal**; wave-5 beyond wave-3 (non-truncation); wave-3 not strictly the shortest absolute price leg. No Fibonacci tuning, pivot deletion, alternate count cherry-picking or score-based rescue.
- The five sequential intervals must respect the envelope of physical 1m high/low from the left pivot to right pivot; this is a conservative interval check, **not proof of intraminute high/low order**.
- A three-leg A-B-C skeleton does **not** prove zigzag (5-3-5), flat (3-3-5), or triangle (3-3-3-3-3); it remains **unclassified**, pending independently confirmed finer subwave witnesses.
- Hard-overlap rejects an ordinary impulse **only**. It is not evidence that a diagonal exists. Any diagonal hypothesis needs separate, preregistered geometry and full subdivision witnesses.

## Physical V83 exploratory result (NOT held-out performance)

| Outcome on both official Binance 2024-03-01/02 source days | BTCUSDT | ETHUSDT |
|---|---:|---:|
| Original V82 parent intervals | 32 | 36 |
| Five-leg skeleton candidates | 1 | 1 |
| Five-leg skeletons passing hard ordinary-impulse geometry | **0** | **0** |
| Three-leg correction skeletons, unresolved family | 1 | 1 |
| All other intervals unresolved | 30 | 34 |
| Hard invalidation | wave-4 overlap; wave-3 shortest | wave-4 overlap |
| Complete recursive wave proof / trades / profit | **none** | **none** |

Detailed audit result, time-labeled candidate vertices, observed rejection reasons, and source receipt hashes are in `docs/evidence/elliott-v83-impulse-geometry-20261016/V83_RESULT.json`. Raw source ZIPs and full V82 pivot traces are kept on Laptop2 in `E:\NEXUS-QA`, not uploaded to the repository.

## QA and limitations
- Executed actual new V83 source-bound read-only audit and SHA-256-bounded result. Interpreter module compilation succeeded.
- **Dedicated V83 synthetic test file was blocked by the remote tool and NOT executed.** This is a known verification gap. Never treat baseline Elliott tests as dedicated V83 proof.
- The established Elliott-focused regression was run separately. Record its final native exit code and outcome before calling it PASS.
- No complete new Elliott classifier, profitable candidate, genuine future forecast or Demo qualification is claimed.
- Research-only, `entry_signal=false`, `paper_eligible=false`, `live_enabled=false`. No V52 change or PR merge.

## Next bounded gate
Independently test V83 on synthetic positive/negative wave-geometry cases (future-pivot, source mismatch, origin breach, wave-3 shortest, wave-4 overlap, source wick and future-tail invariance), then **only** consider a separately isolated, source-attested diagonal/corrective grammar. A diagonal alternative may not be used to retroactively turn rejected historical candidates into wins.
