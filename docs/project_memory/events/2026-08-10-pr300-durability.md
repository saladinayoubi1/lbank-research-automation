# 2026-08-10 — PR #300 durability hardening

Status: CURRENT EVENT RECORD

Evidence:
- Exact pre-merge main: `5a337367b4504dc23d3e87e5daa0a37f28986d53`.
- PR #300 exact head: `d93373c85ade083da40c0a162ece96027b6af005`.
- Required PR-head workflows observed successful: `Test`, `NEXUS Build Verification`, `NEXUS Cloud Fallback`.
- PR was `mergeable=true` with zero unresolved review threads.
- Squash merge result / new main: `60983e2d3233e11fefe357d7378cfae8b15fdad6`.

Facts:
- Reservation-ledger temp contents are flushed and fsynced before atomic replace.
- Replaced ledger and initialization sentinel are fsynced before paid network I/O.
- Parent-directory metadata is fsynced on POSIX where supported.
- Durability syscall failure fails closed.
- Windows directory-entry power-loss durability is not claimed as proven.
- Orphan-lock recovery remains deliberately fail-closed.

Decision:
- #232 remains OPEN and paid-routing hard-cap authority remains non-authoritative.
- Remaining completion evidence includes fixed-SHA crash/restart replay, authenticated orphan-lock recovery, provider-observable reconciliation/recovery, and final aligned CI/review evidence.
- No credential, billing change, paid API call, signing, production deployment, live trading, or other irreversible financial action is authorized by this event.

Lesson:
A successful atomic replace is not itself a durable reservation commit. Durability claims must include flush/fsync ordering and explicit platform/filesystem boundaries, and ambiguous crash state must prefer availability loss over possible re-spend.
