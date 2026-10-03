#!/usr/bin/env python3

import base64
import difflib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


CONFIG_FILE = "/etc/torrent-portal/qbittorrent.conf"
JELLYFIN_CONFIG_FILE = "/etc/torrent-portal/jellyfin.conf"
INSPECTION_DIR = Path("/var/lib/torrent-portal/inspections")
INSPECTION_TTL_SECONDS = 15 * 60
MAX_MAGNET_LENGTH = 8192
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".webm"}
NOISE_PATTERN = re.compile(
    r"\b(?:2160p|1080p|720p|480p|uhd|hdr10?|dv|dolby[ ._-]*vision|"
    r"bluray|blu[ ._-]*ray|web[ ._-]*(?:dl|rip)|webrip|hdtv|dvdrip|"
    r"x26[45]|h26[45]|hevc|av1|remux|proper|repack|extended|unrated|"
    r"aac|ac3|eac3|dts|truehd|atmos)\b",
    re.IGNORECASE,
)


def emit(payload, exit_code=0):
    print(json.dumps(payload, separators=(",", ":")))
    raise SystemExit(exit_code)


def fail(message, status=500):
    emit({"connected": False, "error": message, "status": status}, 1)


def load_config():
    config = {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as config_file:
            for raw_line in config_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()
    except OSError as error:
        fail(f"Cannot read configuration: {error}")

    required = [
        "QB_CONTAINER",
        "QB_CONTAINER_URL",
        "QB_SAVE_PATH",
        "HOST_STORAGE_PATH",
        "HOST_MOVIES_PATH",
    ]
    missing = [key for key in required if not config.get(key)]
    if missing:
        fail("Missing configuration values: " + ", ".join(missing))
    return config


def load_jellyfin_config():
    config = {}
    try:
        with open(JELLYFIN_CONFIG_FILE, "r", encoding="utf-8") as config_file:
            for raw_line in config_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()
    except OSError as error:
        fail(f"Cannot read Jellyfin configuration: {error}", 503)

    url = config.get("JELLYFIN_URL", "").rstrip("/")
    encoded_key = config.get("JELLYFIN_API_KEY_B64", "")
    if not url or not encoded_key:
        fail("Jellyfin catalog is not configured", 503)
    try:
        padding = "=" * (-len(encoded_key) % 4)
        api_key = base64.urlsafe_b64decode(encoded_key + padding).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        fail("Jellyfin API key configuration is invalid", 503)
    if not api_key:
        fail("Jellyfin API key configuration is empty", 503)
    return url, api_key


def library_action(_config):
    jellyfin_url, api_key = load_jellyfin_config()
    query = urllib.parse.urlencode({
        "Recursive": "true",
        "IncludeItemTypes": "Movie,Series",
        "Fields": "ProductionYear,Genres,CommunityRating,DateCreated",
        "SortBy": "SortName",
        "SortOrder": "Ascending",
        "Limit": "5000",
    })
    request = urllib.request.Request(
        f"{jellyfin_url}/Items?{query}",
        headers={
            "Accept": "application/json",
            "Authorization": f"MediaBrowser Token={api_key}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        fail(f"Jellyfin catalog returned HTTP {error.code}", 502)
    except urllib.error.URLError as error:
        fail(f"Cannot connect to Jellyfin: {error.reason}", 502)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail("Jellyfin returned invalid catalog data", 502)

    source_items = payload.get("Items", []) if isinstance(payload, dict) else []
    items = []
    for item in source_items:
        item_type = str(item.get("Type", ""))
        if item_type not in {"Movie", "Series"}:
            continue
        name = str(item.get("Name", "")).strip()
        if not name:
            continue
        rating = item.get("CommunityRating")
        items.append({
            "id": str(item.get("Id", "")),
            "title": name,
            "type": "movie" if item_type == "Movie" else "show",
            "year": item.get("ProductionYear"),
            "rating": round(float(rating), 1) if isinstance(rating, (int, float)) else None,
            "genres": [str(genre) for genre in item.get("Genres", [])[:3]],
            "imageTag": str(item.get("ImageTags", {}).get("Primary", "")),
        })

    emit({
        "connected": True,
        "items": items,
        "counts": {
            "all": len(items),
            "movies": sum(1 for item in items if item["type"] == "movie"),
            "shows": sum(1 for item in items if item["type"] == "show"),
        },
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    })


def poster_action(_config, payload):
    item_id = str(payload.get("itemId", ""))
    if not re.fullmatch(r"[A-Fa-f0-9]{16,64}", item_id):
        fail("Invalid Jellyfin item ID", 400)

    jellyfin_url, api_key = load_jellyfin_config()
    query = urllib.parse.urlencode({"maxWidth": "360", "quality": "80"})
    request = urllib.request.Request(
        f"{jellyfin_url}/Items/{item_id}/Images/Primary?{query}",
        headers={
            "Accept": "image/avif,image/webp,image/jpeg,image/png",
            "Authorization": f"MediaBrowser Token={api_key}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            image_data = response.read(2 * 1024 * 1024 + 1)
            mime_type = response.headers.get_content_type()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            emit({"found": False})
        fail(f"Jellyfin poster returned HTTP {error.code}", 502)
    except urllib.error.URLError as error:
        fail(f"Cannot connect to Jellyfin poster service: {error.reason}", 502)

    if len(image_data) > 2 * 1024 * 1024:
        fail("Jellyfin poster is too large", 502)
    if mime_type not in {"image/avif", "image/webp", "image/jpeg", "image/png"}:
        fail("Jellyfin returned an unsupported poster format", 502)
    emit({
        "found": True,
        "mimeType": mime_type,
        "dataBase64": base64.b64encode(image_data).decode("ascii"),
    })


def qb_request(config, endpoint, method="GET", form=None, timeout=25):
    base_url = config["QB_CONTAINER_URL"].rstrip("/")
    command = [
        "docker", "exec", "-i", config["QB_CONTAINER"],
        "curl", "-sS", "--fail-with-body",
        "--connect-timeout", "5", "--max-time", str(timeout),
        "-H", f"Referer: {base_url}/",
        "-H", f"Origin: {base_url}",
    ]
    input_data = None
    if method == "POST":
        command.extend(["-X", "POST"])
        if form is not None:
            command.extend([
                "-H", "Content-Type: application/x-www-form-urlencoded",
                "--data-binary", "@-",
            ])
            input_data = urllib.parse.urlencode(form)
    command.append(base_url + endpoint)
    result = subprocess.run(
        command,
        input=input_data,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "request failed"
        fail(f"qBittorrent API request failed: {detail}", 502)
    return result.stdout


def get_torrents(config):
    raw = qb_request(config, "/api/v2/torrents/info")
    try:
        torrents = json.loads(raw)
    except json.JSONDecodeError:
        fail("qBittorrent returned invalid torrent data", 502)
    if not isinstance(torrents, list):
        fail("qBittorrent torrent response was not a list", 502)
    return torrents


def find_torrent(config, info_hash):
    wanted = info_hash.lower()
    return next(
        (item for item in get_torrents(config) if str(item.get("hash", "")).lower() == wanted),
        None,
    )


def is_exact_mount(path):
    result = subprocess.run(
        ["findmnt", "-n", "-o", "TARGET", "--target", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return False
    return os.path.realpath(result.stdout.strip()) == os.path.realpath(path)


def storage_status(config):
    storage_path = config["HOST_STORAGE_PATH"]
    mounted = is_exact_mount(storage_path)
    try:
        disk = shutil.disk_usage(storage_path)
    except OSError as error:
        fail(f"Cannot read storage statistics: {error}")
    return {
        "id": "media-block",
        "label": "OCI media block volume",
        "totalBytes": disk.total,
        "usedBytes": disk.used,
        "availableBytes": disk.free,
        "mounted": mounted,
        "healthy": mounted and disk.free > 5 * 1024**3,
    }


def count_queue_states(torrents):
    downloading = {"downloading", "metadl", "forceddl", "stalleddl", "queueddl", "checkingdl", "allocating"}
    seeding = {"uploading", "forcedup", "stalledup", "queuedup", "checkingup"}
    stopped = {"stoppeddl", "stoppedup", "pauseddl", "pausedup"}
    errors = {"error", "missingfiles"}
    result = {"downloading": 0, "seeding": 0, "paused": 0, "errors": 0}
    for torrent in torrents:
        state = str(torrent.get("state", "")).lower()
        if state in downloading:
            result["downloading"] += 1
        elif state in seeding:
            result["seeding"] += 1
        elif state in stopped:
            result["paused"] += 1
        elif state in errors:
            result["errors"] += 1
    return result


def parse_payload(encoded):
    if len(encoded) > 20_000 or not re.fullmatch(r"[A-Za-z0-9_-]+", encoded):
        fail("Invalid request payload", 400)
    try:
        padding = "=" * (-len(encoded) % 4)
        raw = base64.urlsafe_b64decode(encoded + padding)
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        fail("Invalid request payload", 400)
    if not isinstance(payload, dict):
        fail("Invalid request payload", 400)
    return payload


def validate_magnet(value):
    if not isinstance(value, str) or not 20 <= len(value) <= MAX_MAGNET_LENGTH:
        fail("Invalid magnet link", 400)
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme.lower() != "magnet":
        fail("Only magnet links are accepted", 400)
    topics = urllib.parse.parse_qs(parsed.query).get("xt", [])
    btih = None
    for topic in topics:
        match = re.fullmatch(r"urn:btih:([A-Za-z0-9]+)", topic, re.IGNORECASE)
        if match:
            btih = match.group(1)
            break
    if not btih:
        fail("Magnet link has no BitTorrent info hash", 400)
    if re.fullmatch(r"[A-Fa-f0-9]{40}", btih):
        return btih.lower()
    if re.fullmatch(r"[A-Za-z2-7]{32}", btih):
        try:
            return base64.b32decode(btih.upper()).hex()
        except ValueError:
            pass
    fail("Magnet link contains an invalid BitTorrent info hash", 400)


def movie_identity(name):
    text = Path(name).stem
    text = re.sub(r"\[[^]]*]", " ", text)
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(
        r"^\s*(?:www\s+)?(?:\d*movierulz(?:\s+company)?|"
        r"tamilblasters|tamilmv|moviezwap)(?:\s+(?:com|org|net))?\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    year_match = re.search(r"\b((?:19|20)\d{2})\b", text)
    year = int(year_match.group(1)) if year_match else None
    if year_match:
        title_text = text[:year_match.start()]
    else:
        noise_match = NOISE_PATTERN.search(text)
        title_text = text[:noise_match.start()] if noise_match else text
    title_text = re.sub(r"[-]+", " ", title_text)
    title_text = re.sub(r"[^A-Za-z0-9]+", " ", title_text)
    title_text = " ".join(title_text.split()).strip()
    normalized = re.sub(r"[^a-z0-9]", "", title_text.lower())
    return title_text or Path(name).stem, normalized, year


def find_existing_media(config, torrent_name):
    requested_title, requested_normalized, requested_year = movie_identity(torrent_name)
    if not requested_normalized:
        return requested_title, requested_year, None
    best = None
    best_score = 0.0
    movie_root = Path(config["HOST_MOVIES_PATH"])
    if not movie_root.is_dir():
        return requested_title, requested_year, None
    for root, directories, files in os.walk(movie_root, followlinks=False):
        directories[:] = [directory for directory in directories if not directory.startswith(".")]
        for filename in files:
            path = Path(root) / filename
            if path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            candidate_title, candidate_normalized, candidate_year = movie_identity(filename)
            if not candidate_normalized:
                continue
            score = difflib.SequenceMatcher(None, requested_normalized, candidate_normalized).ratio()
            years_compatible = not requested_year or not candidate_year or requested_year == candidate_year
            if not years_compatible:
                score *= 0.55
            exact = requested_normalized == candidate_normalized and years_compatible
            if exact:
                score = 1.0
            if score >= 0.86 and score > best_score:
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                best_score = score
                best = {
                    "title": candidate_title,
                    "year": candidate_year,
                    "sizeBytes": size,
                    "match": "exact" if exact else "likely",
                }
    return requested_title, requested_year, best


def find_jellyfin_item(title, year):
    jellyfin_url, api_key = load_jellyfin_config()
    query = urllib.parse.urlencode({
        "Recursive": "true",
        "IncludeItemTypes": "Movie,Series",
        "Fields": "ProductionYear,ImageTags",
        "SortBy": "SortName",
        "SortOrder": "Ascending",
        "Limit": "5000",
    })
    request = urllib.request.Request(
        f"{jellyfin_url}/Items?{query}",
        headers={
            "Accept": "application/json",
            "Authorization": f"MediaBrowser Token={api_key}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    wanted_normalized = movie_identity(title)[1]
    best = None
    best_score = 0.0
    for item in payload.get("Items", []) if isinstance(payload, dict) else []:
        candidate_title = str(item.get("Name", "")).strip()
        candidate_normalized = movie_identity(candidate_title)[1]
        candidate_year = item.get("ProductionYear")
        if not candidate_normalized:
            continue
        score = difflib.SequenceMatcher(None, wanted_normalized, candidate_normalized).ratio()
        years_compatible = not year or not candidate_year or int(year) == int(candidate_year)
        if not years_compatible:
            score *= 0.55
        if wanted_normalized == candidate_normalized and years_compatible:
            score = 1.0
        if score >= 0.86 and score > best_score:
            best_score = score
            best = {
                "id": str(item.get("Id", "")),
                "title": candidate_title,
                "year": candidate_year,
                "imageTag": str(item.get("ImageTags", {}).get("Primary", "")),
            }
    return best


def optional_jellyfin_poster(item_id):
    if not re.fullmatch(r"[A-Fa-f0-9]{16,64}", item_id or ""):
        return None
    jellyfin_url, api_key = load_jellyfin_config()
    query = urllib.parse.urlencode({"maxWidth": "360", "quality": "80"})
    request = urllib.request.Request(
        f"{jellyfin_url}/Items/{item_id}/Images/Primary?{query}",
        headers={
            "Accept": "image/avif,image/webp,image/jpeg,image/png",
            "Authorization": f"MediaBrowser Token={api_key}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            image_data = response.read(2 * 1024 * 1024 + 1)
            mime_type = response.headers.get_content_type()
    except (urllib.error.HTTPError, urllib.error.URLError):
        return None
    if len(image_data) > 2 * 1024 * 1024:
        return None
    if mime_type not in {"image/avif", "image/webp", "image/jpeg", "image/png"}:
        return None
    return {
        "mimeType": mime_type,
        "dataBase64": base64.b64encode(image_data).decode("ascii"),
    }


def human_bytes(value):
    size = float(max(0, int(value or 0)))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024


def duplicate_check_action(config):
    alerts = []
    checked = 0
    pending_metadata = 0
    for torrent in get_torrents(config):
        tags = {tag.strip() for tag in str(torrent.get("tags", "")).split(",") if tag.strip()}
        if "portal-request" not in tags:
            continue
        if "portal-duplicate-checked" in tags or "portal-duplicate-alerted" in tags:
            continue

        info_hash = str(torrent.get("hash", "")).lower()
        if not re.fullmatch(r"[a-f0-9]{40}", info_hash):
            continue
        torrent_size = int(torrent.get("total_size") or torrent.get("size") or 0)
        if torrent_size <= 0:
            pending_metadata += 1
            continue

        torrent_name = str(torrent.get("name") or "Untitled torrent")
        title, year, existing = find_existing_media(config, torrent_name)
        checked += 1
        if not existing:
            qb_request(config, "/api/v2/torrents/addTags", method="POST", form={
                "hashes": info_hash,
                "tags": "portal-duplicate-checked",
            })
            continue

        jellyfin_item = find_jellyfin_item(existing["title"], existing.get("year"))
        poster = optional_jellyfin_poster((jellyfin_item or {}).get("id", ""))
        difference = torrent_size - int(existing["sizeBytes"])
        difference_percent = (
            abs(difference) / int(existing["sizeBytes"]) * 100
            if int(existing["sizeBytes"]) else None
        )
        alert = {
            "infoHash": info_hash.upper(),
            "torrentTitle": title,
            "torrentYear": year,
            "torrentSizeBytes": torrent_size,
            "torrentSize": human_bytes(torrent_size),
            "existingTitle": existing["title"],
            "existingYear": existing.get("year"),
            "existingSizeBytes": existing["sizeBytes"],
            "existingSize": human_bytes(existing["sizeBytes"]),
            "sizeDifferenceBytes": difference,
            "sizeDifferencePercent": round(difference_percent, 1) if difference_percent is not None else None,
            "match": existing["match"],
            "jellyfinItemId": (jellyfin_item or {}).get("id"),
            "posterMimeType": (poster or {}).get("mimeType"),
            "posterBase64": (poster or {}).get("dataBase64"),
        }
        alerts.append(alert)

    emit({
        "connected": True,
        "hasAlerts": bool(alerts),
        "alerts": alerts,
        "checked": checked,
        "pendingMetadata": pending_metadata,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    })


def duplicate_check_one_action(config, payload):
    info_hash = str(payload.get("infoHash", "")).lower()
    if not re.fullmatch(r"[a-f0-9]{40}", info_hash):
        fail("Invalid duplicate-check info hash", 400)

    torrent = find_torrent(config, info_hash)
    if not torrent:
        emit({
            "ready": False,
            "duplicate": False,
            "state": "waiting-for-torrent",
            "infoHash": info_hash.upper(),
        })

    tags = {tag.strip() for tag in str(torrent.get("tags", "")).split(",") if tag.strip()}
    if "portal-duplicate-alerted" in tags:
        emit({
            "ready": True,
            "duplicate": False,
            "state": "already-alerted",
            "infoHash": info_hash.upper(),
        })
    if "portal-duplicate-checked" in tags:
        emit({
            "ready": True,
            "duplicate": False,
            "state": "already-checked",
            "infoHash": info_hash.upper(),
        })

    torrent_size = int(torrent.get("total_size") or torrent.get("size") or 0)
    torrent_name = str(torrent.get("name") or "").strip()
    if torrent_size <= 0 or not torrent_name:
        emit({
            "ready": False,
            "duplicate": False,
            "state": "waiting-for-metadata",
            "infoHash": info_hash.upper(),
        })

    title, year, existing = find_existing_media(config, torrent_name)
    if not existing:
        qb_request(config, "/api/v2/torrents/addTags", method="POST", form={
            "hashes": info_hash,
            "tags": "portal-duplicate-checked",
        })
        emit({
            "ready": True,
            "duplicate": False,
            "state": "not-in-library",
            "infoHash": info_hash.upper(),
            "torrentTitle": title,
            "torrentYear": year,
            "torrentSizeBytes": torrent_size,
            "torrentSize": human_bytes(torrent_size),
        })

    jellyfin_item = find_jellyfin_item(existing["title"], existing.get("year"))
    poster = optional_jellyfin_poster((jellyfin_item or {}).get("id", ""))
    difference = torrent_size - int(existing["sizeBytes"])
    difference_percent = (
        abs(difference) / int(existing["sizeBytes"]) * 100
        if int(existing["sizeBytes"]) else None
    )
    emit({
        "ready": True,
        "duplicate": True,
        "state": "duplicate-found",
        "infoHash": info_hash.upper(),
        "torrentTitle": title,
        "torrentYear": year,
        "torrentSizeBytes": torrent_size,
        "torrentSize": human_bytes(torrent_size),
        "existingTitle": existing["title"],
        "existingYear": existing.get("year"),
        "existingSizeBytes": existing["sizeBytes"],
        "existingSize": human_bytes(existing["sizeBytes"]),
        "sizeDifferenceBytes": difference,
        "sizeDifferencePercent": round(difference_percent, 1) if difference_percent is not None else None,
        "match": existing["match"],
        "jellyfinItemId": (jellyfin_item or {}).get("id"),
        "posterMimeType": (poster or {}).get("mimeType"),
        "posterBase64": (poster or {}).get("dataBase64"),
    })


def duplicate_ack_action(config, payload):
    info_hash = str(payload.get("infoHash", "")).lower()
    if not re.fullmatch(r"[a-f0-9]{40}", info_hash):
        fail("Invalid duplicate-alert info hash", 400)
    torrent = find_torrent(config, info_hash)
    if not torrent:
        fail("Torrent was not found", 404)
    qb_request(config, "/api/v2/torrents/addTags", method="POST", form={
        "hashes": info_hash,
        "tags": "portal-duplicate-alerted",
    })
    emit({"acknowledged": True, "infoHash": info_hash.upper()})


def cleanup_old_torrents_action(config, dry_run):
    now = int(time.time())
    cutoff = now - 30 * 24 * 60 * 60
    removable_states = {
        "stoppedup",
        "pausedup",
        "stalledup",
        "queuedup",
        "error",
        "missingfiles",
        "unknown",
    }
    candidates = []
    for torrent in get_torrents(config):
        state = str(torrent.get("state", "")).lower()
        progress = float(torrent.get("progress") or 0)
        completed_on = int(torrent.get("completion_on") or 0)
        info_hash = str(torrent.get("hash", "")).lower()
        if progress < 0.999999 or completed_on <= 0 or completed_on > cutoff:
            continue
        if state not in removable_states:
            continue
        if not re.fullmatch(r"[a-f0-9]{40}", info_hash):
            continue
        candidates.append({
            "infoHash": info_hash.upper(),
            "name": str(torrent.get("name") or "Untitled torrent"),
            "state": state,
            "completedAt": datetime.fromtimestamp(completed_on, timezone.utc).isoformat(),
            "ageDays": (now - completed_on) // (24 * 60 * 60),
        })

    if candidates and not dry_run:
        qb_request(config, "/api/v2/torrents/delete", method="POST", form={
            "hashes": "|".join(item["infoHash"] for item in candidates),
            "deleteFiles": "false",
        })

    emit({
        "dryRun": dry_run,
        "retentionDays": 30,
        "candidateCount": len(candidates),
        "removedCount": 0 if dry_run else len(candidates),
        "filesDeleted": False,
        "torrents": candidates,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    })


def save_inspection(payload):
    INSPECTION_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(INSPECTION_DIR, 0o700)
    inspection_id = secrets.token_urlsafe(24)
    target = INSPECTION_DIR / f"{inspection_id}.json"
    temporary = INSPECTION_DIR / f".{inspection_id}.tmp"
    with open(temporary, "x", encoding="utf-8") as output:
        json.dump(payload, output, separators=(",", ":"))
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    return inspection_id


def load_inspection(inspection_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", inspection_id or ""):
        fail("Invalid inspection ID", 400)
    path = INSPECTION_DIR / f"{inspection_id}.json"
    try:
        with open(path, "r", encoding="utf-8") as source:
            payload = json.load(source)
    except FileNotFoundError:
        fail("Inspection expired or was not found", 409)
    except (OSError, json.JSONDecodeError):
        fail("Inspection record could not be read", 500)
    if float(payload.get("expiresEpoch", 0)) < time.time():
        try:
            path.unlink()
        except OSError:
            pass
        fail("Inspection expired; inspect the magnet again", 409)
    return path, payload


def cleanup_expired_inspections(config):
    if not INSPECTION_DIR.is_dir():
        return
    now = time.time()
    for path in INSPECTION_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as source:
                record = json.load(source)
        except (OSError, json.JSONDecodeError):
            continue
        if float(record.get("expiresEpoch", 0)) >= now:
            continue
        info_hash = str(record.get("infoHash", "")).lower()
        if record.get("newlyAdded") and re.fullmatch(r"[a-f0-9]{40}", info_hash):
            torrent = find_torrent(config, info_hash)
            tags = {tag.strip() for tag in str((torrent or {}).get("tags", "")).split(",")}
            if torrent and "portal-probe" in tags:
                delete_files = "true" if float(torrent.get("progress") or 0) < 0.001 else "false"
                qb_request(config, "/api/v2/torrents/delete", method="POST", form={
                    "hashes": info_hash,
                    "deleteFiles": delete_files,
                })
        try:
            path.unlink()
        except OSError:
            pass


def status_action(config):
    cleanup_expired_inspections(config)
    version = qb_request(config, "/api/v2/app/version").strip()
    torrents = get_torrents(config)
    queue = count_queue_states(torrents)
    emit({
        "connected": True,
        "qbittorrentVersion": version,
        "storage": [storage_status(config)],
        "queue": {
            "downloading": queue["downloading"],
            "seeding": queue["seeding"],
            "paused": queue["paused"],
        },
        "errors": queue["errors"],
        "torrentCount": len(torrents),
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    })


def inspect_action(config, payload):
    cleanup_expired_inspections(config)
    magnet = payload.get("magnet")
    info_hash = validate_magnet(magnet)
    supplied_hash = str(payload.get("infoHash", "")).lower()
    if supplied_hash and supplied_hash != info_hash:
        fail("Magnet info hash does not match the request", 400)
    user_id = str(payload.get("userId", "unknown"))[:200]
    torrent = find_torrent(config, info_hash)
    newly_added = torrent is None
    if newly_added:
        qb_request(config, "/api/v2/torrents/add", method="POST", form={
            "urls": magnet,
            "savepath": config["QB_SAVE_PATH"],
            "tags": "portal-probe",
            "stopped": "false",
            "paused": "false",
            "dlLimit": "1",
            "autoTMM": "false",
        })
        deadline = time.monotonic() + 42
        while time.monotonic() < deadline:
            time.sleep(1.5)
            torrent = find_torrent(config, info_hash)
            if torrent and int(torrent.get("total_size") or torrent.get("size") or 0) > 0:
                break
        if not torrent or int(torrent.get("total_size") or torrent.get("size") or 0) <= 0:
            qb_request(config, "/api/v2/torrents/delete", method="POST", form={
                "hashes": info_hash,
                "deleteFiles": "true",
            })
            fail("Torrent metadata did not resolve within 42 seconds", 504)
        qb_request(config, "/api/v2/torrents/stop", method="POST", form={"hashes": info_hash})
        torrent = find_torrent(config, info_hash) or torrent

    size = int(torrent.get("total_size") or torrent.get("size") or 0)
    if size <= 0:
        fail("Torrent metadata is not available", 409)
    torrent_name = str(torrent.get("name") or "Untitled torrent")
    title, year, existing = find_existing_media(config, torrent_name)
    storage = storage_status(config)
    enough_space = storage["availableBytes"] >= int(size * 1.08)
    expires_epoch = time.time() + INSPECTION_TTL_SECONDS
    record = {
        "infoHash": info_hash,
        "magnet": magnet,
        "sizeBytes": size,
        "title": title,
        "year": year,
        "userId": user_id,
        "expiresEpoch": expires_epoch,
        "newlyAdded": newly_added,
    }
    inspection_id = save_inspection(record)
    warnings = []
    if existing:
        warnings.append("A matching movie already exists in the library. Compare the sizes before adding.")
    if not enough_space:
        warnings.append("The media volume does not have enough safe free space.")
    emit({
        "inspectionId": inspection_id,
        "valid": True,
        "metadataResolved": True,
        "title": title,
        "year": year,
        "sizeBytes": size,
        "infoHash": info_hash.upper(),
        "existingMedia": existing,
        "storage": [storage],
        "recommendedStorageId": "media-block",
        "canAdd": storage["mounted"] and storage["healthy"] and enough_space,
        "warnings": warnings,
        "expiresAt": datetime.fromtimestamp(expires_epoch, timezone.utc).isoformat(),
    })


def add_action(config, payload):
    info_hash = validate_magnet(payload.get("magnet"))
    storage = storage_status(config)
    if not storage["mounted"]:
        fail("The media volume is not mounted", 503)

    usage_percent = (
        storage["usedBytes"] / storage["totalBytes"] * 100
        if storage["totalBytes"] else 100.0
    )
    if usage_percent >= 95.0:
        emit({
            "queued": False,
            "storageFull": True,
            "storageUsagePercent": round(usage_percent, 2),
            "storage": [storage],
            "message": "Storage is 95% full or higher. Please try again later.",
        })

    torrent = find_torrent(config, info_hash)
    if torrent:
        qb_request(config, "/api/v2/torrents/addTags", method="POST", form={
            "hashes": info_hash,
            "tags": "portal-request",
        })
        qb_request(config, "/api/v2/torrents/setDownloadLimit", method="POST", form={
            "hashes": info_hash,
            "limit": "0",
        })
        qb_request(config, "/api/v2/torrents/start", method="POST", form={"hashes": info_hash})
        message = "This torrent already existed in qBittorrent and has been started."
    else:
        qb_request(config, "/api/v2/torrents/add", method="POST", form={
            "urls": payload.get("magnet"),
            "savepath": config["QB_SAVE_PATH"],
            "tags": "portal-request",
            "stopped": "false",
            "paused": "false",
            "autoTMM": "false",
        })
        message = "Torrent request was added to the download queue."

    emit({
        "queued": True,
        "storageFull": False,
        "storageUsagePercent": round(usage_percent, 2),
        "infoHash": info_hash.upper(),
        "message": message,
    })


def main():
    if len(sys.argv) < 2:
        fail("Usage: torrent-portal.py status|library|poster|duplicate-check|duplicate-check-one|duplicate-ack|cleanup-old-preview|cleanup-old|add [payload]", 400)
    action = sys.argv[1].strip().lower()
    config = load_config()
    if action == "status":
        status_action(config)
    if action == "library":
        library_action(config)
    if action == "duplicate-check":
        duplicate_check_action(config)
    if action == "cleanup-old-preview":
        cleanup_old_torrents_action(config, True)
    if action == "cleanup-old":
        cleanup_old_torrents_action(config, False)
    if action in {"add", "poster", "duplicate-check-one", "duplicate-ack"}:
        if len(sys.argv) != 3:
            fail(f"The {action} action requires an encoded payload", 400)
        payload = parse_payload(sys.argv[2])
        if action == "poster":
            poster_action(config, payload)
        if action == "duplicate-check-one":
            duplicate_check_one_action(config, payload)
        if action == "duplicate-ack":
            duplicate_ack_action(config, payload)
        add_action(config, payload)
    fail(f"Unsupported action: {action}", 400)


if __name__ == "__main__":
    main()
