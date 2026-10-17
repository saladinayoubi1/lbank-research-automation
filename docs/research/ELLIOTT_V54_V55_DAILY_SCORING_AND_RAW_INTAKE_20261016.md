# Elliott V54–V55 — Daily Score Exclusivity & Verified Raw Source Intake

**Research date:** 2026-10-16 UTC. **Device:** Laptop2 research QA only. **Repository:** Draft PR #2673, not merged. These changes do not touch Laptop1 Demo, Paper journal, paused VPS or Live.

## V54: correct prospective-scoring leakage

The prior V53 daily scanner could count geometrically acceptable **warm-up** parents (last pivot confirmed before Oct 18 UTC) as prospective events, and repeat-count old confirmed candidates on subsequent UTC daily snapshots. V54 corrects this:

- Confirm and timestamp the **last 15m parent pivot** from closed right-hand bars;
- classify parent geometry completed **before Oct 18 00:00 UTC** as excluded warm-up (never scored);
- classify parent geometry **already counted by a prior daily decision close** as excluded historical/replayed;
- count/evaluate an eligible candidate only when its first observable last-parent confirmation falls inside the **new UTC daily score interval**;
- preserve a separate diagnostic count of excluded warm-up and previously-scored geometry candidates. No retroactive price-based pruning, no orders.

Three adversarial regression tests use deliberately injected synthetic parent geometry (no real market witness claim): warm-up geometry cannot score on Oct 18; cannot become eligible by replaying on Oct 20; a post-start parent candidate is reported once on Oct 20 and excluded on Oct 21.

After updating `research/elliott_v53_prospective_scan/scan_verified_v53.py` and adding `research/elliott_v54_score_exclusivity/test_score_exclusivity_v54.py`, the full Elliott regression suite returned **355/355 PASS** on Laptop2 at git HEAD `47f9ca022688525f067b3c90867118327f8668cd`, exit code 0. Machine log: `E:\NEXUS-QA\elliott-v54-score-exclusivity-20261016\NATIVE_V54_TESTS.txt`.

## V55: deterministic offline source-day production, followed by an independent oracle

The separate `research/elliott_v55_source_intake/build_official_day_v55.py` is a **manual/offline** source processor. It does not contact or authenticate the remote archive itself. A future operator must provide the real physical, correctly named official Bybit public Spot BTC/ETH `.csv.gz` archive with an exact declared public URL and preserved capture evidence; the URL string alone is not proof of its origin.

Once the entire source UTC day **has actually ended** (no override allowed for production), V55:
- refuses stale/future out-of-window dates, incorrect URL/name/symbol, existing output directory or partial source days;
- opens and consumes all physical trade rows in timestamp order, preserving original row ordering for tied timestamps;
- refuses malformed or missing trade-bearing minutes instead of interpolating;
- creates a brand-new immutable-receipt folder with exactly 1,440 UTC OPEN-labelled minute OHLCV/trade-count bars;
- independently calls the prior V52 full archive SHA and raw-to-minute numerical oracle, which reopens the compressed archive and verifies each of **7,200 numeric OHLCV fields** and **1,440 trade counts** before marking a real source day as `PASS_OFFLINE_INDEPENDENT_1M_SOURCE_ONLY`;
- records both SHA-256 files, declared URL, the fact that the URL **was not remotely authenticated by this local parser**, and full source QA evidence. No signals, Demo eligibility, Live or P/L.

Synthetic time override is allowed exclusively under explicitly marked `fixture_mode=true`, restricted to the OS temp folder and always emits `SYNTHETIC_TEST_ONLY`, never a real market PASS.

**V55 offline synthetic/adversarial tests: 12/12 PASS.** Tests include a physical 1,440-trade synthetic future-day positive oracle, rejected incomplete day, historical day, wrong archive/URL, source alteration, malformed timestamp/price, missing minute, overwrite attempts and forbidden production clock override.

## Next dependency

At this registration time the Oct 16 UTC source day was not yet complete. **There are no V55-verified new official Bybit source-day receipts, no scored prospective Elliott candidates, no new trade outcomes.** No scheduled collection task, downloader, monitor or autonomous live process was started. Once physical official archives become available, V55 can run after day closure and V53 can score only the frozen eligible new daily interval. Keep the PR Draft until hosted CI and independent QA are verified.

**Safety invariant:** research-only, Bybit BTC/ETH public Spot source, demo untouched, Live disabled, paper eligibility false, prospective trade P/L null.
