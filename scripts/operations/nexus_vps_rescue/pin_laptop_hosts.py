"""Pin laptop SSH host keys from authenticated post-UAC public device exports.

Run as the new VPS nexuscontrol user (or its administrator). No key scanning,
trust-on-first-use, private-key import, or writer/failover actions.
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

NODES = {"LAPTOP1": ("DESKTOP-1R1081M", 2201), "LAPTOP2": ("DESKTOP-F4SA4VL", 2202)}
HOME_DIR = Path('/var/lib/nexus-rescue-control')


def validated_lines(exports: list[dict], authorized: str) -> str:
    if not isinstance(exports, list) or len(exports) != 2:
        raise ValueError('Both authenticated Windows installation exports required')
    seen = set(); host_material = set(); lines = []
    for entry in exports:
        node = entry.get('node')
        if node not in NODES or node in seen or entry.get('hostname') != NODES[node][0] or entry.get('port') != NODES[node][1]:
            raise ValueError('Unknown, repeated, or mismatched laptop')
        seen.add(node)
        if entry.get('schema') != 'nexus-rescue-install-v1' or entry.get('status') != 'INSTALLED_PENDING_VPS_SSH_ACCEPTANCE':
            raise ValueError('Windows installation is not ready for acceptance')
        if entry.get('writer_authority') is not False or entry.get('live_enabled') is not False:
            raise ValueError('Repair transport does not grant writer authority')
        forward = entry.get('forward_public_key', '')
        expected = 'restrict,port-forwarding,permitlisten="127.0.0.1:' + str(NODES[node][1]) + '" ' + forward
        if expected not in authorized.splitlines() or not forward.endswith(' NEXUS-RESCUE-' + node):
            raise ValueError('Forwarding identity does not match the registered laptop')
        host = entry.get('host_public_key', '')
        if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+={0,2} NEXUS-RESCUE-HOST-' + node, host):
            raise ValueError('Unexpected SSH host public-key identity')
        blob = base64.b64decode(host.split()[1], validate=True)
        host_material.add(host.split()[1])
        if len(blob) != 51 or blob[:19] != struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 32):
            raise ValueError('Malformed host public key')
        fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
        if fingerprint not in entry.get('host_fingerprint', '').split():
            raise ValueError('Host fingerprint mismatch')
        lines.append('[127.0.0.1]:' + str(NODES[node][1]) + ' ' + ' '.join(host.split()[:2]))
    if len(host_material) != 2:
        raise ValueError('Laptop SSH host identities must be distinct')
    return '\n'.join(sorted(lines)) + '\n'


def main() -> None:
    import pwd
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exports', type=Path)
    args = parser.parse_args()
    account = pwd.getpwnam('nexuscontrol')
    if socket.gethostname() != 'vm39793-59152.mobinhost.com' or os.geteuid() not in (0, account.pw_uid):
        raise SystemExit('Expected authenticated VPS control identity')
    data = validated_lines(json.loads(args.exports.read_text()), Path('/etc/ssh/nexus-rescue-authorized-keys/nexusrescue').read_text())
    target = HOME_DIR / '.ssh/laptop-known-hosts'
    if target.is_symlink() or not target.is_file():
        raise SystemExit('Expected existing private control SSH directory')
    if target.read_text() not in ('', data):
        raise SystemExit('A laptop identity changed: review before replacement')
    if not target.read_text():
        temporary = target.with_suffix('.new')
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chown(temporary, account.pw_uid, account.pw_gid)
        os.replace(temporary, target)
    print(json.dumps({'pinned_nodes': sorted(NODES), 'known_hosts_sha256': hashlib.sha256(data.encode()).hexdigest(), 'windows_ssh_accepted': False, 'writer_authority': False, 'live_enabled': False}))


if __name__ == '__main__':
    main()
