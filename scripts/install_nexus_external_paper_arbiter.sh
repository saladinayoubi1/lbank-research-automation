#!/usr/bin/env bash
# Independent Linux host only. Installs the API in non-authorizing standby.
set -euo pipefail
umask 077

source_root="${1:?absolute verified repository root required}"
source_sha="${2:?exact verified source SHA required}"
service_root='/opt/nexus-paper-arbiter'
state_root='/var/lib/nexus-paper-arbiter'
service_name='nexus-paper-arbiter.service'
service_user='nexus-paper-arbiter'

case "$(hostname -s | tr '[:lower:]' '[:upper:]')" in
  DESKTOP-1R1081M|DESKTOP-F4SA4VL) echo 'Signing service cannot run on a writer.' >&2; exit 73;;
esac
test "$(uname -s)" = 'Linux'
test "$(id -u)" = 0
case "$source_root" in /*) ;; *) exit 73;; esac
[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]]
test "$(git -C "$source_root" rev-parse HEAD)" = "$source_sha"
test -z "$(git -C "$source_root" status --porcelain --untracked-files=all)"
python3 -c 'import sys; assert sys.version_info >= (3,12)'
command -v openssl >/dev/null
command -v systemctl >/dev/null
command -v runuser >/dev/null
# Initial installer cannot overwrite or accidentally re-key an existing authority.
test ! -e "$service_root"
test ! -L "$service_root"
test ! -e "$state_root"
test ! -L "$state_root"
test ! -e "/etc/systemd/system/$service_name"
test ! -L "/etc/systemd/system/$service_name"
test -f "$source_root/nexus_external_paper_arbiter.py"
test -f "$source_root/nexus_paper_writer_fence.py"

if ! id "$service_user" >/dev/null 2>&1; then
  useradd --system --home-dir "$state_root" --no-create-home --shell /usr/sbin/nologin "$service_user"
fi
install -d -m 0755 "$service_root"
install -m 0644 "$source_root/nexus_external_paper_arbiter.py" "$service_root/"
install -m 0644 "$source_root/nexus_paper_writer_fence.py" "$service_root/"
printf '%s\n' "$source_sha" > "$service_root/source-sha.txt"
install -d -m 0700 -o "$service_user" -g "$service_user" "$state_root"
runuser -u "$service_user" -- env PYTHONDONTWRITEBYTECODE=1 \
  python3 "$service_root/nexus_external_paper_arbiter.py" init --state-root "$state_root"

cat > "/etc/systemd/system/$service_name" <<'UNIT'
[Unit]
Description=NEXUS external Paper arbiter (standby, takeover disabled)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nexus-paper-arbiter
Group=nexus-paper-arbiter
WorkingDirectory=/opt/nexus-paper-arbiter
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/bin/python3 /opt/nexus-paper-arbiter/nexus_external_paper_arbiter.py serve --state-root /var/lib/nexus-paper-arbiter --bind 127.0.0.1 --port 8089
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/nexus-paper-arbiter
RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now "$service_name"
python3 - <<'PY'
import json
import time
from urllib.request import urlopen
for attempt in range(20):
    try:
        with urlopen('http://127.0.0.1:8089/healthz', timeout=2) as response:
            body = json.load(response)
        break
    except OSError:
        if attempt == 19:
            raise
        time.sleep(0.5)
assert body['takeover_enabled'] is False
assert body['live_trading_authority'] is False
print('external_arbiter_deployed=true takeover_enabled=false live_trading_authority=false')
PY
