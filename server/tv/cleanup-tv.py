#!/usr/bin/python3
"""Remove completed TV torrents only after proving every episode exists in Shows."""
import importlib.util
import json
import os
import re
from pathlib import Path

STATE = Path('/var/lib/torrent-portal/tv-cleanup')
VIDEO = {'.mkv', '.mp4', '.avi', '.m4v', '.mov', '.webm', '.ts', '.m2ts'}
CATEGORIES = {'portal-tv': 'tv', 'portal-tv-manual': 'tv-manual'}


def safe_path(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('Unsafe download filename')
    path = root
    if root.is_symlink() or root.resolve() != root:
        raise ValueError('Download folder is a symlink')
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Download contains a symlink')
    return path


def show_index(root):
    if not root.is_dir() or root.is_symlink() or root.resolve() != root:
        raise ValueError('Shows folder is unavailable or redirected')
    index = {}
    def onerror(error):
        raise error
    for parent, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        dirs[:] = [d for d in dirs if not (Path(parent) / d).is_symlink()]
        for name in files:
            path = Path(parent) / name
            if path.suffix.lower() in VIDEO and not path.is_symlink():
                stat = path.stat()
                index.setdefault((stat.st_dev, stat.st_ino), []).append(path)
    return index


def proof(torrent, files, storage, index):
    category = torrent.get('category')
    if category not in CATEGORIES or float(torrent.get('progress', 0)) < 1:
        raise ValueError('Not a completed portal TV torrent')
    if not re.fullmatch(r'[0-9a-fA-F]{40}', torrent.get('hash', '')):
        raise ValueError('Invalid torrent hash')
    if torrent.get('save_path') != '/downloads/' + CATEGORIES[category]:
        raise ValueError('Download location changed')
    root = storage / 'media/torrents' / CATEGORIES[category]
    videos = [f for f in files if Path(f['name']).suffix.lower() in VIDEO and int(f.get('priority', 1)) != 0]
    if not videos:
        raise ValueError('No selected episode videos')
    verified = []
    for file in videos:
        if float(file.get('progress', 0)) < 1:
            raise ValueError('Episode is incomplete')
        source = safe_path(root, file['name'])
        stat = source.stat()
        if not source.is_file() or stat.st_size != int(file['size']):
            raise ValueError('Episode size does not match download')
        matches = index.get((stat.st_dev, stat.st_ino), [])
        if not matches or stat.st_nlink < 2:
            raise ValueError('Episode has not been verified in Shows')
        target = matches[0]
        if not target.is_file() or target.is_symlink() or not os.path.samefile(source, target):
            raise ValueError('Imported episode changed')
        verified.append({'source': str(source), 'show': str(target), 'size': stat.st_size})
    # qBittorrent deletes the entire torrent: reject unsafe paths even among extras.
    for file in files:
        safe_path(root, file['name'])
    return verified


def cleanup(portal, config, preview=False):
    storage = Path(config['HOST_STORAGE_PATH'])
    if not portal.is_exact_mount(str(storage)):
        raise ValueError('Media volume is not mounted')
    index = show_index(Path(config.get('HOST_SHOWS_PATH', str(storage / 'media/shows'))))
    results = []
    for torrent in portal.get_torrents(config):
        if torrent.get('category') not in CATEGORIES or float(torrent.get('progress', 0)) < 1:
            continue
        info_hash = str(torrent.get('hash', '')).lower()
        try:
            if not re.fullmatch(r'[0-9a-f]{40}', info_hash):
                raise ValueError('Invalid torrent hash')
            if not preview:
                portal.qb_request(config, '/api/v2/torrents/stop', method='POST', form={'hashes': info_hash})
            if torrent['category'] == 'portal-tv-manual':
                record = json.loads(portal.manual_tv_path(info_hash).read_text())
                if record.get('state') != 'imported':
                    raise ValueError('Manual import is not complete')
            files = json.loads(portal.qb_request(config, '/api/v2/torrents/files?hash=' + info_hash))
            verified = proof(torrent, files, storage, index)
            if not preview:
                STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
                manifest = STATE / (info_hash + '.json')
                manifest.write_text(json.dumps({'hash': info_hash, 'episodes': verified, 'state': 'verified'}))
                portal.qb_request(config, '/api/v2/torrents/delete', method='POST', form={'hashes': info_hash, 'deleteFiles': 'true'})
                for episode in verified:
                    if Path(episode['show']).stat().st_size != episode['size']:
                        raise ValueError('Shows verification failed after cleanup')
                manifest.write_text(json.dumps({'hash': info_hash, 'episodes': verified, 'state': 'delete-requested'}))
            results.append({'hash': info_hash, 'episodes': len(verified), 'action': 'verified' if preview else 'delete-requested'})
        except (ValueError, OSError, KeyError, TypeError) as error:
            results.append({'hash': info_hash, 'action': 'kept', 'reason': str(error)})
    return results


def main():
    import sys
    spec = importlib.util.spec_from_file_location('portal', '/usr/local/bin/torrent-portal.py')
    portal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(portal)
    print(json.dumps(cleanup(portal, portal.load_config(), '--preview' in sys.argv)))


if __name__ == '__main__':
    main()
