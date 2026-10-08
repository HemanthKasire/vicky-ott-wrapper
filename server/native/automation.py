#!/usr/bin/python3
"""Small authenticated webhook API and durable automation worker; Python standard library only."""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

CONFIG = Path(os.environ.get("AUTOMATION_CONFIG", "/etc/oci-automation/config.json"))
STATE = Path(os.environ.get("AUTOMATION_STATE", "/var/lib/oci-automation"))
COMMANDS = {"start", "help", "status", "cpu", "memory", "storage", "docker", "services", "jellyfin"}
PUBLIC_ACTIONS = {"status", "library", "poster", "series-search", "add"}
LOG = logging.getLogger("oci-automation")


def helper(action, payload=None):
    try:
        result = subprocess.run(["sudo", "-n", "/usr/local/lib/oci-automation/privileged.py"],
                                input=json.dumps({"action": action, "payload": payload or {}}),
                                capture_output=True, text=True, timeout=70)
        if result.returncode:
            return {"error": "OCI helper unavailable", "status": 502}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"error": "OCI request timed out. The torrent may already have been added; check before retrying.", "status": 504}
    except (ValueError, OSError):
        return {"error": "OCI helper unavailable", "status": 502}


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (key TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, due REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS sent (key TEXT PRIMARY KEY, at REAL NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value)))

    def enqueue(self, key, kind, payload, delay=0):
        with self.connect() as db:
            if db.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone():
                return False
            return bool(db.execute("INSERT OR IGNORE INTO jobs (key,kind,payload,due) VALUES (?,?,?,?)",
                                   (key, kind, json.dumps(payload), time.time() + delay)).rowcount)

    def finish(self, key):
        with self.connect() as db:
            db.execute("DELETE FROM jobs WHERE key=?", (key,))
            db.execute("INSERT OR REPLACE INTO sent VALUES (?,?)", (key, time.time()))

    def retry(self, key, attempts, delay):
        with self.connect() as db:
            db.execute("UPDATE jobs SET attempts=?,due=? WHERE key=?", (attempts, time.time() + delay, key))

    def due(self):
        with self.connect() as db:
            return db.execute("SELECT key,kind,payload,attempts FROM jobs WHERE due<=? ORDER BY due LIMIT 12",
                              (time.time(),)).fetchall()

    def notification(self, event, channel, text, poster=None):
        self.enqueue(event, "notify", {"channel": channel, "text": text, "poster": poster})


def request_json(url, data=None, headers=None, timeout=20):
    encoded = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=encoded,
                                     headers={"Content-Type": "application/json", "User-Agent": "OCI-Automation/1", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        return json.loads(body) if body else {}


def multipart(url, fields, image, field_name):
    boundary = "oci" + secrets.token_hex(16)
    data = bytearray()
    for name, value in fields.items():
        data.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    mime = image["mimeType"]
    extension = {"image/png": "png", "image/webp": "webp", "image/avif": "avif"}.get(mime, "jpg")
    data.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; filename="poster.{extension}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
    data.extend(base64.b64decode(image["dataBase64"]))
    data.extend(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(url, data=bytes(data), headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                                                              "User-Agent": "OCI-Automation/1"})
    with urllib.request.urlopen(req, timeout=25) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def deliver(channel, destination, text, poster=None):
    if destination == "telegram":
        url = "https://api.telegram.org/bot" + channel["telegram_token"]
        if poster:
            result = multipart(url + "/sendPhoto", {"chat_id": channel["chat_id"], "caption": text[:1024]}, poster, "photo")
        else:
            result = request_json(url + "/sendMessage", {"chat_id": channel["chat_id"], "text": text[:4000]})
        if not result.get("ok"):
            raise RuntimeError("Telegram rejected notification")
    elif destination == "discord":
        url = channel["discord_url"]
        body = {"content": text[:1950], "allowed_mentions": {"parse": []}}
        if poster:
            multipart(url, {"payload_json": json.dumps(body)}, poster, "files[0]")
        else:
            request_json(url, body)


def duplicate_message(alert):
    year = lambda value: f" ({value})" if value else ""
    difference = str(alert.get("sizeDifferencePercent")) + "%" if alert.get("sizeDifferencePercent") is not None else "Unavailable"
    return "\n".join(["⚠️ DUPLICATE MOVIE DETECTED", "",
                      f"Requested: {alert.get('torrentTitle', '')}{year(alert.get('torrentYear'))}",
                      f"Download size: {alert.get('torrentSize', '')}", "",
                      f"Already in Jellyfin: {alert.get('existingTitle', '')}{year(alert.get('existingYear'))}",
                      f"Existing file size: {alert.get('existingSize', '')}", f"Size difference: {difference}", "",
                      f"Match: {alert.get('match', '')}", "", "The torrent has not been stopped automatically."])


def health_transition(result, previous, host):
    stdout = str(result.get("stdout", "")).strip()
    failed = result.get("code", 1) != 0 or not stdout
    message = stdout
    if failed:
        message = f"ALERT: {host} health check failed\n" + str(result.get("stderr") or result.get("error") or "No response was received.")
    original_alert = message.startswith("ALERT")
    if host == "docker-n8n" and not failed and original_alert:
        message = "\n".join(line for line in message.splitlines()
                            if not re.match(r"\s*-\s*(?:CPU usage is|CPU steal is|I/O wait is)\b", line, re.I))
        is_alert = any(re.match(r"\s*-\s+", line) for line in message.splitlines())
    else:
        is_alert = original_alert
    signature = re.sub(r"\n{3,}", "\n\n", re.sub(r"^Time:.*$", "", message, flags=re.M)).strip() if is_alert else ""
    notify = None
    if is_alert and previous.get("signature") != signature:
        notify = message
    elif not is_alert and previous.get("inAlert"):
        notify = f"✅ {host} recovered\nTime: {datetime.now(ZoneInfo('Asia/Kolkata')).isoformat(timespec='seconds')}\nAll monitored actionable values are back within their limits."
    return {"inAlert": is_alert, "signature": signature}, notify


class Automation:
    def __init__(self, config, store, call=helper):
        self.config, self.store, self.call = config, store, call
        self.stop = threading.Event()
        self.helper_slots = threading.BoundedSemaphore(2)
        self.add_lock = threading.Lock()
        self.cache_lock = threading.Lock()
        self.cache = {}

    def command(self, action, payload=None):
        with self.helper_slots:
            return self.call(action, payload)

    def bridge(self, body, user="unknown"):
        action = body.get("action")
        if action not in PUBLIC_ACTIONS:
            return 400, {"message": "Unsupported action"}
        payload = {**body, "userId": user[:160]}
        if action == "add":
            with self.add_lock:
                result = self.command(action, payload)
                if result.get("queued") and re.fullmatch(r"[A-Fa-f0-9]{40}", str(result.get("infoHash", ""))):
                    self.store.enqueue("duplicate:" + result["infoHash"].upper(), "duplicate",
                                       {"infoHash": result["infoHash"].upper()}, delay=120)
                if result.get("storageFull"):
                    bucket = str(int(time.time() // 3600))
                    self.store.notification("storage:" + bucket, "ott", "🚨 Vicky OTT storage warning\nStorage usage: "
                                            + str(result.get("storageUsagePercent")) + "%\nA torrent request was refused because the media volume reached 95% usage.")
                with self.cache_lock:
                    self.cache.pop("status", None)
        elif action in {"status", "library", "poster", "series-search"}:
            key = action + (":" + json.dumps(body, sort_keys=True) if action not in {"status", "library"} else "")
            with self.cache_lock:
                cached = self.cache.get(key)
                if cached and cached[0] > time.monotonic():
                    return 200, cached[1]
            result = self.command(action, payload)
            if "error" not in result:
                with self.cache_lock:
                    if len(self.cache) > 80:
                        self.cache.clear()
                    self.cache[key] = (time.monotonic() + (5 if action == "status" else 45), result)
        if "error" in result:
            status = result.get("status", 502)
            if not isinstance(status, int) or not 400 <= status <= 599:
                status = 502
            return status, {**result, "message": result["error"]}
        return 200, result

    def movie_event(self, body):
        if body.get("notificationType") == "ItemAdded" and body.get("itemType") == "Movie":
            title = str(body.get("name", "Untitled"))[:500]
            year = " (" + str(body["year"])[:10] + ")" if body.get("year") else ""
            # Some old callers have no item ID. Briefly deduplicate their title/year events.
            identity = str(body.get("itemId") or body.get("ItemId") or f"{title}:{year}:{int(time.time() // 300)}")
            event = "movie:" + hashlib.sha256(identity.encode()).hexdigest()
            self.store.notification(event, "movie", f"🎬 {title}{year} is now available in Jellyfin.")

    def telegram_event(self, body):
        update_id = body.get("update_id")
        if not isinstance(update_id, int):
            raise ValueError("Missing update ID")
        self.store.enqueue("telegram:" + str(update_id), "telegram", body)

    def process_telegram(self, body, event):
        message = body.get("message") or body.get("edited_message") or {}
        chat = str(message.get("chat", {}).get("id", ""))
        if not chat:
            return
        user = str(message.get("from", {}).get("id", ""))
        if user not in self.config["authorized_user_ids"]:
            text = "⛔ You are not authorized to access this server monitor."
        else:
            raw = str(message.get("text", "")).strip().split()
            command = (raw[0] if raw else "/help").split("@")[0].lstrip("/").lower()
            command = command if command in COMMANDS else "help"
            if command == "jellyfin":
                result = self.command("jellyfin-stats")
            else:
                result = self.command("stats", {"command": command})
            text = result.get("stdout") or result.get("stderr") or "Unable to retrieve server statistics."
            if command in {"help", "start"}:
                text += "\n/jellyfin - Jellyfin server status"
        self.store.enqueue(event + ":reply", "notify", {"channel": "monitor", "chat_id": chat, "text": text})

    def notify(self, key, payload):
        channel = dict(self.config["channels"][payload["channel"]])
        if payload.get("chat_id"):
            channel["chat_id"] = payload["chat_id"]
        poster = payload.get("poster")
        for destination in ("telegram", "discord"):
            if payload.get("chat_id") and destination == "discord":
                continue
            if not channel.get("telegram_token" if destination == "telegram" else "discord_url"):
                continue
            receipt = key + ":" + destination
            if not self.store.get(receipt, False):
                try:
                    deliver(channel, destination, payload["text"], poster)
                except urllib.error.HTTPError as error:
                    # A rejected photo can fall back to text. Do not retry text after an ambiguous timeout.
                    if poster and error.code == 400:
                        deliver(channel, destination, payload["text"], None)
                    else:
                        raise
                self.store.set(receipt, True)

    def duplicate(self, key, payload, attempts):
        result = self.command("duplicate-check-one", payload)
        if result.get("error"):
            raise RuntimeError("Duplicate check unavailable")
        if not result.get("ready"):
            if attempts >= 29:
                self.store.finish(key)
            else:
                self.store.retry(key, attempts + 1, 120)
            return
        if result.get("duplicate"):
            poster = ({"mimeType": result["posterMimeType"], "dataBase64": result["posterBase64"]}
                      if result.get("posterMimeType") and result.get("posterBase64") else None)
            self.notify(key, {"channel": "ott", "text": duplicate_message(result), "poster": poster})
            ack = self.command("duplicate-ack", payload)
            if not ack.get("acknowledged"):
                raise RuntimeError("Duplicate acknowledgement failed")
        self.store.finish(key)

    def work_once(self):
        for key, kind, raw, attempts in self.store.due():
            payload = json.loads(raw)
            try:
                if kind == "duplicate":
                    self.duplicate(key, payload, attempts)
                    continue
                if kind == "telegram":
                    self.process_telegram(payload, key)
                elif kind == "notify":
                    self.notify(key, payload)
                self.store.finish(key)
            except Exception as error:
                # Exception URLs can contain bot tokens and Discord secrets; log only the type.
                LOG.warning("Job %s retry (%s)", kind, type(error).__name__)
                self.store.retry(key, attempts + 1, min(900, 30 * 2 ** min(attempts, 5)))

    def worker(self):
        while not self.stop.is_set():
            try:
                self.work_once()
                self.store.set("worker_heartbeat", time.time())
            except Exception as error:
                LOG.error("Worker cycle failed (%s)", type(error).__name__)
            self.stop.wait(5)

    def health(self):
        for host, action in (("docker-n8n", "health"), ("jellyfin", "jellyfin-health")):
            result = self.command(action)
            previous = self.store.get("health:" + host, {})
            state, message = health_transition(result, previous, host)
            if message:
                event = "health:" + host + ":" + secrets.token_hex(12)
                self.store.notification(event, "monitor", message)
            self.store.set("health:" + host, state)
        self.store.set("health_last_run", time.time())


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, handler, automation):
        self.automation = automation
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, handler)

    def process_request(self, request, address):
        if not self.slots.acquire(False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "OCI-Automation"

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, *_args):
        pass  # Do not log secret webhook paths or tokens.

    def send_json(self, status, body):
        raw = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-OCI-Automation", "native-v1")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path == "/healthz":
            heartbeat = self.server.automation.store.get("worker_heartbeat", 0)
            healthy = time.time() - heartbeat < 180
            self.send_json(200 if healthy else 503, {"ok": healthy, "service": "oci-automation"})
        else:
            self.send_json(404, {"message": "Not found"})

    def do_POST(self):
        app = self.server.automation
        config = app.config
        path = urllib.parse.urlsplit(self.path).path
        if path in {config["bridge_path"], config["legacy_path"]}:
            if not hmac.compare_digest(self.headers.get("x-portal-token", "").encode(), config["portal_token"].encode()):
                return self.send_json(401, {"message": "Unauthorized"})
            kind = "bridge"
        elif path == config["movie_path"]:
            kind = "movie"  # Existing secret URL is retained for installed Jellyfin callers.
        elif path == config["telegram_path"]:
            if not hmac.compare_digest(self.headers.get("X-Telegram-Bot-Api-Secret-Token", "").encode(), config["telegram_secret"].encode()):
                return self.send_json(401, {"message": "Unauthorized"})
            kind = "telegram"
        else:
            return self.send_json(404, {"message": "Not found"})
        try:
            if self.headers.get("Transfer-Encoding"):
                return self.send_json(400, {"message": "Content-Length required"})
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                return self.send_json(413, {"message": "Request body must be 1 to 65536 bytes"})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            if kind == "bridge":
                if path == config["legacy_path"]:
                    body = {"action": "add", "magnet": body.get("url"), "mediaType": "movie"}
                status, result = app.bridge(body, self.headers.get("x-portal-user-id", "unknown"))
                return self.send_json(status, result)
            if kind == "movie":
                app.movie_event(body)
            else:
                app.telegram_event(body)
            self.send_json(200, {"accepted": True})
        except (ValueError, TypeError, UnicodeError):
            self.send_json(400, {"message": "Invalid JSON request"})
        except Exception as error:
            LOG.error("Request failed (%s)", type(error).__name__)
            self.send_json(500, {"message": "OCI automation request failed"})


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = json.loads(CONFIG.read_text())
    store = Store(STATE / "state.sqlite")
    app = Automation(config, store)
    mode = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if mode == "health":
        app.health()
    elif mode == "import-pending":
        result = app.command("pending-duplicates")
        if "error" in result:
            raise SystemExit("Cannot inspect pending duplicate checks")
        count = sum(store.enqueue("duplicate:" + value, "duplicate", {"infoHash": value}, 120)
                    for value in result.get("hashes", []))
        print(json.dumps({"importedDuplicateChecks": count}))
    elif mode == "serve":
        store.set("worker_heartbeat", time.time())
        worker = threading.Thread(target=app.worker, daemon=True)
        worker.start()
        server = Server((config["bind"], config.get("port", 8090)), Handler, app)
        def stop(_signum, _frame):
            app.stop.set()
            threading.Thread(target=server.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        LOG.info("Native automation service ready")
        server.serve_forever()
        server.server_close()
        worker.join(timeout=75)
    else:
        raise SystemExit("Unknown mode")


if __name__ == "__main__":
    main()
