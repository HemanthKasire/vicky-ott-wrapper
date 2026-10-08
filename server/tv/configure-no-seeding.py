#!/usr/bin/python3
"""Set Stop at zero seeding limits and stop already completed torrents."""
import importlib.util
import json
from pathlib import Path
import time
spec = importlib.util.spec_from_file_location('portal', '/usr/local/bin/torrent-portal.py')
portal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portal)
config = portal.load_config()
prefs = json.loads(portal.qb_request(config, '/api/v2/app/preferences'))
changes = {'max_ratio_enabled': True, 'max_ratio': 0, 'max_seeding_time_enabled': True,
           'max_seeding_time': 0, 'max_inactive_seeding_time_enabled': True,
           'max_inactive_seeding_time': 0, 'max_ratio_act': 0}
backup = Path('/var/lib/torrent-portal') / ('seeding-preferences-' + str(time.time_ns()) + '.json')
backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
backup.write_text(json.dumps({key: prefs.get(key) for key in changes}))
backup.chmod(0o600)
portal.qb_request(config, '/api/v2/app/setPreferences', method='POST', form={'json': json.dumps(changes)})
updated = json.loads(portal.qb_request(config, '/api/v2/app/preferences'))
if any(updated.get(key) != value for key, value in changes.items()):
    raise RuntimeError('Seeding settings did not persist')
torrents = portal.get_torrents(config)
hashes = '|'.join(t['hash'] for t in torrents)
if hashes:
    portal.qb_request(config, '/api/v2/torrents/setShareLimits', method='POST', form={
        'hashes': hashes, 'ratioLimit': '0', 'seedingTimeLimit': '0', 'inactiveSeedingTimeLimit': '0', 'shareLimitAction': 'Stop'})
completed = '|'.join(t['hash'] for t in torrents if float(t.get('progress', 0)) >= 1)
if completed:
    portal.qb_request(config, '/api/v2/torrents/stop', method='POST', form={'hashes': completed})
print(json.dumps({'zeroSeedingLimits': True, 'completedStopped': len(completed.split('|')) if completed else 0}))
