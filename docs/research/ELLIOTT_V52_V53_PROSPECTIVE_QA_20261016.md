# Elliott V52–V53: source-bound prospective research

Research-only. This document records tests, fixed rules and limitations of Draft PR #2673. No positions, orders, automated Demo, Live, or reported P/L are authorized.

The **capture start** is October 16, 2026 at 00:00 UTC. This protocol was written *after* the capture-start minute. Thus October 16–17 are explicitly **unscored warm-up** and the **first eligible scored evaluation is October 18, 2026 at 00:00 UTC**. The scored window ends November 16, 2026 at 00:00 UTC, exclusive. Historical research inputs cannot be counted as new prospective evidence.

The exact fixed specification is in `research/elliott_v52_prospective/protocol_v52.json`. Its SHA-256 after CRLF-to-LF line-ending normalization is `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`. The line-ending normalization corrects a Windows checkout portability issue; the actual protocol values were not changed.

**V52** reads physical official Bybit public Spot BTCUSDT/ETHUSDT daily trade archives after the complete UTC day closes, checks raw and minute-file hashes, independently reconstructs 1,440 minute bars and checks OHLCV and trade counts. It rejects old, partial, missing, malformed and future data. It does not itself retrieve archives or run scheduled monitoring.

**V53** reads sequences of V52-verified, rehashed UTC source days and runs the unchanged research-only parent/child proposal chain: strict 15m parent pivot, exact 1m source origin and fixed 3m child-degree checks. It returns reasons for acceptance or rejection without any entry authority.

Local tests on Laptop2: V52 17/17, V53 16/16, and the complete Elliott-focused regression collection **352/352 PASS, exit 0** at the branch head containing V52/V53 modules and discovery shims.

At 2026-10-16 00:12:45 UTC, an isolated smoke test independently confirmed three boundaries: the historical Oct08 official source cannot enter V52; an Oct16 warm-up event cannot be scored; and archived Oct08 minute data cannot enter V53. As the current UTC day was not yet over, **zero newly captured complete days and zero new prospective candidate outcomes** were reported. The local readiness receipt is `E:\NEXUS-QA\elliott-v52-frozen-prospective-20261016\V52_V53_READINESS_20261016.json` with SHA-256 `fd2e13ef315beb7eed2f7e96347201f06f778b53c23463b8a29f3a5d88bd6d94`.

The scanner remains a bounded structural research experiment, not a full recursive Elliott classifier and not evidence of profitability or realistic exchange fills. Any future daily observations must be independently captured and evaluated under the frozen rules; no retroactive parameter adjustment is permitted.
