# Windows ASAR metadata lookup regression

Both PR #2318 Windows jobs failed in `after-pack.js:18` while extracting the pinned MCP SDK manifest. The original CI job IDs and native before/after logs are retained in [20261004-native.json](20261004-native.json).

ASAR 3.4.1 resolves directory components using `path.sep`. Its normalized package listing contained the manifest; native `path.join` extraction returned version 1.32.0. The original POSIX string still failed on Windows with the same error as CI. The corrected hook uses a native path and keeps the connector presence, exact SDK version and real Git seed checks.

The bounded suite passed all six tests on DESKTOP-F4SA4VL (Windows, Node v24.19.0). The original hook failed the positive archive case and could not reach the wrong-version gate (four passed, two failed); the corrected hook passed both and continued to reject missing metadata, missing connector/client files and an unpinned version. Exact tested hook, test, package and lock digests are in the receipt.

`npm run dist:win` runs the full production-dependency ASAR suite first in both existing Windows workflows. That stronger suite is preserved. All eight PR workflows, including both Windows builds, completed successfully on head `46f1b9fcfa8ae8fccc65842d2b6d1508cb6d1471`. These additional evidence files require checks on the resulting new head before merge.

The bounded native test is supplementary. Its byte-identical source is retained in [bounded-native-test.cjs.txt](bounded-native-test.cjs.txt); copy it to `tests/test_product_after_pack.cjs` in the isolated replay directory to reproduce the receipt. It does not replace the mandatory production archive suite. Local validation: six bounded packaging tests and 19 focused Python checks passed, including the ChatGPT/TradingView wrappers and source-seed/delivery checks. Overlapping wrapper tests are not counted twice.

The ASAR fixture contains real connector files and SDK manifest/client files; SDK client, transport and auth dependencies load separately from the isolated exact-lock installation. This is not evidence that the complete production archive or Setup/Portable EXEs were produced or executed. New-head Windows CI and package acceptance remain required before merge or installation.

An initial full-dependency fixture timed out after 90 seconds before creating an archive. It was replaced by the bounded fixture above. The original before-test log survived a harness stdout encoding error; the after harness writes its receipt before printing JSON and exited 0. No failure evidence was rewritten.

The existing installation, owner profile/journal and exchange account were outside this isolated replay. No provider authentication, market request or order was performed.
