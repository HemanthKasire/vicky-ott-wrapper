#!/bin/bash
set -euo pipefail
mountpoint -q /mnt/storage
install -d -o 1001 -g 1001 -m 775 /mnt/storage/media/torrents/tv
install -d -o 1001 -g 1001 -m 750 /home/ubuntu/sonarr/config
python3 - <<'PY'
import pathlib,secrets
p=pathlib.Path('/home/ubuntu/sonarr/config/config.xml')
if not p.exists():
 p.write_text('<Config><BindAddress>*</BindAddress><Port>8989</Port><SslPort>9898</SslPort><EnableSsl>False</EnableSsl><LaunchBrowser>False</LaunchBrowser><ApiKey>'+secrets.token_hex(16)+'</ApiKey><AuthenticationMethod>Forms</AuthenticationMethod><AuthenticationRequired>DisabledForLocalAddresses</AuthenticationRequired><LogLevel>info</LogLevel><UpdateMechanism>Docker</UpdateMechanism></Config>')
 p.chmod(0o600)
 import os
 os.chown(p,1001,1001)
PY
cat > /etc/systemd/system/sonarr.service <<'UNIT'
[Unit]
Description=Sonarr TV organiser
Requires=docker.service
After=docker.service
RequiresMountsFor=/mnt/storage
BindsTo=mnt-storage.mount
[Service]
Type=simple
ExecStartPre=/usr/bin/mountpoint -q /mnt/storage
ExecStart=/usr/bin/docker run --rm --name sonarr --network container:qbittorrent --memory=320m --memory-swap=640m --cpus=0.5 --pids-limit=256 -e PUID=1001 -e PGID=1001 -e TZ=Asia/Kolkata -e UMASK=002 -v /home/ubuntu/sonarr/config:/config -v /mnt/storage/media:/data lscr.io/linuxserver/sonarr@sha256:f247545d23ba8b233d6604575347e48a623fe6ad75dda02348bf81917f3b5c06
ExecStop=/usr/bin/docker stop -t 30 sonarr
Restart=on-failure
RestartSec=15
TimeoutStopSec=45
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now sonarr.service
