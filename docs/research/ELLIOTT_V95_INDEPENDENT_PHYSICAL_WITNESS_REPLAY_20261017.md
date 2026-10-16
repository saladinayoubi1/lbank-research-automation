# NEXUS Elliott V95 — independent source-backed terminal pivot replay

**Scope: physically verify the lowest available 1m strict pivot witnesses, NOT prove Elliott recursion or an executable trading edge.** This is a read-only historical research audit, not a new prospective experiment and not a trade backtest. PR #2673 must remain Draft/unmerged, Live disabled, no Bybit Demo orders, V52 future scoring unchanged, Laptop1 install untouched and VPS work postponed.

## Upstream results and independent witness implementation

V88 pre-registered the **BTCUSDT/ETHUSDT July 1–14, 2024 UTC** calendar *before* the V89 archive fetch. V89 sealed 28 authentic official Binance Spot 1m daily ZIP files, CHECKSUM files and 40,320 total complete 1m OHLC rows. V90 then source-bound the candidate center and right-confirmation times; V91/V93 retained their per-leg primitive and rejection receipts. V95 reopens every original source ZIP and official CHECKSUM using V90's source loader, which validates the V88/V89 Git-committed source receipts again.

Unlike a mere V90/V91 JSON audit, `research/elliott_v95_physical_witness/witness_v95.py` contains a **second, independently coded** strict width-1 1m extremum detector. It consumes the full physically closed decision-time OHLC prefix, checks 60-second alignment, gapless contiguous timestamps, finite positive Decimal OHLC, exact left/right strict extrema, explicit dual high-and-low candle abstentions, and confirmation only after the right neighbor's candle closes. Every strict primitive is preserved; same-kind or inconvenient points are never dropped.

The independent detector is **not implemented by calling V86's detector**. For each of the existing eight *unchanged* five-leg V90 cases, V95 compares every reported V86 interior pivot **object in its original order**, explicit ambiguity centers, counts, original six source-bound parent/child vertex prices and confirmation timestamps, against its own direct raw-source reconstruction. If any historical witness differs, the audit fails rather than rewriting the old report. Individual per-leg pivot lists are represented in the output by SHA-256 hashes of their canonical content, original counts and explicit dual-extremum timestamps; full raw original source stays on Laptop2.

## Verified V95 results on the preinspected historical interval

| Metric | BTCUSDT | ETHUSDT | Both |
|---|---:|---:|---:|
| Official 1m candles reloaded and checked | **20,160** | **20,160** | **40,320** |
| Original candidate five-leg structures | 6 | 2 | **8** |
| Candidates whose every 1m terminal pivot matched | **6/6** | **2/2** | **8/8** |
| Candidate confirmations first observed in week A | 0 | 0 | 0 |
| Candidate confirmations first observed in week B | 6 | 2 | 8 |
| Independently proven higher-degree Elliott tree | **0** | **0** | **0** |
| Qualified trading entries / Bybit Demo orders | **0** | **0** | **0** |

A **physical 1m terminal pivot is not yet an authenticated lower-degree Elliott wave**. Matching V86 and an independent primitive detector supports the historical source-observation process, not the unproven higher-order grammar. The original one BTC necessary *outer geometry* candidate still does not pass full 5-3-5-3-5 nested proof; the source-wide counts remain mismatched and an OHLC-order ambiguity remains. Elliott profitability remains entirely unestablished.

## Evidence and fail-closed scope

- Frozen V88 preregistration: `fae91774a57f887fc14122b4b1c74a26f6c7ad5daac28488c4e440b836523899`
- V89 complete 28-ZIP source evidence: `e1c3988f6112ccd12883e35704b63024dc56bf52cc7a38f36ef42e743c2ed7df`
- V90 source-bound candidate evidence: `1db892fcfe75699ded97151501e538d04c2fd8ae4084765c9e1cd4aa9fd4683a`
- V93 immutable proof-debt evidence: `fa55b3dd524fba9de7546fba8ea110db30a1e7b9bb8507ff7c79325ad8a35f58`
- Full original V95 local audit: `E:\NEXUS-QA\elliott-v95-physical-witness-20261017\V95_PHYSICAL_SOURCE_WITNESS_AUDIT.json`
- Source: Binance official historical research-only archive; not live or Bybit Demo quote/feed data. No net realized or simulated trading P/L exists.

## Research conclusion

**V95 source-level 1m witness fidelity: verified on all eight original candidates. Full multi-degree wave / pattern-position proof: unproven.** Terminal consistency must not be promoted to full market grammar, and the historical July dates must not be reused as a tuning or claimed forward test. The still missing research task is an independently preregistered **physical candle-backed higher-degree wave builder and pattern-position verifier** evaluated on a new genuinely uninspected/forward sample. Cost/SL/TP/fill contracts and Demo permission remain blocked.

## Verified source and software QA

- Original official archived-source V95 replay: **8/8** historical motive candidates matched byte-for-byte as reconstructed 1m strict internal terminal witness objects; **40,320 complete 1m candles** revalidated; native `V95_AUDIT_EXIT=0`.
- V95 adversarial CI-safe source-observer tests: **17/17 PASS**, native `V95_DEDICATED_EXIT=0`. They cover ordered local extrema, same-candle dual high+low abstention, future-tail invariance, strict right-neighbor close timing, missing/duplicate minutes, NaN/negative OHLC, forged prior pivot, deleted inconvenient pivot, altered endpoint price and unearned entry flag.
- Full Elliott-specific regression on Laptop2: **758/758 PASS**, `Ran 758 tests in 57.580s`, `OK`, native `V95_FULL_EXIT=0`. Local test log SHA-256: `53026da58cc2a8569d2f48a890dec910ba852c48f9965a6b189bee3c04d42c63`.
- Detailed physical witness JSON SHA-256: `3935d6d79f9f50ca873ff1a60afca6467b02d80650b4bfce92f78053be755d4e`. The Git staged JSON is byte-for-byte identical to the source report; raw source archive bytes remain off-repo.
- Before V95, **V94 GitHub Test / Workflow Permissions Policy / Research Evidence Refresh all passed**, confirming the prior hosted-Windows temp-path issue was fixed. V95's own GitHub CI must be assessed independently after push.
