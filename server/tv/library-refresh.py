#!/usr/bin/python3
"""Detect imported TV files and request a real Jellyfin scan, with persistent retries."""
import hashlib
import importlib.util
import json
import os
import time
import urllib.request
from datetime import datetime
from pathlib import Path

STATE = Path("/var/lib/torrent-portal/library-refresh.json")
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".webm", ".ts", ".m2ts"}


def snapshot(root):
    """Hash file metadata, never media contents. Do not follow directory symlinks."""
    root = Path(root)
    digest = hashlib.sha256()
    count = 0
    def raise_error(error):
        raise error
    for parent, directories, files in os.walk(root, followlinks=False, onerror=raise_error):
        directories[:] = sorted(name for name in directories if not name.startswith("."))
        for name in sorted(files):
            path = Path(parent) / name
            if path.suffix.lower() not in VIDEO_EXTENSIONS or path.is_symlink():
                continue
            info = path.stat()
            digest.update(json.dumps([str(path.relative_to(root)), info.st_size, info.st_mtime_ns]).encode())
            count += 1
    if not root.is_dir():
        raise OSError("Shows folder is unavailable")
    return digest.hexdigest(), count


def execution_time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError):
        return 0


def advance(state, fingerprint, task, now):
    """A scan request is not completion. Retain pending changes until success is observed."""
    state = dict(state)
    pending = state.get("pending")
    if pending:
        result = task.get("LastExecutionResult") or {}
        started = execution_time(result.get("StartTimeUtc"))
        if task.get("State") == "Idle" and started >= pending["requestedAt"] - 2:
            if result.get("Status") == "Completed":
                state["scanned"] = pending["fingerprint"]
                state.pop("pending", None)
                state.pop("lastError", None)
            else:
                state.pop("pending", None)
                state["lastError"] = "Jellyfin library scan did not complete successfully."
        elif task.get("State") == "Idle" and now - pending["requestedAt"] > 300:
            state.pop("pending", None)
            state["lastError"] = "Jellyfin did not start the requested scan; retrying."
        else:
            return state, False
    if state.get("scanned") == fingerprint:
        return state, False
    if task.get("State") != "Idle":
        return state, False
    return state, True


def api(base, key, path, method="GET"):
    req = urllib.request.Request(base + path, method=method, headers={"Authorization": "MediaBrowser Token=" + key})
    with urllib.request.urlopen(req, timeout=25) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def save(state):
    STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    temporary.chmod(0o600)
    temporary.replace(STATE)


def main():
    import fcntl
    os.umask(0o077)
    spec = importlib.util.spec_from_file_location("portal", "/usr/local/bin/torrent-portal.py")
    portal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(portal)
    config = portal.load_config()
    if not portal.is_exact_mount(config["HOST_STORAGE_PATH"]):
        raise OSError("Media volume is not mounted")
    STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(STATE.with_suffix(".lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"busy": True}))
            return
        fingerprint, count = snapshot(config.get("HOST_SHOWS_PATH", config["HOST_STORAGE_PATH"] + "/media/shows"))
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
        if state.get("scanned") == fingerprint and not state.get("pending"):
            print(json.dumps({"changed": False, "episodeFiles": count}))
            return
        base, key = portal.load_jellyfin_config()
        tasks = api(base, key, "/ScheduledTasks")
        task = next(task for task in tasks if task.get("Key") == "RefreshLibrary")
        now = time.time()
        state, request_scan = advance(state, fingerprint, task, now)
        if request_scan:
            # Record intent first so a process restart cannot continuously submit scans.
            state["pending"] = {"fingerprint": fingerprint, "requestedAt": now}
            save(state)
            try:
                api(base, key, "/Library/Refresh", "POST")
            except Exception:
                state.pop("pending", None)
                state["lastError"] = "Could not request a Jellyfin scan; changes retained for retry."
                save(state)
                raise
        save(state)
        print(json.dumps({"scanRequested": request_scan, "pending": bool(state.get("pending")), "episodeFiles": count}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print API keys or exception URLs.
        print(json.dumps({"error": "TV library refresh failed", "type": type(error).__name__}))
        raise SystemExit(1)
