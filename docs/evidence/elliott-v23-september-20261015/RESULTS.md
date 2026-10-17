# NEXUS Elliott V23 — official September 2026 monthly public raw-trade archive acquisition

**Date:** 2026-10-15. **Source stage:** `PASS_TWO_SEPTEMBER_ARCHIVES_TRANSPORT_ONLY`. **Not a completed Elliott strategy validation, candle model acceptance, or Demo authorization.**

## Verified native execution on Laptop2

BTCUSDT and ETHUSDT September 2026 monthly raw Spot trade gzips were downloaded *directly* from `https://public.bybit.com/spot` into a fresh isolated root `E:\NEXUS-QA\elliott-v23-september-official-20261015`. Both original source HEAD responses were HTTP 200; no credentials, redirection, private endpoint or retry was used.

| Official raw source file | Compressed bytes | CSV newline count including header | SHA-256 |
|---|---:|---:|---|
| `BTCUSDT-2026-09.csv.gz` | 128,140,828 | 19,355,496 | `b45655ffb9069e97925905d51fbfd02fe0ff8ef0298d7ecfc501111110fd64d8` |
| `ETHUSDT-2026-09.csv.gz` | 64,310,937 | 7,884,597 | `ec85644bf1de1e7de9dc0906a8042ff4d1517a33a05233ee797b96951b5ce044` |

The capture verified HTTP `Content-Length`, streamed SHA-256, re-read file SHA-256, full gzip CRC/footer, and recorded source URL, fetch time and `Last-Modified`. CSV header is `id,timestamp,price,volume,side`. The complete gzip byte streams were read for integrity but **not** subjected to individual per-trade ID/date/price/side checks or a full Bybit v2 candle reconstruction.

### Source provenance correction, not data repair

The first-run V23 script inadvertently inherited the literal completion label `PASS_TWO_AUGUST_ARCHIVES_TRANSPORT_ONLY` from V22 even though its month, filenames, source URLs and downloaded bytes were correctly **September**. Instead of changing any archive bytes or concealing the mistake:

1. Left the original `CAPTURE_RECEIPT.json` untouched on Laptop2.
2. Corrected the script to use the fixed September label and added a September-specific assertion in `tests/test_nexus_elliott_v23_september_transport.py`.
3. Executed [the independent offline receipt checker](verify_september_capture_provenance.py), rehashing both actual gzip files, matching the real disk byte sizes and expected September official URLs, and creating a separate `CORRECTED_CAPTURE_RECEIPT.json`.
4. Saved the exact corrected evidence at [NATIVE_SEPTEMBER_MONTHLY_CAPTURE_QA.json](NATIVE_SEPTEMBER_MONTHLY_CAPTURE_QA.json). It records original native receipt SHA-256 `0d9f7cd0e93e1da5a253e0d32b8bfe5cae904e22d1611bbc8cda055a9a4fd9f4`, the former label and why it was corrected.

All **4/4** dedicated V23 synthetic gzip/truncation, identity and non-overwrite safety regressions passed on Laptop2 after the correction.

## Study boundaries and next stage

Both August 2026 monthly archives from V22 and both September monthly archives from V23 are now captured and raw-byte SHA-bound; October 8 BTC/ETH daily archives were captured earlier in V21. The **October 9–14** daily files for both symbols remained listed on the public source but were not acquired here (12 files). October 15 was not listed at the previous verification and cannot be assumed available while that UTC day is in progress (2 more potential files). These are **14 remaining source files** for the prior candidate timeline through October 15, subject to official availability.

Even with the four monthly raw files, the existing V19 July/Aug pilot and V20 Sep/Oct segment must **not** be simply spliced. The correct path is complete raw-source acquisition, bounded original-trade-row source validation, and one **new model-v2 uniform candle rebuild** with verified date/15m/1h/4h continuity. The frozen V17 evaluation window starts October 16 UTC, and no genuine future outcome/edge has yet been measured.

No new market backtest, order, signal, Demo promotion, Live Trading, changes to the 500-USDT Paper account, Laptop1 application, prior raw sources or paused VPS. GitHub Draft PR #2673 remains the research review gate.

**Native artifacts:** [source capture](capture_september_monthly.py), [SHA and correction audit](verify_september_capture_provenance.py), and [immutable September capture machine record](NATIVE_SEPTEMBER_MONTHLY_CAPTURE_QA.json).
