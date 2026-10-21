# Public-source diagnostic supplement

One real Laptop2 GET at 2026-10-21T08:08:34Z (11:38 Tehran) returned HTTP403 / CloudFront and an explicit country-origin access rejection. `windows.json` preserves the exact 96-byte public error excerpt, body SHA, no-request-body witness and frozen existing classifier identity. It does not identify the IP's actual country, an account restriction or a bad key. No credentials were used.

The diagnostic stopped after this one request. No alternate REST host, WebSocket, WSL egress, proxy, VPN or substitute exchange was tried after the explicit rejection. Earlier unidentified 403 evidence is preserved separately in `../api_preflight.json`. Earlier backtest/QA/execution digests are unchanged. `state_mutations=false` concerns trading/runtime state; the diagnostic intentionally writes its own evidence file.

Reusable source: `research/nexus_mr40_public_source_diagnostic_v1.py`. Pass `--classifier-path bybit_public_klines.py --output /a/new/file.json`. It verifies the existing classifier's exact SHA before requesting any source. The output must not already exist. This is an isolated Research diagnostic, not a change to the product transport, registry, qualification, trading strategy or Paper writer.

Five network-mocked tests cover explicit-country stop, rate-limit stop, bounded unclassified fallback, removal of a forming candle without automatic demo startup, and output preservation. Native Windows testing uses the installed requests dependency. The local scratch Python lacks requests, so no local runtime-test pass is claimed; compilation and receipt integrity can still be checked without installing packages. An initial test stream double was corrected to accept urllib3's decode_content argument; the real captured probe and its source are unchanged. Native final transcript is retained here.

Source semantics checked against official Bybit documentation on 2026-10-21:

- https://bybit-exchange.github.io/docs/v5/guide
- https://bybit-exchange.github.io/docs/v5/error
- https://bybit-exchange.github.io/docs/v5/ws/connect

No source-readiness, prospective profit or actual-demo result is claimed. The main research test at source commit 8d4415fbd4750243e0d1c9e07d07019224733357 and all earlier evidence remain intact.
