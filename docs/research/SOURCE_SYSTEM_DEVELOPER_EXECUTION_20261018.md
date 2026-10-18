# Complete system specification → real Developer work

The existing Agent Manager can now dispatch a bounded, committed complete-system
implementation request to `developer-agent`. The actual runtime worker emits
executable intake candidate bytes and a complete-system specification, rather
than treating a pytest count as a strategy implementation. A separate
`qa-verifier-agent` lease rebuilds those bytes from committed inputs. The typed
producer and QA receipts bind task/input/code identities and both leases.

## Existing execution path

`agent_manager_runner.py` materializes `research/system_development_requests`
before its existing durable-state merge. `agent_manager.py` selects the real
Developer producer and separate QA verifier. `agent_transport.py` carries the
exact typed implementation binding and, only for QA, the original producer
receipt. `scripts/agent_task_executor.py` executes the compiler in the existing
Runtime Worker. That workflow already publishes `result.json`; both developed
files are included as actual UTF-8 content inside its bounded receipt. No new
scheduler, provider, workflow permission, paid routing or arbitrary-code runner
is introduced.

The coordinator's materializer remains stdlib-only. Candidate and source-note
raw hashes, compiler/model/grammar/dependency-lock hashes and a frozen study
window bind each deterministic task. Unrelated coordinator refreshes preserve
the current lease or DONE state. Changed implementation inputs receive a new
identity; removed old tasks are quarantined by the existing manager. A malformed
request becomes its own BLOCKED task while other work continues. Deterministic
implementation failures stop instead of looping through an unsupported generic
RCA/reasoning-provider route.

Candidate artifacts preserve the reviewed raw bytes, including CRLF. Targeted
Git attributes keep these code/data/lock inputs LF on Windows checkouts so exact
committed input identities remain portable. A temporary Git checkout with
`core.autocrlf=true` preserves the candidate bytes exactly.

## Concrete output and its limits

The seed request completes the **existing internal** prior-day sweep / lagged
peer-resilience proposal. It adds no candidate, parameter variant, selection
tournament or historical replay. Its source note explicitly cites the original
repository proposal and labels all operational rules as research extensions.
This is not an external-source strategy attestation or an Elliott wave counter.
An incomplete website description still needs real interpretation and authoring;
unsupported signals, exits or risk require actual implementation.

The generated `research/complete_systems/prior_day_sweep_peer_resilience_v1.json`
is committed for review and reproduced by the Developer task. Its raw SHA256 is
`6d1590909dfc9fd86cc687687a4673237d2a43da8742f299c91251630c22a313`.
Its system digest is
`4acc6ea974793ef3380477ef8152e76f2470d481c78010a85aba102b8c46c8d9`.

The artifact makes the existing model explicit: one BTC/ETH shared 500-USDT
research book, next-open long-only entry, cost-aware position size, range stop,
2R target, 64-bar timeout and denial rules. It is validated through the actual
complete-system gate in an ephemeral staging directory. That internal syntax
check is not a published approval or a source/semantic review. The existing
executable allowlist remains empty. Portfolio drawdown protection is explicitly
not implemented in this diagnostic, and the historical window is already
inspected, not pristine prospective evidence.

QA here proves artifact reproducibility and lease separation. It is not a new
numerical backtest, an independent implementation of the strategy algorithm,
external-source verification, global semantic novelty, economic qualification,
registry admission, Runtime/Risk admission or Demo approval. Every receipt keeps
those claims false. Paper/Live authority remains false.

## Validation

The final native Laptop2 run passed **148 tests** in 14.14 seconds across the
new real task/compiler/CLI lifecycle plus existing manager, durable runner,
transport, complete-system intake and physical shared-cash contracts, including
isolation of malformed requests to their own blocked task. Exact-head hosted CI
is recorded in the PR.

The lifecycle test dispatches and decodes the real producer envelope, generates
the actual two-file artifact, requests separate QA, reproduces the bundle and
accepts its typed receipt into DONE. Market I/O is prohibited during this test.
Other cases reject role/phase/authority/transport substitution, alternate source
trees, incomplete rules, implicit unsupported exits, test-only fake completion,
rehash-tampered producer artifacts and stale QA leases. The real worker CLI
produces its JSON artifact from another working directory, and the coordinator
materializes its actual request under `python -S`.

Test source SHA values are synthetic identities, not GitHub source attestation.
Actual hosted Developer/QA delivery must be verified separately after merge.
Refs #2007; rollback is a scoped revert with no change to owner installations,
Paper writer, profiles, journals, frozen Elliott protocols or VPS work.
