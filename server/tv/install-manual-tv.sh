#!/bin/bash
set -euo pipefail
mountpoint -q /mnt/storage
install -d -o 1001 -g 1001 -m 775 /mnt/storage/media/torrents/tv-manual
install -d -o root -g root -m 700 /var/lib/torrent-portal/manual-tv
python3 - <<'PYCODE'
import importlib.util,json
spec=importlib.util.spec_from_file_location('portal','/usr/local/bin/torrent-portal.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p);config=p.load_config()
categories=json.loads(p.qb_request(config,'/api/v2/torrents/categories'))
endpoint='editCategory' if 'portal-tv-manual' in categories else 'createCategory'
p.qb_request(config,'/api/v2/torrents/'+endpoint,method='POST',form={'category':'portal-tv-manual','savePath':'/downloads/tv-manual'})
PYCODE
cat > /etc/systemd/system/portal-manual-tv.service <<'UNIT'
[Unit]
Description=Sort manually labelled TV torrent episodes
Requires=docker.service
After=docker.service
RequiresMountsFor=/mnt/storage
BindsTo=mnt-storage.mount
[Service]
Type=oneshot
ExecStartPre=/usr/bin/mountpoint -q /mnt/storage
ExecStart=/usr/local/bin/torrent-portal.py import-manual-tv
TimeoutStartSec=3min
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
UNIT
cat > /etc/systemd/system/portal-manual-tv.timer <<'UNIT'
[Unit]
Description=Check completed manual TV downloads every minute
[Timer]
OnBootSec=90s
OnUnitActiveSec=60s
AccuracySec=10s
RandomizedDelaySec=5s
Unit=portal-manual-tv.service
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now portal-manual-tv.timer
