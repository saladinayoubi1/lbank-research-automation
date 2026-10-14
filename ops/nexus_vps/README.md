# VPS commissioning evidence — 13 October 2026

## Current state: unqualified / HOLD

Both finite observation windows have terminated FAILED. Neither projected completion deadline remains active. The observer exposes no Paper grant, Live authority or verified external fencing. Issue #2454 remains open.

| Window | Running kernel | Retained samples | Elapsed at failure | Terminal cause |
| --- | --- | ---: | ---: | --- |
| soak-20261012 | 6.8.0-31-generic | 805 | 48,345.999 seconds | Current-boot kernel danger |
| soak-20261013-kernel146 | 6.8.0-146-generic | 4 | 728.768 seconds | Observer health HTTP 503 |

The original dated checkpoint in `checkpoint_20261012.json` is a historical 31-sample observation. The latest terminal states and maintenance evidence are in `checkpoint_20261013.json`. The full four-row replacement chain has not been independently replayed.

## Remediation and verification

The exact official Ubuntu GA update was simulated, all 192 MB were downloaded, then installation used the local APT cache. Five related packages were upgraded, seven new kernel packages installed and none removed. The native install service exited zero at 2026-10-13 02:46:28 Tehran. The new image, modules, 65 MB initramfs and GRUB default entry were verified. Both the prior image and initramfs remain available for recovery.

A controlled reboot activated 6.8.0-146-generic. Fresh key-only SSH verified boot `50654191-72f1-4854-840e-f8a21ac6eedc`. All seven preflight checks passed after the required 60-second startup period. nftables was active, its six input rules and drop/drop/accept policies were verified, and all three bound source hashes remained unchanged. The observer was PID 707 with zero restarts.

The replacement window reused the existing collector with only its output-directory literal changed. It started with its own manifest, boot binding and duration clock. The original manifest, failed status, worker and kernel archive were byte-verified before setup and preserved. Prior duration was not inherited. The finite service retained the 5% CPU quota, 96 MiB memory limit, no automatic restart, 25-hour runtime limit and directory-confined write access.

The second run also failed. The new boot journal records CPU soft lockup for 39 seconds, missed RCU timer wakeups and RCU thread starvation. Current health remains HOLD with two kernel danger matches. A later one-second vmstat snapshot was 99% idle, zero steal and no swap activity. That snapshot does not identify the transient cause or establish hypervisor health.

Pinned SSH authentication and a minimal command succeeded, and Laptop 2 received the OpenSSH banner. Windows commands that do not consume input now use explicit null stdin. A transport timeout is never evidence of a stopped owner or permission for takeover.

## Source and forensic bindings

| Artifact | SHA-256 |
| --- | --- |
| Existing observer source | 22a5a33385776befba943d3b2188cfaa23fbf6fb3d9981596f17a6c9a56693c1 |
| nftables configuration | 8a396dd278409d3330481094593f5c6fdbc9dbb2c59de20c08d1d0fa75fd6964 |
| Key-only SSH drop-in | 10a3b8543c1eaa63554520f5bcafcf57ea73069d7cf83b27b0515cbe83355ee2 |
| Original collector | a7aefabf7c51abdc5bc97219a59cc4bdb664d57915a4fd1929e0ca81b02ead17 |
| Replacement collector | c9230b7e0c1ab90069e7bc096d3b86d2673d8cbbca0ad105ea6ddfeb92c777c7 |
| Original terminal status | 5c8db763d95ba24cbc6687b1779bf447bb1be9ed55a9be9cf57064c1374c46ac |
| Replacement terminal status | a6ab17a5bc1aa12fb29d44b6971fd4a4d3cc2345bcb243b9d383a24febc8feea |
| Original kernel failure archive | 5b6707cf34c01ca78d32b47908895baec14c8e9e669af3c2f6bde84eca9715a3 |
| Post-update kernel failure archive | 18e3ac6bf41f123fda3c0978914806e455cb82bc61248a4ddf88b224c681a348 |

`soak_20261012.py` and `soak_20261013_kernel146.py` are exact deployed snapshots. The other configuration snapshots retain their previous identity.

## Continuation

Inspect the terminal evidence; preserve both directories and their receipts:

```sh
cat /var/lib/nexus-vps-commissioning/soak-20261012/status.json
cat /var/lib/nexus-vps-commissioning/soak-20261013-kernel146/status.json
systemctl show nexus-arbiter-observer -p ActiveState -p MainPID -p NRestarts
```

The exact cause remains unproven. Request investigation for service 59152 / 87.107.5.150 at the VM/virtualization layer, including vCPU scheduling or pauses, virtual clock/timer delivery and virtio networking. Repair the underlying cause or migrate the VM while preserving its disk, access and evidence. No provider message has been sent.

After remediation, an authorized new window must use a separate directory and manifest. It requires at least 86,400 seconds using CLOCK_BOOTTIME, 1,441 samples, no gap over 90 seconds, unchanged boot/source/observer identity and a valid full sample chain. No third window or repeated reboot has been launched. Watchdog and coverage checks remain unchanged.

Host/observer continuity is a separate gate from continuous external reachability, positive peer fencing, epoch/permit issuance, writer admission and physical partition/failover/failback tests. No failover or Live authority was enabled. The owner app, profile and Paper journal were preserved. This evidence PR introduces no workflow, execution hook or chat automation.
