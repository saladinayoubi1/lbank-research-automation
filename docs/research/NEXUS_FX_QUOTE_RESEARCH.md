# FX quote research foundation — #2865

This additive research module is part of NEXUS, not an application or a trading adapter. It does not run from the current Paper writer, change crypto behavior, or qualify a strategy.

The input is an ordered immutable tuple of bid/ask observations with an explicit instrument, source revision, caller-supplied expected normalized SHA-256, observed coverage endpoints, contiguous sequence and maximum permitted gap. A valid hash verifies consistency with the expected normalized records, not independent provider authenticity or absence of unobserved market activity. An upstream verified source manifest, source sequence semantics, market-hours coverage and cost/lot metadata are still required before a real-data backtest.

Entry quote contact uses ask for buy and bid for sell. A signal's timestamp is excluded; a cancellation or expiry at a quote timestamp takes precedence. Order activation, expiry and cancellation are caller-supplied, not inferred from course examples. Market contact is the first later quote. Limit/stop contact is not a fill. Stop gaps record the actual quote rather than assuming the trigger level. A protective contact is determined by the opposite quote side, in source sequence order after entry contact; immediate entry-spread ambiguity is unresolved. Data ending before a terminal event is unresolved. The protective function is a diagnostic of contact after a hypothetical entry, not evidence of exposure, fill, or P/L. No commissions, slippage, partial execution or position sizing are assumed. No financial metrics can be computed by this module.

Remaining acceptance work: source registry/provenance, verified tick datasets, cost and quantity contract, latency and fill lifecycle, partial protective exit allocation, event ledger/risk integration, independent QA, and crypto regression tests. Do not enable any new strategy or Demo routing on the basis of these tests.

The protective contact replays the supplied entry intent against the same window and rejects a mismatched observation. Decimal canonicalization and grid checks are independent of ambient Decimal precision.
