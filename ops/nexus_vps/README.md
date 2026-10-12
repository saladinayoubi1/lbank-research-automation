# VPS commissioning checkpoint — 12 October 2026

This directory records the configuration and exact diagnostic worker already running on the VPS. It does not install or activate a Paper writer, permit issuer, failover controller, or trading strategy. Issue #2454 remains open.

## Verified state

- The dedicated SSH key successfully reconnects after firewall apply and reload. Existing SSH remains key-only.
- nftables is enabled and active. The owned `inet nexus_host` table drops inbound/forward traffic by default, allows inbound TCP 22, loopback, established/related traffic and ICMP, and allows outbound traffic.
- Six input rules remain after reload. The observer listens on localhost port 8765; Laptop 1 could not establish an external TCP connection to port 8765.
- The rollback checkpoint was confirmed; its transient timer is inactive.
- Existing `nexus-arbiter-observer` was reused without changes. All seven health checks passed.
- At 2026-10-12 13:13 Tehran, the finite soak unit was active, with 31 samples and about 30 minutes of coverage. Its recorded SHA-256 chain was replayed and matched the atomic status checkpoint. Maximum observed gap was 60.402 seconds.
- Paper grants, Live authority and external fencing verification remain false. Laptop 2 was offline at the latest device query; its current task state has not been verified.

The complete checkpoint is in `checkpoint_20261012.json`. These are observations at stated times, not a completed 24-hour qualification.

## Exact source snapshots

| File | Deployed path / SHA-256 |
| --- | --- |
| `soak_20261012.py` | `/var/lib/nexus-vps-commissioning/soak-20261012/worker.py`; `a7aefabf7c51abdc5bc97219a59cc4bdb664d57915a4fd1929e0ca81b02ead17` |
| `nexus_host.nft` | `/etc/nftables.conf`; `8a396dd278409d3330481094593f5c6fdbc9dbb2c59de20c08d1d0fa75fd6964` |
| `nftables.service.override.conf` | `/etc/systemd/system/nftables.service.d/90-nexus-owned-table.conf` |

The observer source is `/opt/nexus-arbiter/current/nexus_vps_arbiter_observer.py`, SHA-256 `22a5a33385776befba943d3b2188cfaa23fbf6fb3d9981596f17a6c9a56693c1`. The SSH drop-in SHA-256 is `10a3b8543c1eaa63554520f5bcafcf57ea73069d7cf83b27b0515cbe83355ee2`.

## Durable continuation

The existing `nexus-vps-soak-20261012` transient systemd service continues independently of the chat and SSH session. It uses a 5% CPU quota, 96 MiB memory limit, no automatic restart, a 25-hour runtime limit, and write access confined to its commissioning directory. Its first sample started at 2026-10-12 09:13:00.375411 UTC. Earliest 24-hour completion is **13 October 2026 at 12:43 Tehran**.

Read the existing state on the VPS; do not restart this one-off worker or append a second run to its sample file:

```sh
systemctl show nexus-vps-soak-20261012 -p ActiveState -p SubState -p Result -p MainPID
cat /var/lib/nexus-vps-commissioning/soak-20261012/status.json
sha256sum /var/lib/nexus-vps-commissioning/soak-20261012/worker.py
```

The collector samples once per minute and requires at least 86,400 seconds measured using CLOCK_BOOTTIME and 1,441 samples. A gap over 90 seconds, a changed boot identity or bound source, observer stop/restart, stale or failed health response, changed authority flags, or missing/dangerous current-boot kernel log produces FAILED. Each sample is fsynced, links the previous digest, and is followed by an atomic status update.

A stopped process or reboot does not yield COMPLETE. A future attempt must be a separately approved new observation window, with a separate directory and manifest; it cannot inherit the previous duration.

After the window, inspect the terminal unit result, replay the entire sample chain against `status.json`, and verify duration, sample count, maximum gap, boot identity and source hashes. Preserve the final evidence in this issue before advancing commissioning. COMPLETE is only host/observer continuity evidence: it does not prove continuous external network reachability or positive external fencing and does not authorize writer admission.

## Boundaries and remaining work

The owner app, profile, Paper journal and Laptop 1 writer were not changed. This snapshot introduces no workflow, secret, scheduled chat automation or execution hook. Merge or redeployment is not required for the already-running diagnostic collector.

Real fencing, epoch/permit issuance, takeover integration and partition tests remain gated. No failover or Live trading has been enabled. Laptop 2's offline state blocks its fresh local verification only.

## Validation

The exact worker passed Python compilation and its SHA-256 matched the deployed manifest. The running worker produced real host samples; a separate reader replayed all 31 checkpointed samples and matched the last digest. Firewall syntax, reload, fresh SSH reconnect, localhost health, inactive rollback timer and external port 8765 refusal were checked. The full 24-hour result is pending.
