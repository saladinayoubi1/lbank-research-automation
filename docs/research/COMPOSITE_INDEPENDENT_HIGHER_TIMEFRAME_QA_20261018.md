# Independent composite higher-timeframe context QA

Scope: DATA-20/21 -> VAL-40 -> QA-41; Research only, Live=false.

The current composite producer and QA replay previously shared all four 1h/4h
context equations and their as-of join. Repeating that implementation could not
detect a shared premature-candle or context-equation error. The existing default
VAL-40 evaluator now compares every observed context against a separate stdlib
reference before generating any signal or financial replay.

## What is reconstructed independently

- `h1_compression`: current six-hour normalized high-low mean versus the preceding
  48-hour median times 0.8.
- `h1_vol_ok`: current normalized high-low range versus the preceding 72-hour
  median times 1.65. This is a volatility/range gate, not traded volume.
- `h4_up`: current close above the preceding 12-bar close median, with current low
  above the eight lows ending four 4h bars earlier.
- `h4_range`: current close inside the preceding 12-bar high-low envelope.

No pandas rolling/join or producer helper is used by the reference. Each source
is visible at its UTC open plus its complete interval, including exact-close
matches. A source with insufficient rolling history yields false; no closed
source yields missing/null. Receipts retain source prefixes, feature masks,
exact source indices for every 15m decision, full dataset identity, source commit,
reference-code hash and a digest of every compared context value. Future source
rows cannot change an earlier source-prefix identity.

The producer verifier checks receipt binding, complete coverage, indices and
value digests without importing pandas. Separate existing QA execution runs the
reference against its actual raw inputs again and compares the full artifact.
Hashes alone are not exchange authentication or an independent market source.

New physical executions require requalification v3 with both symbol audits and
the v2-era emitted-signal traces. Historical v1/v2 receipts remain readable with
their original limitations. The nested legacy trace's false independent-as-of
flag describes that trace alone; the separate higher-timeframe receipt certifies
only the four fields above. No signal equation or 15m feature is certified by it.

## Actual native feature-only archive evidence

The implementation, frozen request, six raw input hashes and code hashes were
committed **before** this audit at
`c8ccce5c9c165d3f6b43240e4f6885d631c07e27`. The raw 15m archive identities match
the earlier V119 evidence. Exact existing 1h/4h files were separately hashed
before committing the request. None was resampled from 15m substitutes.

On Laptop2, the existing archive loader and unchanged main composite feature
builder were used, followed by independent reference reconstruction:

| Symbol | 15m decision rows | 1h source rows | 4h source rows | Compared context cells | Mismatches |
| --- | ---: | ---: | ---: | ---: | ---: |
| ETHUSDT | 128544 | 32136 | 8034 | 514176 | 0 |
| BTCUSDT | 128544 | 32136 | 8034 | 514176 | 0 |

Raw source history is 2022-12-01 through 2026-07-31, already inspected. Decision
close timestamps run from 2022-12-01T00:15:00Z through 2026-08-01T00:00:00Z. The
1,028,352 comparisons include expected warmup/missing states; they are not
independent trades or evidence of economic edge. No context mismatch was found.
This establishes agreement for these current equations/joins on these exact
inputs; it does not certify every historical Elliott implementation.

Result digest:
`0f35ecfa62fecc22a460d46071081934c9cc62a0761dd111d92059ed26ed6c12`.
Request/result are committed in `research/higher_timeframe_qa/`. Full per-decision
receipts remain in the isolated native directory:
`E:\NEXUS-QA\composite-higher-timeframe-20261018\physical-higher-timeframe-feature-qa`.
The committed summary identifies both full receipt hashes. The CLI and request
reproduce them from pinned inputs and the immutable execution source SHA.
The full native stdout JSON was reconciled locally and its request/result digests
matched exactly. A subsequent remote file-read disconnected; no study was rerun.

The CLI explicitly disables signal generation and backtesting. There was no
V118/V119 replay, new strategy/frontier selection, threshold/stop/entry change,
financial recomputation, protected future-window consumption or new monitoring.
The source is unchanged main feature code, not a full recursive Elliott counter
or a certification of old V11/V119 signal implementations.

## Validation and operational limits

Native focused verification: **112 tests passed in 28.57s**. Coverage includes
the real default evaluator through the existing producer verifier and QA task/
receipt, early-producer-join fault injection, future-tail mutations (including
currently unclosed higher bars), exact 1h/4h cutoff boundaries, missing/warmup
states, corrupted/resigned receipts, legacy v1/v2 reading and lossless bounded
3072-bar all-signals transport with both complete v3 audits. The independent fill
oracle's fault-injection fixture stubs only context reconstruction to isolate its
numerical check; real context reconstruction is tested separately.

Required protected CI runs on the final PR head. No application is installed,
no current Paper journal changes, no additional Paper writer exists and no
economic qualification, registry admission or Demo/Live authority is granted.
The legacy composite monetary model remains its actual 10000-USDT-per-symbol
research model. Shared500 execution, full Elliott structure, 15m/peer-feature and
signal-equation independence, prospective capture and positive untouched economic
evidence remain separate work. Issues #2007/#2672 remain open.
