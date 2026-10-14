# NEXUS laptop repair access through the existing VPS

The VPS broker is installed and real loopback tunnel round trips passed for both laptops. Each forwarding key was also denied access to the other laptop's port. Windows SSH and its persistent tunnel task are **not installed yet**: the current afaq RDC sessions are not elevated. The separate Linux RDC service is active and waiting for the account owner's device authorization. This is preparation plus verified transport, **not completed administrative repair access**.

The owner-facing desktop launcher is `C:\Users\afaq\Desktop\NEXUS-Enable-Rescue.cmd` on each laptop. It checks the frozen bundle manifest and opens the reviewed installer through Windows UAC. Run it under the existing afaq account on both laptops and approve UAC. Separately authorize the VPS device in the existing Desktop Commander account using the fresh verification link supplied by its agent. Device codes are transient and are deliberately excluded from this repository.

| Device | Authenticated RDC identity | VPS loopback relay | Laptop SSH endpoint |
| --- | --- | --- | --- |
| LAPTOP1 / DESKTOP-1R1081M | bbabb808-d554-4db8-bce7-3a453bea8b43 | 127.0.0.1:2201 | 127.0.0.1:22, pending UAC |
| LAPTOP2 / DESKTOP-F4SA4VL | 61c3307f-e6d4-4edf-860a-3519cfb9df5d | 127.0.0.1:2202 | 127.0.0.1:22, pending UAC |

## Scope and authority

This work belongs to existing map nodes OBS-80 and CTRL-11. RUNTIME-60, PAPER-62, PAPER-63, and SAFE-64 authority is unchanged. LAPTOP1 remains the only Paper writer; LAPTOP2 remains research primary; Live and failover remain disabled. Repair services never start trading, research, runner, supervisor, or writer processes. Existing application profiles, authentication, journals, checkpoints, RDC tasks, and NEXUS directory ACLs are preserved.

The VPS is vm39793-59152.mobinhost.com / 87.107.5.150. It remains an optional repair transport: the two earlier kernel soak failures and the observer health timeout are not repaired or cleared by successful SSH. No third soak, reboot, observer reconfiguration, or writer/fencer grant is performed.

## Installed VPS components

`nexusrescue` is a new unprivileged forwarding account with no shell sessions (`MaxSessions 0`), PTY, agent, local TCP, or Unix forwarding. Password and keyboard authentication are disabled. Remote TCP forwarding is confined to the two loopback ports. The distinct per-laptop authorized keys additionally permit only their own port. Root's effective SSH configuration was checked unchanged before atomic replacement and reload; a private exact backup is retained. The public firewall remains unchanged and no public port was added.

`nexus-rescue-control.service` runs as new unprivileged `nexuscontrol`, with no sudo, no new privileges, system/home filesystem protections, a private writable service home, 512 MB memory cap, 50% CPU quota, and restart on failure. It uses an isolated official Node v22.23.3 installation and Desktop Commander 0.3.0. The Node archive checksum and package SHA512 integrity were verified; lifecycle scripts were disabled and the resolved dependency lock digest was retained. This service has its own owner-approved pairing; Windows device tokens are never copied.

The dedicated repair operator key was generated on this VPS and moved **within the same VPS** to `/var/lib/nexus-rescue-control/.ssh/operator_ed25519`, mode 0600, owned by nexuscontrol. It was never exported. Its public fingerprint is `SHA256:JAZ2pz+AwXMrZRwPOHFPpozI3q7zVV3MCNUj1X4MzO0`. A private relocation marker prevents accidental regeneration. The existing root management key remains on LAPTOP1 and is not copied.

The account pairing step is required to let this conversation reach the VPS when both Windows RDC agents fail. Its Linux agent is separate from those agents, but uses the same RDC provider. Provider-wide outages are not covered by that agent. The laptops must remain powered and have Internet access.

## Reviewed Windows installation

The staged bundle is `E:\NEXUS-QA\vps-rescue-20261014` on both devices. The installer refuses an existing sshd, rescue directory, task, or conflicting port. The elevated loader checks the frozen manifest and installer digest again, then executes the verified installer bytes. Bundle scripts/pins are captured and checked as bytes in the private Administrators-owned directory before optional feature installation; the copied forward key must derive the exact public identity already registered for that laptop. Only the Windows optional OpenSSH Server capability is installed; no broad update or automatic reboot occurs. An owned inbound TCP-22 block is created before capability installation, the automatically created public allow rule is disabled, and sshd binds only 127.0.0.1. The existing afaq account accepts only the new VPS operator public key, with password authentication and forwarding disabled.

The owner-reported first installation stopped before any system mutation because `Get-NetTCPConnection` could not connect to the Windows CIM server. The replacement uses .NET IP Helper for listeners, explicit Service Control Manager access for sshd, Firewall COM, and Task Scheduler COM. It does not repair/reset WMI or depend on CIM providers. Native readiness exercises these same APIs before elevation; the TCP guard observes an ephemeral owned loopback listener and its closure, and the task definition is validated in memory without registration. The returned SYSTEM account name is resolved back to SID S-1-5-18 before accepting its identity. Task registration uses create-only flag 2, so an existing task cannot be updated accidentally.

New private material and configuration are confined to `C:\ProgramData\NEXUS-Rescue`, with SYSTEM/Administrators-only ACLs. The forward key stays on its originating laptop. Its public key was previously registered on the VPS. Git's existing SSH client creates the outbound tunnel using the previously pinned RSA host identity; neither Tailscale nor an inbound laptop port is required.

Exactly one new repair-only startup task, `NEXUS-Rescue-Tunnel`, runs as SYSTEM. A mutex prevents concurrent owners, and a Windows job object kills its owned SSH child when the parent closes or dies. Reconnect is bounded to a maximum 30-second backoff. Installed source and client hashes and the owned sshd image path are checked. Only that new SSH service can be restarted. Private logs rotate at 1 MB. Installer failures stop/disable new sshd and its repair task; owned evidence and the public install receipt are retained for review.

## Acceptance after the owner's two actions

1. Read `public\installed-public.json` from both authenticated devices. Both must say `INSTALLED_PENDING_VPS_SSH_ACCEPTANCE` and include the registered forward key plus the newly generated SSH host public key/fingerprint. Never read or transfer private keys.
2. Import only those two public receipts to the VPS control home. Run `/opt/nexus-rescue-control/pin_laptop_hosts.py` as nexuscontrol, passing that JSON array. The helper checks node, hostname, port, registered forwarding identity, distinct host keys, and fingerprints. An identity change is refused. No `ssh-keyscan`, trust-on-first-use, or disabled host checking is used.
3. Confirm the VPS appears independently in `list_devices`; record its new identity. Then use `ssh -F /var/lib/nexus-rescue-control/.ssh/config NEXUS-LAPTOP1 whoami` and the LAPTOP2 alias. Check actual exit codes, hostname, and Administrator membership with a bounded PowerShell probe before claiming repair capability.
4. Validate an innocuous repair/read probe and reconnection while laptop RDC agents are unavailable. Preserve authentication and application state. Record source digests, owned process IDs, actual exits, listeners, and any failures in a new acceptance receipt. Until these checks pass, `independent_control_accepted` and `windows_ssh_accepted` remain false.

For future RDC repair, first inspect the exact existing RDC launch task, executable, configuration ownership, and current process. Restart only its verified owned task/process if needed. Do not recreate device credentials, reset WMI, widen application ACLs, restart unrelated NEXUS services, or start a second Paper writer. An SSH administrative command is not an interactive desktop session; GUI repair may require the existing logged-in user task.

## Recovery and rollback

Retain the original root SSH connection until a fresh pinned root connection succeeds after a broker change. Root SSH was verified again by the later control-service installation and transport probes. To roll back the broker, verify the current config equals its recorded installed digest and the private backup equals the previous digest; syntax-check the backup candidate, restore atomically, reload SSH, and verify a fresh pinned root connection. Do not replace a concurrently changed SSH config. Stop/remove only the owned control service and broker account/key entries after checking their ownership and digests.

On Windows, stop the owned repair task and its job-contained tunnel, then stop the new sshd only after its installed image path and configuration match the receipt. Unregister only `NEXUS-Rescue-Tunnel`. Preserve private identities and receipts until the owner decides to retire them. Remove only the owned rescue firewall rule/directory; do not re-enable the public OpenSSH allow rule or touch any existing RDC/Paper/research task. The optional Server capability was absent before this work and can be removed if retiring this installation; no automatic uninstall/reboot is performed.

## Evidence

`docs/evidence/nexus-vps-rescue-20261014/current-checkpoint.json` records the actual deployed broker/control digests and pending owner actions. Twelve source/config/key-pinning tests pass in the local Linux gate, including actual sshd interpretation. Both native Windows parsers, bundle readback hashes, non-elevated inspection, and owned-job child cleanup pass. Both real VPS-to-laptop test markers match, cross-node forwarding is rejected, and the temporary listeners are closed. These temporary tests did not install sshd or persistent Windows tasks.

The earlier v10 research head remains `21b8f03af4bf5dab1f8c0830d81d1d5753cdbedb`; its required hosted CI checks passed on Windows, macOS, and Ubuntu. Its native source gate and first producer are still pending, with zero v10 market replay runs. No observed research fold is replayed or retuned here.

The CIM-free replacement passed native child processes with exit 0 on LAPTOP1 (31.07 seconds) and LAPTOP2 (4.68 seconds), with empty stderr. The frozen desktop launcher was replaced only after success on each device. Public receipts are in `docs/evidence/nexus-vps-rescue-20261014/cim-free-native-qa.json`. These checks did not register a task, start sshd, or exercise elevated firewall writes. Administrative installation and direct VPS SSH acceptance still require the owner actions above.
