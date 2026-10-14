"""Install an isolated, pinned Linux RDC repair gateway; owner pairs it separately.

No copied laptop device credentials, public listeners, trading changes, or reboot.
The new repair identity moves only within this VPS into its dedicated service user.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import socket
import subprocess
import tarfile
import urllib.request

USER = "nexuscontrol"
OPT = Path("/opt/nexus-rescue-control")
HOME_DIR = Path("/var/lib/nexus-rescue-control")
KEY_ROOT = Path("/var/lib/nexus-vps-rescue")
NODE_VERSION = "v22.23.3"
PACKAGE = "@wonderwhy-er/desktop-commander"
VERSION = "0.3.0"
INTEGRITY = "sha512-2EXNxuztSIW3fQw6OEGMek39M8yQlKinXooMYtNR4wRLhtA+f3b0cbxBggAfDeKemMWltm1qWQy/t2Av9VmYLw=="


def run(*args: str, timeout: int = 20, env: dict | None = None) -> str:
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {result.stderr[-3000:]}")
    return result.stdout.strip()


def https(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "NEXUS-Rescue-Setup/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.geturl().split('/')[2] != url.split('/')[2]:
            raise RuntimeError("Unexpected download redirect")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("Download exceeds expected maximum")
    return data


def main() -> None:
    if os.geteuid() != 0 or socket.gethostname() != "vm39793-59152.mobinhost.com" or platform.machine() != "x86_64":
        raise SystemExit("Expected authenticated existing x64 VPS root session")
    for path in (OPT, HOME_DIR, KEY_ROOT / 'operator-identity-relocated.json', Path('/etc/systemd/system/nexus-rescue-control.service')):
        if path.exists() or path.is_symlink():
            raise SystemExit(f"Existing control-gateway state: inspect instead of overwrite: {path}")
    try:
        pwd.getpwnam(USER)
    except KeyError:
        pass
    else:
        raise SystemExit("Control user exists without installation ownership")
    if not (KEY_ROOT / 'operator_ed25519').is_file() or (KEY_ROOT / 'operator_ed25519').is_symlink():
        raise SystemExit("Expected existing private VPS repair identity")
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))) * 1024
    if available < 300 * 1024**2 or shutil.disk_usage('/opt').free < 1536 * 1024**2:
        raise SystemExit("Insufficient available resources for isolated package installation")
    os.umask(0o022)
    OPT.mkdir(mode=0o755)
    receipt = {"schema": "nexus-rescue-control-install-v1", "hostname": socket.gethostname(), "node_version": NODE_VERSION, "package": PACKAGE, "package_version": VERSION, "package_integrity": INTEGRITY, "status": "INSTALLING", "private_key_exported": False, "writer_authority": False, "live_enabled": False}
    receipt_path = OPT / 'installation-receipt.json'
    try:
        filename = f'node-{NODE_VERSION}-linux-x64.tar.xz'
        release = f'https://nodejs.org/dist/{NODE_VERSION}/'
        sums = https(release + 'SHASUMS256.txt', 100000).decode()
        matches = [line.split()[0] for line in sums.splitlines() if line.split()[-1] == filename]
        if len(matches) != 1 or len(matches[0]) != 64:
            raise RuntimeError("Official Node checksum missing/ambiguous")
        archive = OPT / filename
        archive.write_bytes(https(release + filename, 80 * 1024**2))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != matches[0]:
            raise RuntimeError("Official Node archive SHA256 mismatch")
        receipt['node_archive_sha256'] = digest
        (OPT / 'SHASUMS256.txt').write_text(sums)
        with tarfile.open(archive) as tar:
            prefix = filename.removesuffix('.tar.xz')
            if any(member.name.split('/')[0] != prefix for member in tar.getmembers()):
                raise RuntimeError("Unexpected Node archive prefix")
            tar.extractall(OPT, filter='data')
        node_root = OPT / filename.removesuffix('.tar.xz')
        node = node_root / 'bin/node'
        npm = node_root / 'lib/node_modules/npm/bin/npm-cli.js'
        if run(str(node), '--version') != NODE_VERSION:
            raise RuntimeError("Installed Node version mismatch")
        meta = json.loads(https('https://registry.npmjs.org/@wonderwhy-er%2fdesktop-commander/' + VERSION, 2000000))
        if meta['name'] != PACKAGE or meta['version'] != VERSION or meta['dist']['integrity'] != INTEGRITY:
            raise RuntimeError("Published package identity changed")
        tgz = https(meta['dist']['tarball'], 16 * 1024**2)
        if base64.b64encode(hashlib.sha512(tgz).digest()).decode() != INTEGRITY.split('-', 1)[1]:
            raise RuntimeError("Published package archive integrity mismatch")
        (OPT / 'desktop-commander-0.3.0.tgz').write_bytes(tgz)
        project = OPT / 'agent'
        project.mkdir(mode=0o755)
        (project / 'package.json').write_text(json.dumps({'private': True, 'name': 'nexus-rescue-control', 'version': '1.0.0'}) + '\n')
        env = dict(os.environ)
        env.update({'PATH': str(node_root / 'bin') + os.pathsep + env.get('PATH', ''), 'NODE_OPTIONS': '--max-old-space-size=256', 'PUPPETEER_SKIP_DOWNLOAD': 'true', 'npm_config_cache': str(OPT / 'npm-cache')})
        run(str(node), str(npm), 'install', '--prefix', str(project), '--ignore-scripts', '--no-audit', '--no-fund', '--omit=dev', '--save-exact', PACKAGE + '@' + VERSION, timeout=240, env=env)
        lock = json.loads((project / 'package-lock.json').read_text())
        locked = lock['packages']['node_modules/' + PACKAGE]
        if locked['version'] != VERSION or locked['integrity'] != INTEGRITY:
            raise RuntimeError("Lockfile package integrity mismatch")
        receipt['dependency_lock_sha256'] = hashlib.sha256((project / 'package-lock.json').read_bytes()).hexdigest()
        entry = project / 'node_modules' / PACKAGE / 'dist/index.js'
        if 'Remote MCP device' not in run(str(node), str(entry), 'remote', '--help', timeout=30, env=env):
            raise RuntimeError("Pinned remote-agent help check failed")
        run('useradd', '--system', '--create-home', '--home-dir', str(HOME_DIR), '--shell', '/bin/bash', USER)
        account = pwd.getpwnam(USER)
        HOME_DIR.chmod(0o700)
        ssh_dir = HOME_DIR / '.ssh'
        ssh_dir.mkdir(mode=0o700)
        os.chown(ssh_dir, account.pw_uid, account.pw_gid)
        for suffix in ('', '.pub'):
            source = KEY_ROOT / ('operator_ed25519' + suffix)
            target = ssh_dir / ('operator_ed25519' + suffix)
            os.rename(source, target)
            target.chmod(0o600)
            os.chown(target, account.pw_uid, account.pw_gid)
        relocated = {'schema': 'nexus-rescue-identity-relocation-v1', 'identity_path': str(ssh_dir / 'operator_ed25519'), 'owner': USER, 'same_vps_only': True, 'private_key_exported': False}
        relocation_path = KEY_ROOT / 'operator-identity-relocated.json'
        relocation_path.write_text(json.dumps(relocated, indent=2) + '\n')
        relocation_path.chmod(0o600)
        known = ssh_dir / 'laptop-known-hosts'
        known.write_text('')
        known.chmod(0o600)
        os.chown(known, account.pw_uid, account.pw_gid)
        config = ssh_dir / 'config'
        config.write_text('Host NEXUS-LAPTOP1\n    HostName 127.0.0.1\n    Port 2201\nHost NEXUS-LAPTOP2\n    HostName 127.0.0.1\n    Port 2202\nHost NEXUS-LAPTOP1 NEXUS-LAPTOP2\n    User afaq\n    IdentityFile ' + str(ssh_dir / 'operator_ed25519') + '\n    IdentitiesOnly yes\n    BatchMode yes\n    StrictHostKeyChecking yes\n    UserKnownHostsFile ' + str(known) + '\n    HostKeyAlgorithms ssh-ed25519\n    ConnectTimeout 8\n    ConnectionAttempts 1\n    ServerAliveInterval 5\n    ServerAliveCountMax 2\n')
        config.chmod(0o600)
        os.chown(config, account.pw_uid, account.pw_gid)
        unit = f'''[Unit]
Description=NEXUS independent VPS repair access (owner pairing required)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User={USER}
Group={USER}
WorkingDirectory={HOME_DIR}
ExecStart={node} {entry} remote --disable-no-sleep
Restart=on-failure
RestartSec=15
TimeoutStopSec=20
KillMode=control-group
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths={HOME_DIR}
UMask=0077
MemoryMax=512M
CPUQuota=50%
TasksMax=128
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

[Install]
WantedBy=multi-user.target
'''
        path = Path('/etc/systemd/system/nexus-rescue-control.service')
        path.write_text(unit)
        path.chmod(0o644)
        run('systemd-analyze', 'verify', str(path), timeout=20)
        run('systemctl', 'daemon-reload')
        run('systemctl', 'enable', '--now', 'nexus-rescue-control.service')
        receipt['status'] = 'INSTALLED_WAITING_OWNER_PAIRING'
        receipt['service_user'] = USER
        receipt['private_key_path_only'] = str(ssh_dir / 'operator_ed25519')
        receipt['independent_control_accepted'] = False
        print(json.dumps(receipt), flush=True)
    except Exception as exc:
        receipt['status'] = 'FAILED_REVIEW_REQUIRED'
        receipt['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        receipt_path.chmod(0o644)


if __name__ == '__main__':
    main()
