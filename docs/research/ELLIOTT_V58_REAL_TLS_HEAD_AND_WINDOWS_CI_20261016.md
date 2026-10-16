# Elliott V58 — actual verified HTTPS HEAD probe and Windows CI repair

**When:** 2026-10-16 UTC, source-check Laptop2 DESKTOP-F4SA4VL. Research PR #2673 remains Draft, not merged.

## Windows hosted CI finding and fix

On previous branch HEAD `f61d714a7e77ed236b61906098485f1c2a283fea`, GitHub's full suite passed on **Ubuntu and macOS**, but **Windows failed exactly three repeated instances** of `V55OfflineOfficialIntakeTests.test_no_fixture_writes_outside_os_temp`. The V56 implementation rejected a nonexistent output parent directory before checking that a synthetic fixture target was outside the OS temp directory. This caused the test to receive `existing real output parent directory required` instead of `synthetic fixture must remain in OS temp`, not a trade or source acceptance.

Commit `20ce02241a83b620f7294da1bb80a263d3e47f97` moved the OS-temp safety check before the target parent check. A focused exact Windows laptop test `test_no_fixture_writes_outside_os_temp` passed. No verification guard was weakened.

## Actual external HTTPS handshake

At `2026-10-16T01:25:22.659026Z`, the real Windows research machine performed a **non-downloading HTTPS HEAD** for:

- `https://public.bybit.com/spot/BTCUSDT/BTCUSDT_2026-10-15.csv.gz`
- `https://public.bybit.com/spot/ETHUSDT/ETHUSDT_2026-10-15.csv.gz`

For both, a direct Python system-trust TLS handshake completed, with a nonempty verified peer certificate and **TLS 1.3**. Both **HEAD returned HTTP 404**. Archive bytes received/written: **zero**. The public listings for both symbols, independently inspected in the same session, ended at the Oct 14, 2026 daily filenames. Do not infer when Oct15/Oct16 will be published or whether a GET would have succeeded based on HEAD alone. This read-only probe did **not** enter the prospective dataset.

Local log: `E:\NEXUS-QA\elliott-v58-tls-source-capture-20261016\REAL_HEAD_TLS_HANDSHAKE_20261016.txt`.

## Critical TLS socket fix

The initial V58 implementation attempted `conn.sock.getpeercert()` **after** `conn.getresponse()`. With `Connection: close`, Python's HTTPConnection may immediately clear the connection socket on return, causing false failures even though the TLS handshake had succeeded. The corrected V58 captures a verified peer certificate and TLS version **immediately after explicit `HTTPSConnection.connect()`**, before sending an HTTP request. It still refuses unknown certificate, weak TLS, non-200 HTTP, redirects, malformed gzip, incomplete dates and output overwrite.

Mocked transport tests now simulate a connection whose socket is cleared after `getresponse`, and assert explicit handshake must precede the request: **14/14 V58 tests pass, exit 0**, log `E:\NEXUS-QA\elliott-v58-tls-source-capture-20261016\ISOLATED_V58_TLS_TESTS_HANDSHAKE_FIXED.txt`.

At V58's initial frozen check, **398/398** native Elliott tests passed on the actual research laptop (`NATIVE_V58_398_TESTS.txt`). A fresh full-suite run is required on any later revised HEAD; neither isolated tests nor laptop results replace the hosted Windows CI conclusion.

## Remaining external dependency

Oct16 source day is incomplete until 2026-10-17 00:00 UTC. Even then the official archive may be published later. The TLS transport and declared-source archive proof must be paired with V55's immutable transactional 1m source, V52 independent raw-to-OHLCV verifier and V57 physical receipt reattestation before **Oct18+** scored Elliott evaluation. Neither a successful HEAD nor a registered official URL authenticates CSV bytes that have not actually been received and hashed.

Live disabled, no exchange API keys, no Paper/Demo positions, no P/L assertions; laptop1 and VPS unchanged.
