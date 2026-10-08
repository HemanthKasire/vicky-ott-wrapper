#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
mountpoint -q /mnt/storage
install -m 750 -o root -g root cleanup-movies.py /usr/local/bin/portal-movie-cleanup.py
cat > /etc/systemd/system/portal-movie-cleanup.service <<'UNIT'
[Unit]
Description=Delete verified movie download originals after import
Wants=network-online.target
After=network-online.target
RequiresMountsFor=/mnt/storage
[Service]
Type=oneshot
ExecStartPre=/usr/bin/mountpoint -q /mnt/storage
ExecStart=/usr/bin/python3 /usr/local/bin/portal-movie-cleanup.py
TimeoutStartSec=180
UMask=0077
Nice=10
CPUQuota=20%
MemoryMax=128M
ProtectSystem=full
ProtectHome=read-only
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/portal-movie-cleanup.timer <<'UNIT'
[Unit]
Description=Clean completed movie downloads after safe import
[Timer]
OnBootSec=2min
OnUnitInactiveSec=60s
AccuracySec=5s
Unit=portal-movie-cleanup.service
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now portal-movie-cleanup.timer
systemctl start portal-movie-cleanup.service
