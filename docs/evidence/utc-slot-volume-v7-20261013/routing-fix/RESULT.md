# v7 frontier routing correction

CI on preparation source a4a296182768e17ca45a0f7d3be9a137a7a96f29 exposed three routing regressions: v7 had fallen into the fixed bucket and could preempt prior fixed/generated stages. A separate generic bounded-signal fixture omitted reviewed v6 shock/previous-close and v7 slot-volume inputs. Ubuntu and macOS each reported four failures; their original results remain failures.

The existing frontier selector now has a final v7 tier after fixed, generated v2/v3/v4, reviewed v5 and jump v6 work. No earlier IDs, ordering, configs or batching limits were changed. Missing feature/digest validation remains strict; the generic fixture supplies its reviewed fields.

Local targeted verification passed 30 tests: the four original failed pure CI test functions, 12 jump/Research tests and 14 slot-volume tests. One new regression checks all 107 earlier frontier contracts individually: any remaining prior contract defers v7. The terminal v6 ledger still routes only the frozen v7 candidate.

The local harness runs selected original function bodies and the unittest causal suites. It does not claim a full local pytest run, hosted CI PASS, native Windows research or independent strategy QA. Hosted exact-head CI remains separate.

Original study freeze d5d0e8c4f8f78632afa321bbf23ce84ac988827b03b7890575f7277f05b491d4 is preserved. Feature helper, factory and v7 contract bytes are unchanged; candidate fingerprint remains 424c0a527aca815448719704c5aa714246e1b1e4c62532dcb782350b1c5090be. The amendment binds corrected execution/test bytes before any market-data outcome has been observed.

Both native RDC devices were Offline. No producer, real-market backtest, v5/v6 completed numeric/Decimal job, failover, owner writer or infrastructure action was performed. Research only; Demo admission=false; Live=false; official Coordinator advancement=false.
