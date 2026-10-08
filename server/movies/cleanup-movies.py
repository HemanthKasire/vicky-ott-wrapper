#!/usr/bin/python3
"""Remove movie torrents after hardlink or sampled torrent-piece import verification."""
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path

STATE = Path('/var/lib/torrent-portal/movie-cleanup')
VIDEO = {'.mkv', '.mp4', '.avi', '.m4v', '.mov', '.webm', '.ts', '.m2ts'}
MAX_PIECE = 32 * 1024 * 1024


def safe_path(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('Unsafe torrent path')
    if root.resolve() != root or not root.is_dir():
        raise ValueError('Movie download folder is unavailable or redirected')
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Symlinks require manual review')
    return path


def library_index(root):
    if root.resolve() != root or not root.is_dir():
        raise ValueError('Movies folder is unavailable or redirected')
    index = {}
    def onerror(error):
        raise error
    for parent, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        dirs[:] = [d for d in dirs if not (Path(parent) / d).is_symlink()]
        for name in files:
            path = Path(parent) / name
            if path.suffix.lower() in VIDEO and not path.is_symlink():
                index.setdefault(path.stat().st_size, []).append(path)
    return index


def sampled_pieces(path, offset, size, total, piece_size, hashes):
    """Check first/middle/last wholly contained pieces; never hash the entire movie."""
    if not 0 < piece_size <= MAX_PIECE or size <= 0 or offset < 0 or offset + size > total:
        raise ValueError('Unsupported torrent piece metadata')
    if len(hashes) != (total + piece_size - 1) // piece_size:
        raise ValueError('Torrent piece hashes are unavailable')
    first = (offset + piece_size - 1) // piece_size
    last = (offset + size) // piece_size - 1
    if offset + size == total:
        last = (total - 1) // piece_size
    if first > last:
        raise ValueError('Movie has no independently verifiable torrent piece')
    pieces = sorted({first, (first + last) // 2, last})
    # A tiny file must be verified entirely; large files need three separated pieces.
    if size > piece_size * 3 and len(pieces) != 3:
        raise ValueError('Insufficient torrent pieces to verify movie')
    with path.open('rb') as stream:
        for number in pieces:
            length = min(piece_size, total - number * piece_size)
            local = number * piece_size - offset
            if local < 0 or local + length > size:
                raise ValueError('Torrent piece crosses movie boundary')
            stream.seek(local)
            data = stream.read(length)
            if len(data) != length or hashlib.sha1(data).hexdigest() != hashes[number].lower():
                return False
    return True


def proof(portal, config, torrent, files, index):
    if torrent.get('category') != '' or torrent.get('save_path') != '/downloads/complete' or float(torrent.get('progress', 0)) < 1:
        raise ValueError('Not a completed movie in the movie download folder')
    info_hash = torrent.get('hash', '')
    if not re.fullmatch(r'[0-9a-fA-F]{40}', info_hash):
        raise ValueError('Invalid torrent hash')
    root = Path(config['HOST_STORAGE_PATH']) / 'media/torrents/complete'
    ordered = sorted(files, key=lambda f: int(f['index']))
    if [int(f['index']) for f in ordered] != list(range(len(ordered))):
        raise ValueError('Torrent file order is incomplete')
    total = sum(int(f['size']) for f in ordered)
    if any(int(f['size']) < 0 for f in ordered):
        raise ValueError('Invalid torrent file size')
    verified = []
    offset = 0
    metadata = None
    for file in ordered:
        source = safe_path(root, file['name'])
        size = int(file['size'])
        if Path(file['name']).suffix.lower() in VIDEO and int(file.get('priority', 1)) != 0:
            if float(file.get('progress', 0)) < 1:
                raise ValueError('Movie video is incomplete')
            matches = index.get(size, [])
            target = None
            method = None
            for candidate in matches:
                if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size != size:
                    continue
                if source.exists() and os.path.samefile(source, candidate):
                    target, method = candidate, 'hardlink'
                    break
                if metadata is None:
                    properties = json.loads(portal.qb_request(config, '/api/v2/torrents/properties?hash=' + info_hash))
                    hashes = json.loads(portal.qb_request(config, '/api/v2/torrents/pieceHashes?hash=' + info_hash))
                    metadata = int(properties['piece_size']), hashes
                if sampled_pieces(candidate, offset, size, total, *metadata):
                    target, method = candidate, 'first-middle-last-torrent-pieces'
                    break
            if target is None:
                raise ValueError('Movie has not been verified in Movies')
            stat = target.stat()
            verified.append({'source':str(source), 'movie':str(target), 'size':size,
                             'device':stat.st_dev, 'inode':stat.st_ino, 'method':method})
        offset += size
    if not verified:
        raise ValueError('No selected movie videos')
    return verified


def cleanup(portal, config, preview=False):
    if not portal.is_exact_mount(config['HOST_STORAGE_PATH']):
        raise ValueError('Media volume is not mounted')
    movies = Path(config['HOST_MOVIES_PATH'])
    downloads = Path(config['HOST_STORAGE_PATH']) / 'media/torrents'
    if movies.is_relative_to(downloads) or downloads.is_relative_to(movies):
        raise ValueError('Movies and download folders must not overlap')
    index = library_index(movies)
    results = []
    for torrent in portal.get_torrents(config):
        if torrent.get('category') != '' or torrent.get('save_path') != '/downloads/complete' or float(torrent.get('progress',0)) < 1:
            continue
        info_hash = str(torrent.get('hash','')).lower()
        try:
            if not re.fullmatch(r'[0-9a-f]{40}',info_hash):
                raise ValueError('Invalid torrent hash')
            if not preview:
                portal.qb_request(config, '/api/v2/torrents/stop', method='POST', form={'hashes':info_hash})
            files = json.loads(portal.qb_request(config, '/api/v2/torrents/files?hash=' + info_hash))
            verified = proof(portal, config, torrent, files, index)
            if not preview:
                # Recheck target identity immediately before authorizing source deletion.
                for movie in verified:
                    path = Path(movie['movie'])
                    stat = path.stat()
                    if path.is_symlink() or (stat.st_dev,stat.st_ino,stat.st_size) != (movie['device'],movie['inode'],movie['size']):
                        raise ValueError('Imported movie changed during verification')
                STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
                manifest = STATE / (info_hash + '.json')
                manifest.write_text(json.dumps({'hash':info_hash,'movies':verified,'state':'verified'}))
                portal.qb_request(config, '/api/v2/torrents/delete', method='POST', form={'hashes':info_hash,'deleteFiles':'true'})
                for movie in verified:
                    if Path(movie['movie']).stat().st_size != movie['size']:
                        raise ValueError('Imported movie changed after cleanup')
                manifest.write_text(json.dumps({'hash':info_hash,'movies':verified,'state':'delete-requested'}))
            results.append({'hash':info_hash,'movies':len(verified),'action':'verified' if preview else 'delete-requested'})
        except (ValueError,OSError,KeyError,TypeError) as error:
            results.append({'hash':info_hash,'action':'kept','reason':str(error)})
    return results


def main():
    import sys
    spec = importlib.util.spec_from_file_location('portal','/usr/local/bin/torrent-portal.py')
    portal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(portal)
    print(json.dumps(cleanup(portal,portal.load_config(),'--preview' in sys.argv)))


if __name__ == '__main__':
    main()
