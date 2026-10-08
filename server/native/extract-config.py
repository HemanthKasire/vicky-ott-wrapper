#!/usr/bin/python3
"""Run as root on the old host. Secrets stay on that host, never in source control."""
import datetime
import json
import os
import re
import secrets
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path("/etc/oci-automation")
DB = "/var/lib/docker/volumes/n8n_n8n_data/_data/database.sqlite"


def main():
    os.umask(0o077)
    ROOT.mkdir(mode=0o750, exist_ok=True)
    if (ROOT / "config.json").exists():
        raise SystemExit("Configuration already exists; refusing to replace secrets or routing")
    backup = Path("/var/backups/n8n-native-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup.mkdir(mode=0o700)
    connection = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
    saved = sqlite3.connect(str(backup / "database.sqlite"))
    connection.backup(saved)
    saved.close()
    subprocess.run(["cp", "-a", "/home/ubuntu/n8n/Caddyfile", str(backup / "Caddyfile")], check=True)
    subprocess.run(["cp", "-a", "/home/ubuntu/n8n/docker-compose.yml", str(backup / "docker-compose.yml")], check=True)
    old_config = Path("/var/lib/docker/volumes/n8n_n8n_data/_data/config").read_text()
    (backup / "n8n-config.json").write_text(old_config)
    instance = json.loads(subprocess.check_output(["docker", "inspect", "n8n"]))[0]
    (backup / "n8n-container.json").write_text(json.dumps(instance))
    env = dict(item.split("=", 1) for item in instance["Config"]["Env"] if "=" in item)
    key = env.get("N8N_ENCRYPTION_KEY") or json.loads(old_config)["encryptionKey"]
    rows = [dict(zip(("id", "name", "type", "data"), row)) for row in
            connection.execute("SELECT id,name,type,data FROM credentials_entity")]
    # Same legacy AES-CBC derivation as the installed n8n cipher, using only Node's crypto.
    script = r"""
const fs=require('fs'),c=require('crypto');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const output=input.rows.map(row=>{
 const b=Buffer.from(row.data,'base64');
 if(b.subarray(0,8).toString()!=='Salted__') throw Error('Unsupported credential encryption');
 const p=Buffer.concat([Buffer.from(input.key,'binary'),b.subarray(8,16)]);
 const md5=b=>c.createHash('md5').update(b).digest();
 const h1=md5(p),h2=md5(Buffer.concat([h1,p])),iv=md5(Buffer.concat([h2,p]));
 const d=c.createDecipheriv('aes-256-cbc',Buffer.concat([h1,h2]),iv);
 return {...row,data:JSON.parse(Buffer.concat([d.update(b.subarray(16)),d.final()]).toString())};
});
process.stdout.write(JSON.stringify(output));
"""
    result = subprocess.run(["docker", "exec", "-i", "n8n", "node", "-e", script],
                            input=json.dumps({"rows": rows, "key": key}), capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise SystemExit("Credential conversion failed; no secrets were printed. Backup preserved.")
    creds = {row["id"]: row for row in json.loads(result.stdout)}
    workflows = {}
    for name, raw, static in connection.execute("SELECT name,nodes,staticData FROM workflow_entity WHERE active=1"):
        workflows[name] = {"nodes": {node["name"]: node for node in json.loads(raw)},
                           "static": json.loads(static) if static else {}}
    def nodes(name):
        return workflows[name]["nodes"]
    bridge = nodes("Vicky OTT Torrent Bridge")
    movie = nodes("Jellyfin Movie Notifications")
    monitor = nodes("Vicky Server Monitor - Commands")
    health = nodes("Servers Schedule Health Check")
    def token(node):
        reference = node["credentials"]["telegramApi"]["id"]
        return creds[reference]["data"]["accessToken"]
    def channel(telegram_node, discord_node):
        url = discord_node["parameters"]["url"]
        if not url.startswith("https://discord.com/api/webhooks/") and not url.startswith("https://discordapp.com/api/webhooks/"):
            raise ValueError("Unexpected Discord endpoint")
        return {"telegram_token": token(telegram_node), "chat_id": str(telegram_node["parameters"]["chatId"]), "discord_url": url}
    gateway = subprocess.check_output(["docker", "network", "inspect", "n8n_default", "--format", "{{range .IPAM.Config}}{{.Gateway}}{{end}}"], text=True).strip()
    authorized = re.search(r"authorizedUserIds\s*=\s*new Set\(\[([\s\S]*?)\]\)", monitor["Prepare Command"]["parameters"]["jsCode"])
    if not authorized:
        raise ValueError("Cannot identify authorized monitor users")
    user_ids = re.findall(r"['\"](\d+)['\"]", authorized[1])
    if not user_ids:
        raise ValueError("No authorized users found")
    config = {
        "bind": gateway, "port": 8090,
        "bridge_path": "/webhook/" + bridge["Webhook"]["parameters"]["path"],
        "legacy_path": "/webhook/" + nodes("TorrentMagURL")["TorrentURLWH"]["parameters"]["path"],
        "movie_path": "/webhook/" + movie["Webhook"]["parameters"]["path"],
        "telegram_path": "/webhook/native-monitor-" + secrets.token_hex(24),
        "telegram_secret": secrets.token_hex(32),
        "portal_token": Path("/etc/torrent-portal/webhook-token").read_text().strip(),
        "authorized_user_ids": user_ids,
        "channels": {
            "ott": channel(bridge["Send a text message"], bridge["HTTP Request"]),
            "movie": channel(movie["Send a text message"], movie["HTTP Request"]),
            "monitor": channel(health["Telegram Alert"], health["Discord Alert"]),
        },
        "backup_dir": str(backup),
    }
    header_cred = creds[bridge["Webhook"]["credentials"]["httpHeaderAuth"]["id"]]["data"]
    if header_cred.get("name", "").lower() != "x-portal-token" or header_cred.get("value") != config["portal_token"]:
        raise ValueError("Bridge authentication mismatch")
    ssh = creds[monitor["jellyfin stats"]["credentials"]["sshPrivateKey"]["id"]]["data"]
    if ssh.get("passphrase"):
        raise ValueError("Passphrase-protected SSH key requires separate migration")
    (ROOT / "jellyfin.key").write_text(ssh["privateKey"].rstrip() + "\n")
    (ROOT / "ssh.json").write_text(json.dumps({k: ssh[k] for k in ("host", "port", "username") if k in ssh}))
    (ROOT / "config.json").write_text(json.dumps(config, indent=2))
    static = workflows["Servers Schedule Health Check"]["static"]
    global_state = static.get("global", {})
    jelly_state = static.get("node:Jellyfin Alert State", {})
    (ROOT / "initial-state.json").write_text(json.dumps({
        "health:docker-n8n": {"inAlert": global_state.get("inAlert", False), "signature": global_state.get("alertSignature", "")},
        "health:jellyfin": {"inAlert": jelly_state.get("inAlert", False), "signature": jelly_state.get("signature", "")},
    }))
    print(json.dumps({"configurationCreated": True, "backup": str(backup), "workflows": len(workflows)}))


if __name__ == "__main__":
    main()
