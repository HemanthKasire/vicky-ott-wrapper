#!/usr/bin/python3
"""Root-only cutover/rollback. Does not print URLs containing secrets or credential values."""
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/etc/oci-automation")
CONFIG = json.loads((ROOT / "config.json").read_text())
BACKUP = Path(CONFIG["backup_dir"])
CADDY = Path("/home/ubuntu/n8n/Caddyfile")
COMPOSE = Path("/home/ubuntu/n8n/docker-compose.yml")
BASE = "https://n8n.hemanthkasireddy.online"


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)


def api(token, method, body=None):
    req = urllib.request.Request("https://api.telegram.org/bot" + token + "/" + method,
                                 data=json.dumps(body or {}).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as response:
        data = json.load(response)
    if not data.get("ok"):
        raise RuntimeError("Telegram API rejected request")
    return data["result"]


def check_bridge():
    for action in ("status", "library"):
        req = urllib.request.Request(BASE + CONFIG["bridge_path"], data=json.dumps({"action": action}).encode(),
                                     headers={"Content-Type": "application/json", "x-portal-token": CONFIG["portal_token"]})
        with urllib.request.urlopen(req, timeout=75) as response:
            if response.headers.get("X-OCI-Automation") != "native-v1":
                raise RuntimeError("Request did not reach native automation")
            data = json.load(response)
        if data.get("connected") is not True:
            raise RuntimeError("Public bridge check failed")
        print(json.dumps({"action": action, "publicHTTPS": True, "connected": True}))


def route():
    old = (BACKUP / "Caddyfile").read_text()
    paths = " ".join(CONFIG[k] for k in ("bridge_path", "legacy_path", "movie_path", "telegram_path"))
    address = CONFIG["bind"] + ":" + str(CONFIG["port"])
    replacement = """n8n.hemanthkasireddy.online {
    @native path PATHS
    handle @native {
        reverse_proxy ADDRESS {
            transport http {
                dial_timeout 5s
                response_header_timeout 75s
            }
        }
    }
    handle /native-health {
        rewrite * /healthz
        reverse_proxy ADDRESS
    }
    handle {
        reverse_proxy n8n:5678
    }
}""".replace("PATHS", paths).replace("ADDRESS", address)
    target, count = re.subn(r"n8n\.hemanthkasireddy\.online\s*\{\s*reverse_proxy n8n:5678\s*\}", lambda _: replacement, old, count=1)
    if count != 1:
        raise RuntimeError("Unexpected original Caddy configuration; refusing automatic replacement")
    try:
        CADDY.write_text(target)  # Keep the inode of the file bind-mounted into Caddy.
        run("docker", "exec", "caddy", "caddy", "validate", "--config", "/etc/caddy/Caddyfile")
        run("docker", "exec", "caddy", "caddy", "reload", "--config", "/etc/caddy/Caddyfile")
        check_bridge()
    except Exception:
        CADDY.write_text(old)
        run("docker", "exec", "caddy", "caddy", "reload", "--config", "/etc/caddy/Caddyfile")
        raise
    print("Production bridge and movie webhooks now use native automation")


def finish():
    check_bridge()
    token = CONFIG["channels"]["monitor"]["telegram_token"]
    previous = api(token, "getWebhookInfo")
    (BACKUP / "telegram-webhook.json").write_text(json.dumps(previous))
    for value in {c["telegram_token"] for c in CONFIG["channels"].values()}:
        api(value, "getMe")
    compose = COMPOSE.read_text()
    match = re.search(r"(?m)^  n8n:\s*\n", compose)
    if not match:
        raise RuntimeError("Unexpected compose layout")
    tail = compose[match.end():]
    end = re.search(r"(?m)^  [A-Za-z0-9_-]+:\s*$|^\S", tail)
    section = tail[:end.start()] if end else tail
    remaining = tail[len(section):]
    if re.search(r"(?m)^    profiles:", section):
        raise RuntimeError("Existing n8n profiles need manual review")
    section = re.sub(r"(?m)^    restart:.*$", '    restart: "no"', section)
    if not re.search(r"(?m)^    restart:", section):
        section = '    restart: "no"\n' + section
    new_compose = compose[:match.end()] + '    profiles: ["manual-n8n"]\n' + section + remaining
    COMPOSE.write_text(new_compose)
    run("docker", "compose", "-f", str(COMPOSE), "config", "--quiet")
    run("docker", "update", "--restart=no", "n8n")
    try:
        run("docker", "stop", "--time", "60", "n8n")
        # Register after shutdown; old n8n may otherwise remove the bot webhook while stopping.
        api(token, "setWebhook", {"url": BASE + CONFIG["telegram_path"], "secret_token": CONFIG["telegram_secret"],
                                 "allowed_updates": ["message"], "drop_pending_updates": False})
        result = api(token, "getWebhookInfo")
        if result.get("url") != BASE + CONFIG["telegram_path"]:
            raise RuntimeError("Bot webhook switch was not confirmed")
        run("runuser", "-u", "oci-automation", "--", "python3", "/usr/local/lib/oci-automation/automation.py", "import-pending")
        run("systemctl", "enable", "--now", "oci-automation-health.timer")
        run("systemctl", "start", "oci-automation-health.service")
        check_bridge()
        # Replace the retired editor fallback with a small explanatory response.
        current = CADDY.read_text()
        current = current.replace("    handle {\n        reverse_proxy n8n:5678\n    }", '    handle {\n        respond "Automations now run directly on OCI. The n8n editor is stopped; its data and workflows are backed up." 200\n    }')
        CADDY.write_text(current)
        run("docker", "exec", "caddy", "caddy", "validate", "--config", "/etc/caddy/Caddyfile")
        run("docker", "exec", "caddy", "caddy", "reload", "--config", "/etc/caddy/Caddyfile")
        (ROOT / "cutover-complete").write_text(str(time.time()))
        print("Telegram, scheduled checks and webhooks migrated; n8n stopped with data retained")
    except Exception:
        rollback()
        raise


def rollback():
    run("systemctl", "stop", "oci-automation-health.timer")
    COMPOSE.write_text((BACKUP / "docker-compose.yml").read_text())
    instance = json.loads((BACKUP / "n8n-container.json").read_text())
    policy = instance["HostConfig"]["RestartPolicy"]["Name"] or "no"
    run("docker", "update", "--restart=" + policy, "n8n")
    run("docker", "start", "n8n")
    CADDY.write_text((BACKUP / "Caddyfile").read_text())
    run("docker", "exec", "caddy", "caddy", "reload", "--config", "/etc/caddy/Caddyfile")
    # n8n registers its original bot webhook during startup. No duplicate registration here.
    run("systemctl", "stop", "oci-automation.service")
    print("Original routing and n8n restored; allow n8n to finish starting")


if __name__ == "__main__":
    try:
        mode = sys.argv[1] if len(sys.argv) > 1 else "verify"
        {"route": route, "finish": finish, "rollback": rollback, "verify": check_bridge}[mode]()
    except Exception as error:
        # Avoid exception messages containing secret bot or webhook URLs.
        print("Migration step failed: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
