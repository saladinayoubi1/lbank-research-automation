# NEXUS Elliott V93 — finite recursive wave grammar and future-only entry/exit hypothesis

**State:** additive research QA. The new parser checks a finite abstract Elliott subwave proof graph and the historical V91/V92 *lack of independently verified graph evidence*. It is not an exchange strategy, an executable entry, a real backtest or a source-authenticated Elliott certificate. GitHub PR #2673 remains Draft/unmerged. Laptop1 Demo, V52 Oct 18–Nov 15 2026 UTC prospective protocol, Bybit and the paused VPS untouched. Live trading disabled.

## Actual frozen corpus and results

V91 Git source was committed in `1fa94b9432be9d13782f3f76c0bb48737c3bc445` with content SHA256 `d4401a5606dee6a0842d1ee3752375dc95de732b9189eb3e65983640ec1715c0`. V92 execution admission source was committed in `48a29982e82856ea5242ceec156204e7c05618a3` with content SHA256 `490b283bbf0cc218eec1e417df49f854fe4e4646e142a4d98b7bb244a097324a`. V93 verifies exact **Git committed blob bytes plus ancestry**, rather than trusting filenames or renaming an unsupported case.

| Inspection | BTC | ETH | Total |
|---|---:|---:|---:|
| Source-bound candidate five-leg cases | 6 | 2 | 8 |
| V91 fixed 1m strict interior counts mismatched 5-3-5-3-5 | **6** | **2** | **8** |
| Missing independent lower-degree proof tree | **6** | **2** | **8** |
| Missing verified 15m position/prior trend context | **6** | **2** | **8** |
| V92 order admission DENY | 6 | 2 | 8 |
| Complete Elliott pattern proof / new signals / P&L | **0 / 0 / none** | **0 / 0 / none** | **0 / 0 / none** |

Additional root cause: 7/8 fail conventional impulse outer hard geometry. The remaining BTC skeleton passed necessary outer geometry but has a physically unordered local high+low event and mismatched 1m internal counts. All historical candidate families were explored with frozen rules and **none should be relabeled to rescue a previous losing result**.

## Actual implementation: pure finite grammar checker

`research/elliott_v93_recursive_proof/proof_v93.py` adds a typed finite `WaveNode` graph whose non-terminal wave uses alternating directed contiguous subwave intervals, strictly decreasing degree, right-confirmed source-time bounds, and deterministic grammar:
- **IMPULSE**: five constituents: motive, corrective, motive, corrective, motive.
- **ZIGZAG**: three constituents: motive, corrective, motive.
- **FLAT**: three constituents: corrective, corrective, motive.
- A degree-1 non-terminal decomposes to 5 or 3 degree-0 **TERMINAL** leaves. A terminal cannot claim additional lower-degree decomposition.

Child interval continuity, exact parent boundaries, unique graph objects, max depth, max node count, increasing center/boundary times, no reuse/cycle, no future confirmation, and alternating up/down direction must all pass. For the same physical market observation, graph shape alone is **never authenticated**: even a perfectly consistent synthetic tree returns `SYNTACTIC_RECURSIVE_SHAPE_ONLY`, `physical_1m_and_subminute_provenance_verified=false`, `entry_signal=false` and `paper_eligible=false`. The source-backed terminal witness verifier / independent market graph builder still **does not exist**. No self-supplied source flag can trick this grammar verifier into creating a market proof.

**Consequently** this is a *syntax framework*, not a validated replacement for the incomplete V82–V91 Elliott wave classifier. The archived V91 cases contain source-backed primitive counts but not independently adjudicated recursive graph nodes with a proven higher-degree pattern position.

## Candidate policy registered **for future untouched source only**

V93 stores a **non-deployed, non-optimized, exploratory hypothesis** to remove discretionary choice when, and only when, a separately certified source-backed and context-valid Elliott tree can later be demonstrated. The procedure is NOT tested against historical July gains/losses and currently emits **zero signals**.

- Candidate must first pass independently source-authenticated full graph degree/position/context, not merely motive outer geometry or an artificial syntax tree.
- After completion and confirmation of Wave 5, observe a **future closed 1m candle** breaking Wave-5 outer extreme in motive direction. A candidate trade could be *hypothetically* priced at the next 1m open only with physically observed bid/ask quotes and a validated fill model; never use the earlier wave-center price or intrabar information unavailable at decision time.
- Stop is the outer Wave-4 extreme in invalidating direction; discard if invalid versus entry. Experimental target **2 times initial nominal R** and timeout after **60 complete 1m candles** (hypothetical next-bar exit). This is a deliberately *unvalidated heuristic* rather than an optimal value or a claim of current Bybit liquidity.
- Use reference 500 USDT paper balance, maximum **2.50 USDT nominal risk** per test case, no overlapping position in same pair, no immediate duplicate re-entry. Gap, spread, fees, funding, tick/step sizes, stop queue, fill and any loss above nominal risk are still unverified. Missing any market spec or quote => **ABSTAIN**.
- The policy is **not connected to Demo** and cannot issue orders. Model/test losses cannot be inferred from this table; no realized net P/L is calculated. Never tune these constants using July 2024 outcomes.

## Evidence and QA

New structured source-obligation receipt: `docs/evidence/elliott-v93-recursive-proof-20261017/V93_PROOF_OBLIGATIONS.json` and off-repo original on Laptop2; SHA256 `fa55b3dd524fba9de7546fba8ea110db30a1e7b9bb8507ff7c79325ad8a35f58`. It preserves 8 exact as-of decision times, 1m strict interior counts, mismatch leg indices, OHLC ambiguity, unsupported context, and explicit deny state.

Tests include synthetic two-degree recursive Impulse, Zigzag, Flat, bearish mirrors, invalid wave-role type, degree inversion, missing subwaves, overlap/gap, future confirmation, unaligned timing, re-used/cyclic node, unreasonable graph expansion, altered immutable Git checksum and forced unauthorized admission. **A pass validates the checker, not profitability.**

**Next bounded research task:** implement an independent candle-level graph builder with a documented terminal verification rule and source provenance for real multi-degree observed patterns. Separately verify the preregistered trade hypothesis on *new* untouched data with Bybit-compatible spread/slippage/fees and chronological fill simulation, before any Demo promotion. No Live functionality.

## Verified regression record

- V93-specific tests: **21/21 PASS**, `V93_DEDICATED_EXIT=0`.
- Complete Elliott tests on isolated Laptop2: **737/737 PASS**, `Ran 737 tests in 49.685s`, `OK`, native `V93_FULL_EXIT=0`.
- Local test log: `E:\NEXUS-QA\elliott-v93-recursive-proof-20261017\V93_FULL_REGRESSION.txt`, SHA-256 `4ef7fa81599700fb82d56022206e01f01d7a34d1ef482965b934f07ca8b6e567`.
- New structural proof-debt JSON SHA-256 `fa55b3dd524fba9de7546fba8ea110db30a1e7b9bb8507ff7c79325ad8a35f58`; original source receipts and V52 scoring data unchanged.
- GitHub CI for V93 must be independently verified *after* push; this document does not claim those workflows succeeded.
