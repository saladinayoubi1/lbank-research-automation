# NEXUS V94 — Windows GitHub CI report-path recovery

## Why V94 prioritizes CI over the next terminal wave observer

On PR #2673 commit `dc08af84620bae51c5c7e1bf8946c9b21bc0d529`, GitHub workflows **Research Evidence Refresh** and **Workflow Permissions Policy** both succeeded. The **Test** workflow failed on `windows-latest` only; `macos-latest` and `ubuntu-latest` tests succeeded.

Verified failing GitHub Actions workflow run **38971639430**, job **117211158785**. Its pytest summary was **2 failed, 4,895 passed, 20 skipped** on Windows. Both exact failures arose from output `ROOT.mkdir(parents=True)`:
- `test_nexus_elliott_v92_execution_semantics.py::test_v91_real_all_cases_still_denied`
- `test_nexus_elliott_v93_recursive_proof.py::test_proof_debt_requires_all_missing_context`

The Windows hosted runner has no dedicated `E:` source/test drive, unlike Laptop2. The failure is a **report directory portability error**, not a false V91 source SHA, model benefit, research entry, or discovered market result.

## Narrow correction

The two **research-report destination** variables now use `Path(tempfile.gettempdir())` for V92/V93 generated *transient test reports*, instead of a hard-coded local laptop drive. No historical receipts are moved or modified: exact SHA-bound V91, V92 and V93 source JSON files in `docs/evidence` remain immutable. Original detailed laptop evidence remains at the prior Laptop2 paths.

Four added V94 regression tests assert that both report destinations are on the executing host's available temp volume and exercise both real-case auditors with independent temporary roots; they require all generated results to match the previously committed historical evidence byte-for-byte **except for deliberately non-deterministic timestamp metadata**. Test report hashes naturally vary by invocation, but the committed evidence bytes and historical decisions do not.

This is **no change** to Elliott geometry, 1m/3m/15m pivots, executable trading controls, paper balance, source ZIPs, research outcome, frozen V52 scoring, runner deployment, or the two laptops' existing installed Demo.

## Gate and limits

All original eight V91/V92 motive examples continue to be explicitly denied for trading. Source-authenticated recursive full Elliott patterns remain **zero**; no costed profit is asserted.

Run V94-specific regression and full local Elliott regression before committing. After pushing, **the new GitHub Test workflow needs its own confirmed Windows, Ubuntu and macOS pass**. Do not represent Laptop2's successful tests as confirmation of GitHub Windows CI.

**Next distinct objective (V95):** physical terminal subwave graph attestation against V89 archived one-minute OHLC and V90 source pivots, including no-lookahead, exact right-confirmation, all primitive retention, immutable Git receipts and refusal to promote a terminal syntactic shape as a complete recursive Elliott pattern. Leave Demo and Live untouched.

## Verified Laptop2 QA

- Dedicated new portable-output tests: **4/4 PASS**.
- Unchanged prior V92 + V93 focused tests: **42/42 PASS** with native exit code 0.
- Full Elliott suite: **741/741 PASS**, `Ran 741 tests in 52.042s`, `OK`, native `V94_FULL_EXIT=0`.
- Full local regression text SHA-256: `aeaf3031ee2521779c2844365eaf79fc861130757e0c99903343f5551f0299cb`; local path `E:\NEXUS-QA\elliott-v93-recursive-proof-20261017\V94_PORTABLE_CI_FULL_REGRESSION.txt`.
- Tests independently compare regenerated transient V92/V93 outputs with immutable Git receipts after omitting timestamp-only fields. These are **software portability results, not economic backtest results**.
