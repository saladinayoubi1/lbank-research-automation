# NEXUS-ARBITER-01 / VPS staging: strictly read-only observer

Scope: new Ubuntu 24.04 Mobinhost VPS `87.107.5.150`; 2 vCPU, ~3.8 GiB RAM, ~40 GiB disk.

## Authority boundary

This is a **read-only preflight observer**, NOT the final lease/fencing arbiter. It cannot issue, sign or accept Paper-writer grants. Its `/readyz` and `/writer-permit` endpoints ALWAYS return 503/HOLD and any mutation returns 403. It binds to `127.0.0.1:8765` only. Never publish its port externally.

Laptop 1 `DESKTOP-1R1081M` remains owner of the real 500-USDT Demo/Paper journal. Laptop 2 `DESKTOP-F4SA4VL` remains standby, and both failover Scheduled Tasks stay disabled. Live Trading is always disabled.

## Deployment checklist

- Confirm root console or secure key-based SSH access before changes. The earlier root password was exposed in chat imagery; rotate it via a secure channel, never GitHub or CLI history.
- Verify reviewed exact commit SHA, file SHA-256 and `python3 -m py_compile`; do NOT `curl | sh`. Stage files atomically in an isolated `/opt/nexus-arbiter/current` directory with root ownership. Do not overwrite owner laptops or ProductRuntime.
- Run `python3 -B /opt/nexus-arbiter/current/nexus_vps_arbiter_observer.py --once` and inspect fields `host_preflight`, `writer_authority=DISABLED`, and `paper_writer_grants_enabled=false`. It checks CPU, RAM, disk, uptime, SSH state, NTP, and all readable kernel journal entries for current boot. Inaccessible journal means HOLD.
- Put the reviewed systemd unit at `/etc/systemd/system/nexus-arbiter-observer.service`, inspect with `systemd-analyze verify`, then `systemctl daemon-reload && systemctl enable --now nexus-arbiter-observer`. Do not install or start if source integrity or tests fail.
- Verify `systemctl is-active nexus-arbiter-observer`, `ss -lntp`, `curl --max-time 5 http://127.0.0.1:8765/healthz`, `curl -i http://127.0.0.1:8765/readyz`. The second MUST be HOLD (503) even if the first is healthy (200). Confirm observer has no public listener.
- Keep a read-only 24-hour stability review: kernel lockups/RCU stalls, storage I/O, NTP sync, journal access, memory/disk availability and repeated service restarts. A single clean snapshot is not evidence of long-term reliability.
- Set up a dedicated local SSH key and verify login BEFORE disabling password or public root SSH. Check provider firewall and a safe rollback path before changing inbound rules. No private key should enter GitHub, the chat, or a shared clipboard.

## Real external-fencing gate remains blocked

Canonical `nexus_paper_writer_fence.py` implements signature, monotonically increasing epochs, checkpoint digests and freshness checks, but **is not connected to the existing failover task launchers or a physical external fencer**. Pure network disconnection or missing heartbeats can NEVER prove Laptop 1 has stopped writing. A legitimate failover must require a separately operated external fence, valid exclusive lease and epoch, preserved journal checkpoint, Paper-only authority, and rigorous power-loss/partition/reboot/failback tests on both laptops. GitHub is source-of-truth/evidence, not runtime lock database. No Demo takeover permitted until these acceptance gates pass.

Relevant: issue #2454.
