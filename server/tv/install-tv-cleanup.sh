#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
mountpoint -q /mnt/storage
python3 configure-no-seeding.py
install -m 750 -o root -g root cleanup-tv.py /usr/local/bin/portal-tv-cleanup.py
cat > /etc/systemd/system/portal-tv-cleanup.service <<'UNIT'
[Unit]
Description=Delete verified TV download originals after import
Wants=network-online.target
After=network-online.target
RequiresMountsFor=/mnt/storage
[Service]
Type=oneshot
ExecStartPre=/usr/bin/mountpoint -q /mnt/storage
ExecStart=/usr/bin/python3 /usr/local/bin/portal-tv-cleanup.py
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
cat > /etc/systemd/system/portal-tv-cleanup.timer <<'UNIT'
[Unit]
Description=Clean completed TV downloads after safe import
[Timer]
OnBootSec=2min
OnUnitInactiveSec=60s
AccuracySec=5s
Unit=portal-tv-cleanup.service
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now portal-tv-cleanup.timer
systemctl start portal-tv-cleanup.service
