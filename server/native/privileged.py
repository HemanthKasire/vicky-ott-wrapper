#!/usr/bin/python3
"""Fixed, stdin-only privilege boundary. Install root-owned; never writable by the API user."""
import base64
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

PORTAL = "/usr/local/bin/torrent-portal.py"
COMMANDS = {"start", "help", "status", "cpu", "memory", "storage", "docker", "services"}
PORTAL_ACTIONS = {"status", "library", "poster", "series-search", "add", "duplicate-check-one", "duplicate-ack"}


def run(request):
    action = request.get("action")
    payload = request.get("payload", {})
    if not isinstance(payload, dict):
        raise ValueError("Invalid payload")
    if action in PORTAL_ACTIONS:
        args = [PORTAL, action]
        if action not in {"status", "library"}:
            args.append(base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("="))
        result = subprocess.run(args, capture_output=True, text=True, timeout=65)
        try:
            data = json.loads(result.stdout)
        except ValueError:
            return {"error": "Torrent helper did not return JSON", "status": 502}
        if result.returncode:
            data.setdefault("status", 502)
        return data
    if action == "pending-duplicates":
        spec = importlib.util.spec_from_file_location("portal", PORTAL)
        portal = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(portal)
        hashes = []
        for item in portal.get_torrents(portal.load_config()):
            tags = {t.strip() for t in item.get("tags", "").split(",")}
            if (item.get("category") not in {"portal-tv", "portal-tv-manual"}
                    and "portal-request" in tags
                    and not tags.intersection({"portal-duplicate-checked", "portal-duplicate-alerted"})
                    and re.fullmatch(r"[a-fA-F0-9]{40}", item.get("hash", ""))):
                hashes.append(item["hash"].upper())
        return {"hashes": hashes}
    if action == "stats":
        command = payload.get("command", "status")
        if command not in COMMANDS:
            raise ValueError("Command not allowed")
        args = ["/usr/local/bin/server-stats.sh", command]
    elif action == "health":
        args = ["/usr/local/bin/server-health-check.sh"]
    elif action in {"jellyfin-stats", "jellyfin-health"}:
        target = json.loads(Path("/etc/oci-automation/ssh.json").read_text())
        if not re.fullmatch(r"[a-zA-Z0-9_.:-]+", target["host"]) or not re.fullmatch(r"[a-zA-Z0-9_-]+", target["username"]):
            raise ValueError("Invalid SSH configuration")
        script = "/usr/local/bin/jellyfin-stats.sh" if action.endswith("stats") else "/usr/local/bin/jellyfin-health-check.sh"
        args = ["ssh", "-i", "/etc/oci-automation/jellyfin.key", "-p", str(int(target.get("port", 22))),
                "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=yes",
                "-o", "UserKnownHostsFile=/etc/oci-automation/known_hosts",
                target["username"] + "@" + target["host"], script]
    else:
        raise ValueError("Action not allowed")
    result = subprocess.run(args, capture_output=True, text=True, timeout=50)
    return {"code": result.returncode, "stdout": result.stdout[:24000], "stderr": result.stderr[:2000]}


if __name__ == "__main__":
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError("Request too large")
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError("Invalid request")
        print(json.dumps(run(request)))
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "OCI command timed out; an add request may still have succeeded.", "status": 504}))
    except Exception:
        print(json.dumps({"error": "OCI helper failed", "status": 500}))
