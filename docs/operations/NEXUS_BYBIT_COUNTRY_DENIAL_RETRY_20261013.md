# Bybit country-denial retry boundary — 2026-10-13

The completed owner Paper workflow 38340837500 on main a5a7b85f65bb7d213fded62069c05d78a3419add persisted a verified checkpoint, but its loop remains WAITING_FOR_FRESH_CELLS with 7/12 source-bound cells and 36 expected lanes. Four 4h cells have SOURCE_MISMATCH; SOLUSDT:minute15 is blocked. A successful workflow/checkpoint does not certify complete data readiness.

Independent read-only Laptop 1 verification validated the checkpoint module Git blob cbf8009b3c0275c99048a4ace213ea95bfaf7bf0, latest pointer, current and previous manifests, compressed archive and loop self-digest. The latest pointer was unchanged during inspection:

- Manifest SHA-256: 1434b38e111f2045429f4808e178f7dfb33a73c0764a7ee35cfc1c17d6fe4720.
- Archive: 631620 bytes, SHA-256 9056cb12d90e72a418b3b14f43df0c0a6c52ab983177c7332913c4f5add04e7a.
- Previous run 38331369070, previous manifest SHA-256 534f3401b06fc64337744aa92e4558796431d585a535e0b29067cb1c39b678a1.
- Loop digest: 5b47926246cd2990cf32574c14f48deb8409c89de30668c00f755789e5f84d22.
- Live and automatic strategy promotion remain disabled; research-health dispatch is false.

The existing diagnostic log explicitly classified HTTP403 edge_country_restricted from the approved official hosts. In the fetcher, this classification also incremented the retry counter reserved for unclassified errors. When every host was denied, the same request could repeat over five rounds with 52 seconds of sleeps. On the current EEA selection, that means up to 15 denied requests for one logical page. This change removes confirmed country denials from that retry counter. It keeps the existing reviewed single pass across approved hosts, preserves retries for genuinely unclassified transient 403s, retains diagnostic classification and raises when no verified canonical response is available. The terminal failure also closes its session.

The added regressions cover all-host denial in GLOBAL and EEA, mixed country/unclassified responses in both orders, and a country denial encountered after an initially unclassified retry. The original valid-host, rate/region/compliance refusal, source-validation and unclassified recovery cases remain required. On native Laptop 1, pytest 9.1.1 was installed with the repository's pinned test dependencies in an isolated QA target. The old source failed all five new cases while its 15 existing cases passed. The corrected source passed all 20 cases. An autouse test guard blocked real network requests throughout; no live API probe or completed backtest was run. The installed application and previously verified accounting environment were not modified.

This is a request-suppression fix, not restored feed access. There are no new endpoints, selectors, proxy routes, credentials, fabricated candles, stale-source acceptance, old receipt relabelling, checkpoint writes, owner reinstall, completed numerical replay or writer-authority changes. Permitted official source availability, all twelve exact-source closed-bar cells and physical single-writer commissioning remain separate acceptance gates under #1952 and #2454.

## Contract-only source-push integration

The existing multi-pair discovery workflow watches the shared fetcher on main pushes. Its archive preparer, physical discovery, fresh runtime snapshot and requalification previously allowed these pushes to execute; the two publishers used successful-parent/output conditions without a separate event boundary. A source-only retry fix could therefore lease research workers or regenerate search work when exact-source exhaustion reuse missed.

All six non-contract jobs now require workflow_dispatch on refs/heads/main. This includes hosted archive/wheelhouse preparation and both evidence publishers. Push and pull-request contract CI remain active, including the expanded shared event-policy regression. The standalone workflow retains its reviewed one-shot dispatch surface; central reviewed routing remains available. Existing job/permission inventories, physical lane, exact source artifacts, source-SHA and exhaustion verification, fresh runtime requirements and publisher parent/output conditions are preserved.

Nine event-policy tests pass, covering all non-contract jobs on push, PR, dispatch, schedule, repository_dispatch and workflow_run, including feature refs and successful-parent/stale-output contexts. Failed, cancelled, skipped or explicit no-work parents cannot publish. Twenty existing multi-pair workflow contract checks also pass, including exact job inventory, source transport, archive verification, runtime binding, exhaustion certification and native bootstrap. The existing policy, trust-boundary and immutable-action validators pass for the changed workflow. The retry implementation/test blobs and their 20-case native QA receipt remain unchanged.

No archive acquisition, physical search, fresh market request, producer replay, checkpoint write or new proof publication is performed by this source preparation. Merge still requires the resulting exact-head CI, then verification that the main-push execution jobs are skipped. Reverting the data fix should retain these event guards; reverting the guards restores the source-push replay hazard.

