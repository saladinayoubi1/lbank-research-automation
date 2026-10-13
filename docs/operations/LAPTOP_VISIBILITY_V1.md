# Independent laptop visibility through the existing VPS observer

Status: source preparation and local contract tests only. No real laptop receipt, VPS rollout, independent SSH connection or operational monitoring is claimed.

## What the operator can see

The existing observer retains its host preflight and gains GET `/nodes`. Its two fixed node identities are DESKTOP-1R1081M (Runtime/Paper primary) and DESKTOP-F4SA4VL (Research primary).

| Field | Meaning | Limit |
| --- | --- | --- |
| contact | FRESH, NO_RECENT_HEARTBEAT, NOT_SEEN, STATE_UNAVAILABLE or CLOCK_ANOMALY | An authenticated message proves recent contact; silence never proves the PC is powered off |
| last_received_at_utc / age_seconds | VPS receipt time and effective age of receipt/report | Restart or duplicate messages do not refresh an old receipt |
| runner.listener_count | Number of Runner.Listener processes observed by name | Process presence does not prove GitHub registration, connectivity or worker health |
| coordinator | Existing local heartbeat's activity/connectivity report | It is a report at its own timestamp, not a remote attestation |
| research | Existing explicit status.json stage, completed cells and source SHA | Stale progress is retained as last_observation; current becomes null |
| reporter_source_sha | Exact-format source identity supplied by the exporter | This field is not independent code attestation or research QA |

Freshness is bounded to 90 seconds for both contact and each component. Contact is bounded by both the original report time and VPS receipt time. A fresh laptop contact cannot make an old research stage current. Stale/unknown inputs are never interpreted as a running research worker.

The exporter reads `data/agent_coordination/local_heartbeat.json` produced by the existing orchestrator when explicitly configured. It reads only whitelisted fields and ignores error text, file paths, private fields and unrelated GitHub workflow status. Research progress requires an explicit real checkpoint path; absence remains UNKNOWN. It does not execute the orchestrator, restart a runner, dispatch work, read process command lines or inspect credentials.

## Authenticated transport boundary

No HTTP ingestion endpoint is exposed. POST/PUT/DELETE remain denied. The current observer remains loopback-only. Use the existing pinned SSH transport on port22.

The receiver is designed to be invoked by a **server-owned SSH forced command bound to one authenticated laptop identity**. The forced identity is never taken from the message or SSH_ORIGINAL_COMMAND. The application checks that the message's node matches that trusted identity. Supplying `--authenticated-node` yourself on an arbitrary shell is not authentication.

Each laptop must use its own scoped transport identity. Do not copy the VPS administrator key, Paper arbiter signing key or another laptop's credentials between machines. Private keys/credentials remain outside source, artifacts and logs. No keys or accounts were created in this work.

The existing observer service account needs read access to the receipt DB; the constrained receiver needs write access to that telemetry DB only. Determine the actual service user/StateDirectory and reviewed least-privilege ownership on the VPS before deployment. Do not assume a DynamicUser UID remains stable. No broad root shell, port forwarding or access to owner state should be granted to a telemetry sender. A forced-command SSH policy must deny agent/X11/port forwarding and PTY access, ignore client-supplied commands and bind the receiver/source/state paths on the server.

## Source-frozen operational steps — not executed

1. Obtain an independent, pinned VPS operator connection that continues to work when both laptops are offline. The currently documented administrator path on Laptop1 does not satisfy this requirement.
2. Verify exact reviewed source and actual observer unit/account/state permissions. Preserve the healthy install, host checks, kernel/SSH configuration and existing state.
3. Install the reviewed helper alongside the existing observer; initialize a fresh private telemetry database explicitly. Existing/missing/corrupt DB state is never silently reinitialized during receive or display.
4. Configure two separately authenticated, least-privilege SSH forced commands with server-fixed node identities and private state path. Verify cross-node injection and command override rejection using actual transport.
5. Add the optional `--node-state` argument to the existing observer. Do not install a second observer or expose a new public HTTP port. A deployment restart/cutover needs its exact-source verification and is not included in this source preparation.
6. From each existing approved periodic telemetry hook, invoke the exporter once and deliver its bounded JSON stdin through its own scoped SSH profile. Do not start another coordinator, runner, scheduler or telemetry daemon. No existing laptop task/installation has been altered.
7. Verify actual receipts from both machines through an independent VPS connection, then disconnect one sender and prove contact expiry, stale-progress suppression, restart persistence and unchanged denial of permits. Native Windows/process checks and SSH transport isolation are separate acceptance evidence.

Illustrative commands after the above private transport/account configuration and exact-source validation:

```sh
python3 nexus_laptop_observations.py init --db /private/telemetry/nodes.sqlite3
python3 nexus_vps_arbiter_observer.py --serve --host 127.0.0.1 --port 8765 --node-state /private/telemetry/nodes.sqlite3
python3 nexus_laptop_observations.py snapshot --db /private/telemetry/nodes.sqlite3
```

The server-fixed receiver command for Laptop1 has the form:

```sh
python3 /reviewed/source/nexus_laptop_observations.py receive --db /private/telemetry/nodes.sqlite3 --authenticated-node DESKTOP-1R1081M
```

Laptop2 has a different forced identity. These example paths are not assertions about installed paths. A one-shot Windows export reads the caller-supplied existing checkpoint locations and can be piped to the already-reviewed scoped SSH profile; no credentials are accepted by the exporter.

```powershell
python nexus_laptop_observations.py export --source-sha EXACT_REVIEWED_40_HEX_SHA --heartbeat-file EXISTING_LOCAL_HEARTBEAT --research-status EXISTING_RESEARCH_STATUS
```

Local JSON replay or typing a hostname cannot satisfy physical two-node acceptance. Unit test reports use clearly synthetic fixtures and do not attest real devices.

## Verified source scope

Twenty-three local tests passed: 17 receipt/export/HTTP cases plus six existing observer tests. They cover identity mismatch, added authority/role fields, malformed/oversized payloads, source/counter/boolean bounds, future/naive/stale/reordered timestamps, duplicate replay without freshness extension, server clock rollback, SQLite restart/concurrency/corruption/missing state, per-component freshness and removal of private/error text.

The existing localhost restriction, host/kernel preflight and /readyz/permit HOLD/503 and mutation 403 behavior still pass. Code compiles under Python3.12.14/SQLite3.53.1. Local tests are developer contract evidence; full exact-head CI and real VPS/Windows transport checks remain required.

No Paper/Live/issuer/fencing authority is added. A heartbeat cannot permit writer takeover, research qualification, automatic dispatch, reboot, recovery or a third soak. Owner 500 USDT profile, installation and journal remain intact.

Before-change mapping: `docs/operations/LAPTOP_VISIBILITY_PRECHECK.md`. Test receipt/log: `docs/evidence/laptop-visibility-20261013/`.
