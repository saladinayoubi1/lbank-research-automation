# Independent laptop visibility — change precheck

Recorded before implementation on 2026-10-13; source main ed2f16b6aabe7d0d97562fd64bb4e3609dc51b32.

Change: Extend the existing VPS observer with a read-only two-laptop projection and bounded authenticated heartbeat receipt storage. Add a one-shot exporter that reads existing local heartbeat/research checkpoints; no new runner, supervisor or scheduler.
System Map node(s): OBS-80, CTRL-11 (observations only); RUNTIME-60/PAPER-62/PAPER-63/SAFE-64 authority unchanged.
Existing component being changed: nexus_vps_arbiter_observer.py; reuse fast_agent_orchestrator.py local_heartbeat.json and source-bound research status.json as inputs. Do not activate start_nexus_local_node.bat or modify runner registration.
Why existing component cannot already satisfy the need: Host preflight has no laptop receipts or last-contact/workload projection. Existing heartbeat is local and its workflows are GitHub-wide, not proof of a laptop research worker.
Primary runner / execution lane: Existing independent VPS observer; one-shot export from each existing laptop periodic hook when later explicitly configured. Local unit/HTTP tests now; both physical devices Offline and independent VPS SSH unavailable.
Data source and provenance: Authenticated node-bound SSH forced-command stdin, server receipt time, existing local heartbeat/research snapshots and a bounded process-name-only listener observation. No private credentials, command lines, exchange or Paper journal data read.
Upstream dependencies: Main-pinned source, private VPS state, dedicated per-node SSH identities with forced node binding, existing port22 and pinned host verification. No new public endpoint/firewall change.
Downstream consumers: Existing observer GET /nodes and CLI projection; operator read access independent of either laptop.
Authority level: Receive/store/display telemetry only. A self-reported heartbeat is not independent native QA or fencing proof.
Paper/Live boundary: No writer permit, failover, retry/dispatch, risk override, trading, owner profile/install/journal mutation; Live=false.
Duplicate-work check: Preserve host /healthz and /readyz/permit HOLD; no second observer, runner, scheduler, telemetry daemon, soak or reboot. Read existing signals instead of executing their producers.
Failure mode: Unknown/spoofed node, malformed/oversized payload, stale/future timestamp, replay, corrupt/missing state or clock rollback cannot create fresh contact. A silent laptop is NO_RECENT_HEARTBEAT, never proof it is powered off. Missing workload input remains UNKNOWN.
Rollback: Revert optional route/helper/exporter; retain receiver state and original observer source. No in-place deployment or service restart in this turn.
Tests: Node identity/role binding; timestamp/replay/duplicate behavior; restart persistence; corruption/missing DB; independent freshness per observation; unknown/stale local inputs; no secret/error text exported; HTTP /nodes and unchanged permit/POST denials.
Independent QA required: Exact-head CI plus later physical two-node sender/receiver and operator access tests, transport identity isolation, restart and negative cases before operational claim.
Deployment/cutover impact: Draft source preparation only. Current SSH route depends on offline Laptop1; neither VPS nor laptop installation changed. Dedicated least-privilege transport and an independent operator access route are deployment prerequisites, not asserted as existing.
Evidence required to declare DONE: Reviewed merge, exact-source CI, authenticated real receipts from both laptops visible from an independent VPS connection, TTL/replay/restart tests and service role invariants. Local mocks prove the contract only.
