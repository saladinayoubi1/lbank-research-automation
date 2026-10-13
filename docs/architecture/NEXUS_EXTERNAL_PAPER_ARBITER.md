# External Paper arbiter deployment

Scope: Issue #2454; RUNTIME-60, PAPER-62, PAPER-63, OBS-80, SAFE-64.
The two laptops retain their existing System Map roles. This is a separate
authority service, not another trading runtime, runner, or research scheduler.

## Implemented boundary

`nexus_external_paper_arbiter.py` issues RSA/SHA-256 permits compatible with
`nexus_paper_writer_fence.py`. SQLite `BEGIN IMMEDIATE` serializes the positive
fencing operation and permit issuance across service instances sharing the
same persistent volume. A current-proof check is serialized with issuance too.
The issuer commits the permit before returning it and retains epochs, used
nonces, trust identity and signed permit integrity across restarts.

There is one active lease at a time. A new request, including a recovered
writer's request, cannot displace an unexpired lease. Missing/corrupt state,
clock rollback, changed key, expired lease, unavailable controller or incomplete
fencing observation deny authority. No API accepts client-supplied fence claims.
There is no Live authority or trading loop here. The journal checkpoint digest
is supplied by the authenticated writer and must also match the independently
restored real ProductRuntime checkpoint at the writer; signing alone does not
prove checkpoint continuity.

## Deployable standby, not physical failover qualification

The CLI deliberately uses `unavailable_fence`. Both `/healthz` and launch output
report `takeover_enabled=false`. There is no HTTP switch, environment flag,
manual JSON receipt import, or signing-key distribution that enables takeover.
An authenticated permit request still denies until an actual external fencing
controller is implemented and independently physically qualified.

The controller must positively stop the peer and inhibit restart through the
lease plus a safety margin. It must bind fresh observations to both machine
identities, request nonce, controller identity and hold duration. The trusted
adapter must obtain these observations itself through an independently
authenticated control channel. A network timeout, a laptop's assertion,
an unchecked receipt digest, or an offline test fixture is insufficient.
Current permit retrieval rechecks the external fence; controller loss denies
new authority. Fencing latency consumes the original requested TTL.

## Independent Linux deployment

Prerequisites: a separate persistent Linux server, root deployment access,
Python 3.12 or later, OpenSSL, systemd, and an exact clean verified Git checkout.
The selected host must be external to both laptops; a VM/WSL instance on either
laptop and the transient Codex executor do not meet that deployment requirement.

On that independently selected server only:

```sh
bash scripts/install_nexus_external_paper_arbiter.sh /absolute/verified/repository EXACT_40_HEX_SHA
```

The installer requires fresh paths and refuses to overwrite an existing
authority. It creates a dedicated service account, durable private state and
3072-bit private signing key on that server. It installs only two Python files
and an exact-source marker. It starts one systemd service bound to loopback in
standby. It does not modify either laptop, enable failover tasks, download
exchange credentials, alter an owner profile, or reset Paper capital.

The private key and complete writer-token file stay on the server and never
enter GitHub, an artifact, the Library, a log or either laptop. If client
integration is later qualified, each laptop receives only its own scoped API
token and the public trust root over an authenticated private channel.
Publish the API only behind verified HTTPS/private networking. The Python CLI
requires configured TLS for non-loopback listening. Never distribute a
production key generated on a writer or in the transient executor.

State is `/var/lib/nexus-paper-arbiter/authority.sqlite3`, outside the Git tree.
The service never initializes missing state during restart. Backups/restoration
and migration require an independent epoch/key continuity review; never clone
one authority's key and volume into two independently serving arbiters.

## Before enabling takeover

1. Verify independent host, exact deployed SHA, private permissions, persistent
   storage and restart continuity; preserve a sanitized deployment receipt.
2. Integrate and physically verify the external controller and restart inhibition.
3. Bind both existing writer paths to mandatory fresh proof at each write;
   verify exact journal/checkpoint restoration. An optional verifier is insufficient.
4. Perform partition-with-primary-alive, stale/replay, checkpoint mismatch,
   controller/arbiter loss, primary recovery, failback and reboot drills.
5. Only after independent evidence proves one writer throughout may the existing
   two standby tasks be enabled. Live remains false and Protective Exit remains
   reduce/close only throughout.

Local contract and HTTP tests are preparation evidence, not deployment or
physical fencing proof. Initial rollback is to stop/disable the new server
service while retaining its state for review; do not erase epochs or keys to
recover availability. The owner continues under the existing unchanged setup.
