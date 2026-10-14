"""Provision a loopback-only repair broker over the already authenticated VPS SSH.

No trading, runner, firewall, root credential, or existing observer changes.
Only authenticated per-laptop *public* keys are accepted.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess

NODES = {"LAPTOP1": ("DESKTOP-1R1081M", 2201), "LAPTOP2": ("DESKTOP-F4SA4VL", 2202)}
USER = "nexusrescue"
ROOT = Path("/var/lib/nexus-vps-rescue")
CONFIG = Path("/etc/ssh/sshd_config")
KEY_DIR = Path("/etc/ssh/nexus-rescue-authorized-keys")
START = "# BEGIN NEXUS VPS RESCUE V1"
END = "# END NEXUS VPS RESCUE V1"


def validate_public_key(value: str, comment: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/]+={0,2} " + re.escape(comment), value):
        raise ValueError("Unexpected public key format/identity")
    blob = base64.b64decode(value.split()[1], validate=True)
    if len(blob) != 51 or blob[:19] != struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32):
        raise ValueError("Malformed Ed25519 public key")
    return value


def validate_exports(exports: list[dict]) -> dict[str, str]:
    if not isinstance(exports, list) or len(exports) != 2:
        raise ValueError("Exactly two authenticated laptop exports required")
    keys = {}
    for entry in exports:
        node = entry.get("node")
        if node not in NODES or node in keys or entry.get("hostname") != NODES[node][0] or entry.get("user") != "afaq":
            raise ValueError("Unknown, duplicated, or mismatched laptop identity")
        if entry.get("schema") != "nexus-rescue-forward-key-v1" or entry.get("private_key_exported") is not False:
            raise ValueError("Wrong export schema or private-key provenance")
        if entry.get("writer_authority") is not False or entry.get("live_enabled") is not False:
            raise ValueError("Repair is not writer authority")
        keys[node] = validate_public_key(entry["forward_public_key"], "NEXUS-RESCUE-" + node)
    if len({key.split()[1] for key in keys.values()}) != 2:
        raise ValueError("Forwarding identities must be distinct")
    return keys


def render_authorized_keys(keys: dict[str, str]) -> bytes:
    return ("\n".join(
        'restrict,port-forwarding,permitlisten="127.0.0.1:' + str(NODES[node][1]) + '" ' + keys[node]
        for node in NODES
    ) + "\n").encode("ascii")


def render_block() -> bytes:
    return f"""\n{START}
Match User {USER}
    AuthenticationMethods publickey
    PubkeyAuthentication yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AuthorizedKeysFile {KEY_DIR}/{USER}
    AllowTcpForwarding remote
    AllowStreamLocalForwarding no
    GatewayPorts no
    PermitListen 127.0.0.1:2201 127.0.0.1:2202
    PermitOpen none
    MaxSessions 0
    PermitTTY no
    X11Forwarding no
    AllowAgentForwarding no
    PermitTunnel no
    ClientAliveInterval 30
    ClientAliveCountMax 3
{END}
""".encode("ascii")


def run(*args: str, timeout: int = 15) -> str:
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args[0]}: {result.stderr[-2000:]}")
    return result.stdout


def effective(path: Path, user: str) -> dict[str, str]:
    lines = run("/usr/sbin/sshd", "-T", "-f", str(path), "-C", f"user={user},host=vm39793-59152.mobinhost.com,addr=127.0.0.1").splitlines()
    return dict(line.split(" ", 1) for line in lines if " " in line)


def no_symlink(path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError(f"Unexpected symlink: {path}")


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    no_symlink(path)
    temp = path.with_name(path.name + ".nexus-rescue-new")
    no_symlink(temp)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    os.fchmod(fd, mode)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def apply(keys: dict[str, str]) -> dict:
    if os.geteuid() != 0 or socket.gethostname() != "vm39793-59152.mobinhost.com":
        raise RuntimeError("Requires the authenticated existing NEXUS VPS root session")
    os.umask(0o077)
    for path in (ROOT, CONFIG, KEY_DIR):
        no_symlink(path)
    if not ROOT.is_dir() or ROOT.stat().st_uid != 0 or ROOT.stat().st_mode & 0o777 != 0o700:
        raise RuntimeError("Operator directory must already be root-owned mode 0700")
    old = CONFIG.read_bytes()
    block = render_block()
    auth = render_authorized_keys(keys)
    receipt_path = ROOT / "broker-receipt.json"
    no_symlink(receipt_path)
    if START.encode() in old:
        if old.count(block) != 1 or not receipt_path.exists() or (KEY_DIR / USER).read_bytes() != auth:
            raise RuntimeError("Existing rescue state differs: review instead of overwrite")
        receipt = json.loads(receipt_path.read_text())
        if hashlib.sha256(old).hexdigest() != receipt["sshd_config_sha256"]:
            raise RuntimeError("SSH configuration changed after installation")
        return {**receipt, "already_installed": True}
    if END.encode() in old or receipt_path.exists() or KEY_DIR.exists():
        raise RuntimeError("Partial broker state: inspect before adoption")
    try:
        run("getent", "passwd", USER)
    except RuntimeError:
        pass
    else:
        raise RuntimeError("Broker account already exists without ownership receipt")
    root_before = effective(CONFIG, "root")
    if root_before["passwordauthentication"] != "no" or root_before["kbdinteractiveauthentication"] != "no":
        raise RuntimeError("Existing key-only root baseline changed")
    candidate = ROOT / "sshd_config.candidate"
    if candidate.exists():
        raise RuntimeError("Unexpected prior candidate file")
    candidate.write_bytes(old + block)
    candidate.chmod(0o600)
    try:
        run("/usr/sbin/sshd", "-t", "-f", str(candidate))
        root_after = effective(candidate, "root")
        if root_before != root_after:
            raise RuntimeError("Candidate changes effective root SSH configuration")
        broker = effective(candidate, USER)
        expected = {"gatewayports": "no", "allowtcpforwarding": "remote", "allowstreamlocalforwarding": "no", "permitopen": "none", "maxsessions": "0", "passwordauthentication": "no", "kbdinteractiveauthentication": "no", "permittty": "no", "allowagentforwarding": "no", "authenticationmethods": "publickey", "permitlisten": "127.0.0.1:2201 127.0.0.1:2202"}
        for name, value in expected.items():
            if broker.get(name) != value:
                raise RuntimeError(f"Broker confinement mismatch: {name}")
        backup = ROOT / "sshd_config.before-rescue"
        if backup.exists():
            raise RuntimeError("Prior backup exists without installed receipt")
        backup.write_bytes(old)
        backup.chmod(0o600)
        run("useradd", "--system", "--create-home", "--home-dir", "/var/lib/nexus-rescue-broker", "--shell", "/usr/sbin/nologin", USER)
        KEY_DIR.mkdir(mode=0o755)
        KEY_DIR.chmod(0o755)
        atomic_write(KEY_DIR / USER, auth, 0o644)
        if CONFIG.read_bytes() != old:
            raise RuntimeError("Concurrent SSH config edit; refuse replacement")
        atomic_write(CONFIG, old + block, CONFIG.stat().st_mode & 0o777)
        try:
            run("/usr/sbin/sshd", "-t")
            run("systemctl", "reload", "ssh")
        except Exception:
            if CONFIG.read_bytes() == old + block:
                atomic_write(CONFIG, old, CONFIG.stat().st_mode & 0o777)
                run("systemctl", "reload", "ssh")
            raise
        receipt = {"schema": "nexus-rescue-broker-v1", "hostname": socket.gethostname(), "sshd_config_sha256": hashlib.sha256(old + block).hexdigest(), "previous_sshd_config_sha256": hashlib.sha256(old).hexdigest(), "authorized_public_keys_sha256": hashlib.sha256(auth).hexdigest(), "relay_addresses": ["127.0.0.1:2201", "127.0.0.1:2202"], "root_effective_config_unchanged": True, "firewall_changed": False, "public_ports_added": False, "windows_route_accepted": False, "writer_authority": False, "live_enabled": False}
        atomic_write(receipt_path, (json.dumps(receipt, indent=2) + "\n").encode())
        return receipt
    finally:
        candidate.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exports", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    keys = validate_exports(json.loads(args.exports.read_text()))
    print(json.dumps(apply(keys) if args.apply else {"valid": True, "nodes": list(keys), "mutation_performed": False, "writer_authority": False, "live_enabled": False}, indent=2))


if __name__ == "__main__":
    main()
