# NEXUS Elliott V75 — first prospective Bybit daily archive is still incomplete

**Evaluated:** 2026-10-16 14:05:32 UTC. **Mode:** one-shot, research-only preflight on Laptop2 `DESKTOP-F4SA4VL`. **No downloading**, no orders, no paper or demo mutation, no changes to the frozen V52 protocol.

## Actual atomic operation

V74's full composite legacy prefix tests remain valid at SHA `2eebabb5c26632e7fbc39f8d7224378219b34310`: **524/524** native Elliott unittest success and hosted Windows/macOS/Ubuntu **success**. The latest separate public Bybit Spot top-of-book transport readiness diagnostic is only a transport observation, not a source-bound Elliott signal or V52 prospective score.

V75 ran the **unchanged existing** `research/elliott_v58_tls_source_capture/capture_tls_v58.py::capture_completed_spot_day_tls` and `research/elliott_v55_source_intake/build_official_day_v55.py::build_verified_1m_day` for **both BTCUSDT and ETHUSDT** on the first protocol source day `2026-10-16T00:00:00Z`, using the machine's actual UTC clock (not a synthetic test clock or date override). It passed a never-usable output destination for each pair and intercepted the HTTPS client constructor to prove that the day-complete gate rejected **before constructing any remote network connection**. V55's exact original source URL declarations were supplied, but the archive files were intentionally not present and never downloaded.

| Bybit Spot pair | V58 early physical TLS source capture | V55 early 1m physical ingestion | New source file | Forward scoring |
|---|---|---|---|---|
| BTCUSDT | **DENIED — UTC day not complete** | **DENIED — UTC day not complete** | None | None |
| ETHUSDT | **DENIED — UTC day not complete** | **DENIED — UTC day not complete** | None | None |

**V75 isolated physical receipt:** `E:\NEXUS-QA\elliott-v75-v52-source-preflight-20261016\V75_BOTH_SYMBOLS_PREMATURE_DAY_GATES.json`, SHA256 `2d95513d73762aab11d5482305a83b27c0ce045ecdff4738a36286623fdc896d`. A one-shot on-device `preflight_v75.py` in the same scratch directory made the exact production gate calls without scheduling or downloading. Process exited `0` with `INCOMPLETE_DAY_REJECTED_AS_REQUIRED`. Verified frozen `protocol_v52.json` SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`, unchanged.

## Frozen UTC scoring boundaries — do not backdate

- The first permitted source daily UTC day is **October 16, 2026**, but **cannot finish before October 17 at 00:00 UTC**; archive publication/physical receipt can be later.
- October 16–17 are **warmup only** and excluded from scientific forward scoring.
- The first *scored* UTC daily source date is **October 18, 2026**, whose full official daily archive **cannot finish before October 19 at 00:00 UTC**, and may be published later. This is not permission to claim the 18th source was known on the 18th or that hypothetical signals could be filled at earlier timestamps.
- Frozen prospective scoring ends at **November 16, 2026 00:00 UTC** (exclusive). Only previously defined strict original V52 15m parent / 3m child hierarchy, exact source cryptographic evidence, and V59/V60/V69 arrival-time validation may produce a later **research diagnostic**; output contract strictly prohibits entry, paper eligibility, Live, orders, filled P/L, or automatic Demo promotion.

## Subsequent permitted operational step

Only **after** the corresponding daily UTC day has completed: capture each public Bybit Spot `<symbol>_YYYY-MM-DD.csv.gz` over direct TLS using the existing V58 exact-URL no-redirect one-shot capture to a **new immutable isolated research folder**, ensure genuine HTTPS/receipt hashes, then independently reconstruct V55/V56 one-minute bars and pass V52/V57/V59/V60/V69 source availability gates. Capture dates separately and never fabricate missing minute bars. If an archive is not physically published yet, report no availability and end the atomic step; do not replay prior October data as prospective evidence.

**Scientific decision:** No profitable new Elliott signal, no Demo position and no change in the old V70 `REJECT_PROMOTION_OUT_OF_SAMPLE_HISTORICAL_LOSSES` determination. PR #2673 remains Draft/unmerged; Laptop1 and VPS unchanged, Live disabled.
