# Fixed portfolio: official raw-Spot future source route

## Result and scope

The historical-context integration in PR2756 is already merged. This change
adds an executable, separately bounded source route for the existing fixed
portfolio protocol. It does not run that portfolio, release its Manager task,
or grant Paper authority. Classification: data-intelligence and
evidence/verification; preserve DATA-20/DATA-21 and QA-41.

The only interval is **[2026-10-19T00:00Z, 2027-01-17T00:00Z)**, exactly
90 UTC days, 180 symbol/day files and 540 physical four-hour bars per asset.
BTCUSDT and ETHUSDT remain Bybit Spot. The entire horizon must have elapsed
before either acquisition or raw-source QA can open any source file. There is
no caller-supplied clock/date override in the CLI, early partial scoring,
schedule, monitoring loop, provider fallback or automatic retry.

## Separate representation and evidence boundary

| Route | Source representation | What this change does |
| --- | --- | --- |
| Existing future preflight | Claimed direct V5 4h candle Parquets | Preserves its exact original bytes and its refusal to grant economic/Paper readiness |
| New raw-source route | Official HTTPS daily Spot trades aggregated into UTC 4h buckets | Records exact acquisition and raw bytes; independently reconstructs every tick with Decimal |
| Existing historical context | Original archive plus approved 79-day warmup | Preserves its digest and requires a later executor to bind it separately |

The source format is explicitly **raw Spot trades, not V5 candles**. The public
[Spot archive directory](https://public.bybit.com/spot/) and the separate
[V5 candle documentation](https://bybit-exchange.github.io/docs/v5/market/kline)
were inspected on 2026-10-19 UTC without opening prospective price files.
The retained earlier raw-file evidence already establishes the exact supported
CSV schema and historical seam; this change does not repeat that old study.

Source acceptance means local verified-TLS HTTP observations plus numerical
reconstruction. It does not mean an exchange-signed payload, an external-host
attestation, independently proven provider completeness, an identical V5 candle
representation or economic qualification. Both cryptographic/external-host
claims remain false in the receipts. A local receipt hash alone proves neither
origin nor exchange authority.

## Implemented controls

`research/portfolio_v3_forward_raw_source_policy_v1.json` is digest-locked.
It binds the frozen dates/candidate, the historical context digest, and exact
LF-normalized identities of the existing raw parser, separate Decimal QA,
fixed handoff, source freeze and V5 preflight. A modified policy or imported
parser/verifier is rejected.

`scripts/nexus_portfolio_v3_forward_raw_source.py` provides three operations:

- `status`: reports elapsed horizon and continued lack of financial readiness;
  reads no market inputs and needs no HTTP package.
- `capture`: after the full horizon, GETs only the exact allowlisted official
  symbol/day URLs. TLS verification is explicit, redirects are rejected,
  environment proxy/netrc settings are disabled, timeouts are finite, and the
  fresh requests session uses its default zero-retry adapter. Each retained raw
  file and daily receipt binds the request/code/policy identity. Resume rehashes
  completed days and makes no repeated GET for them. Partial or unreceipted raw
  files stop for explicit recovery. Per-file and total byte limits are enforced
  before excess response bytes are written.
- `qa`: after the full horizon, checks all 180 ordered paired days, receipts,
  exact URLs/TLS/status/times/hashes and totals. The existing separate stdlib
  Decimal implementation streams every trade, validates chronology and buckets,
  and reconciles OHLCV/counts against the float producer. Missing bars are never
  synthesized. Optimized Python is rejected because Decimal QA uses assertions.
  Raw bytes are rehashed again after each independent reconstruction.

The resulting write-once QA artifact carries 540 source-bound bars per asset,
its capture/policy/code identities and digest. Source eligibility is only for
a **separate** fixed-portfolio Research/QA handoff. Financial dispatch,
strategy-result readiness, Paper eligibility and Live remain false.

## Verification and remaining integration

Twelve focused tests passed locally. They exercise a complete synthetic
180-file producer/independent-QA path, safe resume, corrupted/rehashed source
claims, missing/duplicated days, OHLCV/time/count mutations, failed/redirected/
short HTTP bodies, byte-budget enforcement, immutable code/policy/request
bindings, duplicate/nonfinite JSON, early-time I/O rejection and optimized
Python rejection. All prices in these tests are artificial constants.

The current native Laptop2 verification is retained separately under
`docs/evidence/portfolio-forward-raw-source-20261020/native-verification.json`.
All twelve final methods passed there in 43.902 seconds; native exit=0.
It binds the final code/test/policy hashes and its actual current-time status.
Hosted exact-head CI is still required before merge. No actual future dataset,
financial result, source acquisition, order, source deployment or new active
Research task is claimed by synthetic protocol verification.

The exact original financial executor and independent signal/accounting QA
handoff remain next work. That consumer must bind this future source result to
the approved historical context, preserve the globally anchored 42-bar review
phase, original shared cash/costs and fixed DD20 comparison, and retain the full
horizon before any financial execution. The existing preparation row remains
BLOCKED. No qualification, registry or Risk/Paper gate is changed.

No original raw/Parquet data, installed application, journal, profile, laptop
role, source freeze, historical negative study, Manager definition, workflow,
monitor or VPS is modified. Laptop1 remains the sole Paper writer. Bybit only;
Live=false; paper_eligible=false; orders=0. Rollback removes these additive
source-route files and isolated synthetic QA outputs.
