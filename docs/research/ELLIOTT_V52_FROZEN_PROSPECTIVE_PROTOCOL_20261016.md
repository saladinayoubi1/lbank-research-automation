# NEXUS Elliott V52 — Frozen prospective evidence admission, not trading

**Registered:** 2026-10-16 UTC, after the start of the original V17 prospective window (00:00 UTC). **This is a new, later-starting scored sub-study**, not a claim that October 16 early bars were unobserved before registration.  
**Repo:** Draft PR #2673; GH source of truth. **Device:** isolated Laptop2 research checkout.  
**Deployment boundary:** no exchange orders, no Demo/Paper promotion, Live disabled, laptop1 and VPS untouched.

## Freeze protocol and scientific admission

The exact versioned protocol file is `research/elliott_v52_prospective/protocol_v52.json`, frozen SHA-256:

`f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`

The companion code independently rehashes the full protocol file and rejects any byte change. Parameters are **fixed from reviewed prior historical evidence**, not optimized on future results.

| Scope | Fixed decision |
|---|---|
| Bybit source | Official public **Spot** raw trade daily archives, only BTCUSDT and ETHUSDT |
| Market capture interval | `2026-10-16 00:00 UTC` inclusive through `2026-11-16 00:00 UTC` exclusive |
| **Warm-up, not scored** | Oct 16 and Oct 17 UTC, explicitly excluded because protocol registration occurred after Oct 16 started and continuous historical context is needed |
| **First eligible score timestamp** | `2026-10-18 00:00 UTC` |
| Score end | `2026-11-16 00:00 UTC` exclusive |
| Source bars | Complete, contiguous UTC OPEN-labelled **1m** from daily official trade streams, unfilled; preserve exact timestamps and physical CSV row tie order |
| Degree design | Strict width-3 15m parent, strict width-3 1m provenance, strict width-1 3m child (`15m / 5`), fixed `5-3-5-3-5` + `5-3-5` zigzag cardinality |
| Ambiguity, missing bars, incomplete days | **Reject / no synthetic fill / no retrospective pruning** |
| Output | Source integrity and bounded research-wave diagnostics only; **no signal, order, Demo eligibility, P/L or complete recursive Elliott claim** |

A daily archive can only be audited **after the entire UTC day ends**. A post-day research replay of earlier intraday times is not a claim that the system had the complete daily archive then, and is never treated as live fill or executable order evidence.

## Independently reproducible source-day auditor

`research/elliott_v52_prospective/prospective_v52.py` validates physical gzip + 1m parquet SHA pins, exact daily filename, Bybit public Spot trade schema, monotonic raw millisecond ordering, valid Decimal price/volume, complete coverage of all **1,440** UTC minutes (no interpolation), exact 1m UTC timestamps, all **7,200** independently rebuilt numeric OHLCV values, and **1,440** per-minute trade counts. A missing/mismatched field blocks admission. It rejects data before Oct 16, scoring events before Oct 18, stale/future parent confirmations, invalid timezone and end-of-window events. These are **data-accuracy** gates, not trading profitability tests.

The validator explicitly permits clock injection solely for deterministic tests; real execution omits the override and uses the operating system's UTC clock. An SHA-256 value alone cannot establish exchange provenance; capture must still preserve the official archive acquisition URL and evidence. The auditor does not fetch the archive or run unsupervised in the background.

## Test and real-data status

The isolated Laptop2 V52 suite exercised **17 deterministic unit cases**, including a completely synthetic future-day OHLCV positive oracle and adversarial historical archive, too-early day, byte-mutated protocol, changed source SHA, missing minute, changed price/volume/count, naive timestamp and future parent confirmation cases: **17/17 PASS**. Native GitHub `tests/test_nexus_elliott_v52_prospective.py` enrolls those guards in the broader Elliott regression suite.

**No official Oct 16+ market archive has been audited or scored by V52 at registration. No unseen Elliott pattern, profitable strategy, P/L, orders or executable future entries are asserted.**

## Next controlled experiment

Once a verified post-registration official daily archive is available, independently verify 1m raw-trade completeness and origin. Run an **as-of closed-bar-only bounded parent/child diagnostic** with **no scoring before Oct 18**, no time-window/width optimization and no P/L-derived pruning. Record fixed rules, real source hashes, rejection counts, first *observable* candidate decision time and independent test log. Before any distinct Demo gate, collect authentic post-signal bid/ask quotes and conservative fill/fee/slippage provenance, stop/TP ordering and negative-case audit.

**Invariant:** `entry_signal=false`, `paper_eligible=false`, `live_enabled=false`, `auto_demo=false`, `complete_recursive_elliott=false`, `new_pnl=null`.
