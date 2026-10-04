# TradingView in AI Room and alternative Demo data

The AI Room has a separate TradingView panel for a human to view OHLCV and
technical indicators. An explicit Desktop click opens TradingView's official
OAuth sign-in page. Credentials stay in Electron's OS-encrypted main-process
store; the renderer can request only a bounded symbol/timeframe snapshot.
The official MCP endpoint is `https://mcp.tradingview.com/mcp`.

Only `get_ohlcv` and `get_technicals_rating` can be called. Provider output is
rendered as text with its source, symbol, interval and receipt time. Receipt time
is not candle time or proof of a fresh trading price. There is no automatic
polling, generic tool invocation, alert/watchlist write or market-data export.
No data from this panel goes to the ChatGPT prompt, backend, research, Strategy,
Risk, Paper journal, Council voting, promotion or execution.

The existing ChatGPT sign-in/provider bridge and frozen AI Room control routes
remain separate. ChatGPT's optional advice still follows the merged roadmap:
Mission → Supervisor → Evidence → independent QA → Risk → isolated Paper;
advice is not a Council vote, QA result or execution authority. Live/L4 is locked.

Official references:

- [TradingView MCP tools and account eligibility](https://www.tradingview.com/mcp/docs)
- [TradingView display-use terms](https://www.tradingview.com/policies/)
- [Official MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)

## Verification and owner activation

The real pinned MCP SDK is exercised with deterministic HTTP/OAuth responses:
discovery, resource binding, dynamic registration, loopback PKCE exchange and
the two read calls. Separate tests exercise callback state/issuer, encrypted
credentials, cancellation, expired-account behavior, and trusted main-frame IPC.
No test signs into an owner account or calls a paid service.

The Windows packaging hook verifies the connector and pinned SDK inside ASAR.
The old installed build must remain until exact-head CI/package evidence and a
separate preview pass. After that, the owner clicks **ورود به TradingView** in
the new Desktop preview and approves the official account authorization.
TradingView's MCP beta requires an eligible account (currently Essential or
higher, excluding trials). Account authorization and real market tool responses
have not been verified yet. Merely reading discovery metadata is not sign-in.

## Alternative feed audit

`scripts/audit_alternative_demo_data.py` uses only fixed, official public GET
endpoints. It downloads both BTC/ETH spot warmups on the complete native 4h grid
for 300 days (1,800 closed bars each), then checks a 24h trade/mark grid, the
five-minute execution window, native funding cadence, lot/fee information and
isolated risk tiers. Gaps, invalid prices and conflicting bars fail coverage;
there is no forward fill, Bybit-data substitution or reduced warmup.

The audit caches immutable HTTP receipts by URL and body digest, limits a run
to 48 requests, retries a transient request once, refuses redirects and stops
the provider on 401/403. A fixed source digest and UTC window allow continuation
from cached responses. Each receipt has `demo_replacement_authorized=false`.

Example (use an isolated directory, never an owner Paper runtime root):

```sh
python scripts/audit_alternative_demo_data.py --provider bitget --output ./public-audit/bitget --budget 40
python scripts/audit_alternative_demo_data.py --provider kucoin --output ./public-audit/kucoin --budget 24
```

Repository receipts under `docs/evidence/alternative-demo/` bind the actual
secondary-laptop collection to the source digest and UTC observation window.
Raw HTTP bodies remain in the isolated public-audit cache on that laptop for
replay; they contain no Paper account state or exchange private credential.

A collection pass means a candidate for an isolated adapter. Replacing Demo
still requires the provider's own contract units, rounding, fees, funding and
margin rules, full historical replay with conservative/stress costs, independent
numerical QA and persistent feed/restart tests. KuCoin contract lots cannot be
treated as Bybit base-coin quantities. The existing Bybit position, account
history, 500-USDT reference and journal must not be migrated or repriced.
