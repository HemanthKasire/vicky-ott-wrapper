#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
mountpoint -q /mnt/storage
install -m 750 -o root -g root library-refresh.py /usr/local/bin/portal-library-refresh.py
cat > /etc/systemd/system/portal-library-refresh.service <<'UNIT'
[Unit]
Description=Refresh Jellyfin after TV episode imports
Wants=network-online.target
After=network-online.target
RequiresMountsFor=/mnt/storage
BindsTo=mnt-storage.mount
[Service]
Type=oneshot
ExecStartPre=/usr/bin/mountpoint -q /mnt/storage
ExecStart=/usr/bin/python3 /usr/local/bin/portal-library-refresh.py
TimeoutStartSec=90
UMask=0077
Nice=10
CPUQuota=20%
MemoryMax=96M
ProtectSystem=full
ProtectHome=read-only
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/portal-library-refresh.timer <<'UNIT'
[Unit]
Description=Watch completed TV imports for Jellyfin library updates
[Timer]
OnBootSec=2min
OnUnitInactiveSec=60s
AccuracySec=5s
Unit=portal-library-refresh.service
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now portal-library-refresh.timer
systemctl start portal-library-refresh.service
