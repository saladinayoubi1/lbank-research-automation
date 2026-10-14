"""Prepare one private repair identity; never print or export its private key."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import stat
import subprocess
import socket

if os.geteuid() != 0 or socket.gethostname() != "vm39793-59152.mobinhost.com":
    raise SystemExit("Expected the authenticated existing NEXUS VPS root session")
os.umask(0o077)
root = Path("/var/lib/nexus-vps-rescue")
if (root / "operator-identity-relocated.json").exists():
    raise SystemExit("Repair identity moved to nexuscontrol on this VPS; never generate a replacement")
if root.is_symlink():
    raise SystemExit("Unexpected rescue directory symlink")
if not root.exists():
    root.mkdir(mode=0o700)
if root.stat().st_uid != 0 or stat.S_IMODE(root.stat().st_mode) != 0o700:
    raise SystemExit("Unexpected rescue directory ownership or permissions")
key = root/"operator_ed25519"
pub = root/"operator_ed25519.pub"
created = False
if key.is_symlink() or pub.is_symlink() or key.exists() != pub.exists():
    raise SystemExit("Unexpected partial repair identity; do not overwrite")
if not key.exists():
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "NEXUS-VPS-RESCUE", "-f", str(key)],
                   stdin=subprocess.DEVNULL, check=True, timeout=10, capture_output=True)
    created = True
if key.stat().st_uid != 0 or stat.S_IMODE(key.stat().st_mode) != 0o600:
    raise SystemExit("Unexpected private-key ownership or permissions")
derived = subprocess.run(["ssh-keygen", "-y", "-P", "", "-f", str(key)],
                         check=True, capture_output=True, text=True, timeout=5).stdout.strip().split()[:2]
public = pub.read_text().strip()
if derived != public.split()[:2] or derived[0] != "ssh-ed25519":
    raise SystemExit("Repair identity mismatch")
fingerprint = subprocess.run(["ssh-keygen", "-l", "-f", str(pub)], check=True,
                             capture_output=True, text=True, timeout=5).stdout.strip()
versions = {}
for name in ("node", "npm"):
    executable = shutil.which(name)
    versions[name] = (subprocess.run([executable, "--version"], capture_output=True,
                                    text=True, timeout=5).stdout.strip() if executable else None)
print(json.dumps({"hostname": socket.gethostname(), "created_new_identity": created,
                  "private_key_path_only": str(key), "private_key_exported": False,
                  "public_key": public, "public_key_sha256": hashlib.sha256((public+"\n").encode()).hexdigest(),
                  "fingerprint": fingerprint, "versions": versions,
                  "ssh_config_changed": False, "firewall_changed": False,
                  "windows_route_active": False, "writer_authority": False, "live_enabled": False}))
