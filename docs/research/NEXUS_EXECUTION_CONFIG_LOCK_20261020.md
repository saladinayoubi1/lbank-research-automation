# Freeze the diagnostic execution inputs

The daily risk-cadence diagnostic pinned its engine and study contract but
checked only the candidate identity in a separate calibration file. Changing
stress capital to 1000 USDT or severe fees to zero passed those locks. Its
currency P/L still multiplied return by 500, and a missing cost profile could
be silently omitted from falsification. An empty profile set could survive
through `all([])`.

This bounded RES-32 / QA-41 maintenance change uses the existing diagnostic.
The complete reviewed calibration now has a canonical SHA256 pin, checked
before importing the market-source path or creating output. The approved
three profiles all retain one shared 500-USDT Spot account:

| Profile | Fee per side, bps | Slippage per side, bps |
|---|---:|---:|
| stress | 15 | 10 |
| severe | 25 | 15 |
| conservative | 10 | 5 |

The canonical pin is
`0d59b4c956ceec492c4c9b2f92062871f7603a9bb60f69a2e435a971597bc1e4`.
It covers candidate rules, costs, capital and authority fields. It tolerates
JSON formatting, key order, UTF-8 BOM and line endings, while requiring the
exact reviewed numeric representations. Non-finite values fail canonical
serialization; other changed values cannot match the reviewed digest.

Falsification requires exactly seven periods, four books and all three cost
profiles in every book. Future diagnostic output includes the calibration
digest and actual execution profiles; currency P/L uses validated capital.
This change does not migrate or rewrite the retained historical result.

DeepSeek and Perplexity reviewed the same source excerpts, reproduced bug
description and proposed fix through the existing AI Room conversations.
Both agreed with the repair direction and requested complete profile/matrix
checks and rejection before price loading. Their responses and Codex's
resolution are retained in the accompanying `ai-review.json`. Perplexity's
response was recovered from two identical logical accessibility reads, each
matching the complete submitted prompt; its official completion signal was
not observed. Claude did not provide a fresh response because the composer
operation failed; its old assistant-owned draft was preserved.

Nineteen test methods passed locally and on physical Laptop2, native exit 0.
The new checks include 70 changed-config subcases, 10 incomplete-matrix
subcases, a rejection-before-price-read control, and valid configuration and
historical decision controls. The original observer regressions remain in
the suite. `verification.json` binds both tested source hashes to the
physical snapshot and test log.

No new historical economic replay or future scoring was performed. The
original contract, engine, retained result and fixed rejection remain
unchanged. These are code-integrity checks and advisory peer reviews, not
independent financial qualification or evidence of profitable trading.
Paper eligibility remains false, Live remains disabled, and orders remain zero.

Evidence: `docs/evidence/execution-config-lock-20261020/`.
Rollback is an isolated revert of the diagnostic, its tests and this review
packet; no installed Paper runtime or owner journal migration is involved.
