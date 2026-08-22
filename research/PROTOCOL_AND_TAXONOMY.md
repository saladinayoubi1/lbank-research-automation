# NEXUS research protocol and taxonomy

Status: research-only / paper-trading-only. Tracking issue: #45.

## Market authority

Market evidence is interpreted in this fixed order:

1. **Bybit — primary** venue and implementation authority.
2. **Binance — secondary corroboration** only.
3. **LBank — tertiary/legacy research** only; it cannot override Bybit or authorize execution.

No source, model, backtest or paper result authorizes live orders, private credentials, signing, billing or production promotion.

## Taxonomy

| Axis | Controlled values |
|---|---|
| Market | crypto spot; crypto futures; perpetuals; options; FX spot; forwards; swaps; options |
| Strategy | trend; momentum; carry; value; mean reversion; arbitrage; market making; volatility; event-driven; cross-sectional; on-chain; funding/basis; statistical; ML |
| Evidence domain | market structure; data; execution costs; risk; backtesting; nonstationarity; model validation; regulation; behavioral finance |
| Evidence role | authoritative; academic; implementation/incident; limitation/dissent |
| Lifecycle | candidate; verified; rejected; superseded; review-due |
| Applicability | hypothesis; parameter boundary; validation control; failure mode; operational constraint |

## Inclusion policy

Include a source only when its identity is independently resolvable through a DOI, standards body, regulator, official venue documentation or stable institutional publication page. Record title, author/publisher, year, locator, applicability, limitations, verification status, review date and obsolescence triggers.

High-impact claims normally require an authoritative source, independent academic evidence, implementation or incident evidence, and a limitation or dissenting view. A missing role is an explicit evidence gap, not permission to substitute a blog, marketing page or model-generated claim.

## Exclusion policy

Reject or quarantine anonymous claims, unverifiable screenshots, affiliate/promotional content, copied summaries without primary metadata, unsupported profitability claims, personalized advice, future information, private notes, credentials, attachment paths and sources whose license or privacy status prevents repository use.

Blogs, social posts and model outputs may identify candidate sources but are never final evidence. A syntactically valid citation is not proof of authenticity, applicability, peer review or current validity.

## Review procedure

1. Register the candidate and assign a stable ID.
2. Verify identity and locator against the primary publisher.
3. Classify market, strategy, domain, role and applicability.
4. Write a bounded claim plus limitation; never import a conclusion verbatim as project truth.
5. Bind claim IDs to evidence IDs and record conflicting evidence.
6. Set a review date and concrete obsolescence triggers.
7. Run `python scripts/validate_research_registry.py`.
8. Merge only through fixed-head green CI.

Review is required at least every 365 days, and earlier after venue/API/fee/funding/market-structure changes, standards revisions, source retractions, data-method changes, false-green backtests or new contradictory evidence.

## Backtest validity boundary

Every strategy study must pre-register the primary hypothesis, dataset/venue, completed-bar timing, benchmark, chronological validation, cost/funding/slippage assumptions, search count, multiple-testing treatment and falsification criteria. Report net outcomes, drawdown, tail loss, turnover, exposure and window stability. Passing history allows paper-forward evaluation only.

## Zotero and recovery

Git is the versioned citation authority; Zotero is the working library. Export only reviewed metadata. Never commit PDFs, private notes or local paths. On registry corruption, restore the previous-valid Git version, verify file SHA-256 values and rerun the validator before accepting new evidence.
