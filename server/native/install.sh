#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
mountpoint -q /mnt/storage
getent passwd oci-automation >/dev/null || useradd --system --home /var/lib/oci-automation --shell /usr/sbin/nologin oci-automation
install -d -o root -g root -m 755 /usr/local/lib/oci-automation
install -m 755 automation.py privileged.py /usr/local/lib/oci-automation/
install -m 700 cutover.py /usr/local/lib/oci-automation/cutover.py
install -m 700 network.py /usr/local/lib/oci-automation/network.py
install -m 755 ott-run.py /usr/local/bin/ott-run
if [[ ! -f /etc/oci-automation/config.json ]]; then
    python3 extract-config.py
fi
chown root:oci-automation /etc/oci-automation /etc/oci-automation/config.json /etc/oci-automation/initial-state.json
chmod 750 /etc/oci-automation
chmod 640 /etc/oci-automation/config.json /etc/oci-automation/initial-state.json
chmod 600 /etc/oci-automation/jellyfin.key /etc/oci-automation/ssh.json
install -d -o oci-automation -g oci-automation -m 700 /var/lib/oci-automation
cat > /etc/sudoers.d/oci-automation <<'SUDO'
oci-automation ALL=(root) NOPASSWD: /usr/local/lib/oci-automation/privileged.py ""
SUDO
chmod 440 /etc/sudoers.d/oci-automation
visudo -cf /etc/sudoers.d/oci-automation
cat > /etc/systemd/system/oci-automation.service <<'UNIT'
[Unit]
Description=OCI native torrent API, Telegram commands and notification worker
Requires=docker.service oci-automation-network.service
After=docker.service oci-automation-network.service network-online.target
Wants=network-online.target
[Service]
User=oci-automation
Group=oci-automation
UMask=0077
ExecStart=/usr/bin/python3 /usr/local/lib/oci-automation/automation.py serve
Restart=on-failure
RestartSec=5
TimeoutStopSec=90
MemoryMax=192M
MemorySwapMax=96M
CPUQuota=50%
TasksMax=64
Nice=5
ProtectSystem=full
ProtectHome=read-only
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/oci-automation-network.service <<'UNIT'
[Unit]
Description=Permit native API access only from the private Docker bridge
Requires=docker.service
After=docker.service
Before=oci-automation.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 /usr/local/lib/oci-automation/network.py up
ExecStop=/usr/bin/python3 /usr/local/lib/oci-automation/network.py down
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/oci-automation-health.service <<'UNIT'
[Unit]
Description=Check OCI and Jellyfin health and queue changed alerts
After=oci-automation.service
[Service]
Type=oneshot
User=oci-automation
Group=oci-automation
UMask=0077
ExecStart=/usr/bin/python3 /usr/local/lib/oci-automation/automation.py health
TimeoutStartSec=150
MemoryMax=128M
CPUQuota=25%
Nice=10
UNIT
cat > /etc/systemd/system/oci-automation-health.timer <<'UNIT'
[Unit]
Description=Run native server health checks every minute
[Timer]
OnBootSec=2min
OnUnitInactiveSec=60s
AccuracySec=5s
Unit=oci-automation-health.service
[Install]
WantedBy=timers.target
UNIT
runuser -u oci-automation -- python3 - <<'PY'
import json,sys
sys.path.insert(0,'/usr/local/lib/oci-automation')
from automation import Store
s=Store('/var/lib/oci-automation/state.sqlite')
for k,v in json.load(open('/etc/oci-automation/initial-state.json')).items():
    if s.get(k) is None:s.set(k,v)
PY
systemctl daemon-reload
systemctl enable --now oci-automation.service
systemctl restart oci-automation.service
echo 'Native service installed; routing and health timer await verified cutover.'
