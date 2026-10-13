# v6 Decimal oracle calendar-day cache precheck

Change: Cache canonical datetime day keys once in the existing Decimal oracle, then resume only the nine uncompleted selected-report accounting cells.
System Map nodes: DATA-21, VAL-40, QA-41.
Existing component being changed: Existing independently implemented nexus_composite_fill_oracle.recompute, baseline ref 7294b2d72d2ae5a46a03a26c23242ac27a385f1a / blob d583ed655efe64b5c0c5eb73960eb217bc7ded83; bounded immutable-report audit wrapper.
Why existing component cannot already satisfy the need: The 600-second v6 audit exited 124 after three completed cells. Native 77k-bar accounting cell 2 took approximately 205 seconds after cell 1. The oracle performs per-bar Timestamp.floor(D), the same operation already identified as costly in the source backtest. No quantified old/new speedup is assumed; new regression and runtime receipts are required.
Primary runner / execution lane: Laptop1 isolated distinct-host QA, not Research failover; producer remains Laptop2.
Data source and provenance: Existing pinned Bybit BTC/ETH 15m/1h/4h canonical archive, immutable v6 report/source and completed optimized numeric proof. Prior decoder references retain their original dataset-only identity.
Upstream dependencies: Study source 8899ec6bec4927fc39795f2867be91e2431178c6; original engine blob 918c886570040712f3b7aa83f7fa812720c927b2; report digest 02c7a7b1dd0a78ed13d8dbefcfec7824d11c9eedd22e3d337b5e658eb0e099b3; complete numeric proof 2264571a50b99af12479f733cb9ba2b208038ce4467ddc614578ba82a6bce259.
Downstream consumers: Research accounting evidence only.
Authority level: Research only; source backtest, producer/tournament and sockets remain prohibited.
Paper/Live boundary: Owner Demo admission=false, auto-Demo=false, Live=false, official Coordinator advancement=false. No owner state mutation.
Duplicate-work check: Preserve the failed original audit root and reuse its three digested passing receipts with frozen input/source, regenerated signal, feature-frame and original-report metric checks. Do not rerun those accounting cells, completed v5 jobs, native day-cache units or 16 completed numeric comparisons. Oracle calculation rules are unchanged; the newly reviewed cache source identity is explicit and distinct from the baseline oracle identity.
Failure mode: Source, runtime, input, receipt or numerical discrepancy fails closed. Fresh root and exclusive execution lock prevent duplicate jobs; stage deadlines preserve atomic cells.
Rollback: Use the unchanged baseline oracle for further diagnosis without overwriting old results; no owner installation rollback needed.
Tests: Freeze 20 unrounded Decimal outputs/fill paths from the exact baseline before patching; compare the patched implementation. Verify timezone/DST day-key parity, object fallback and canonical no-scalar-floor calls. Check AST to limit changes to the day-cache statements. Repeat the new regression on native Windows before resumed accounting.
Independent QA required: New pinned cache source tested on native Laptop1, then independent Decimal accounting of frozen Laptop2-produced evidence. Shared signals/data and original-source strict replay limits stay explicit.
Deployment/cutover impact: New isolated QA root and evidence files only. No runner, runtime, install, registry, VPS or WSL changes.
Evidence required to declare DONE: All 12 selected-report accounting receipts and a bound final receipt with native exit 0, with original/cached oracle identities and reuse lineage explicit. A partial run is not full accounting completion or strategy qualification.
