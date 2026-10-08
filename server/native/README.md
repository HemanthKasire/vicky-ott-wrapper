# Native OCI automation

Replaces the five published n8n workflows with a Python standard-library service,
a persistent SQLite queue, and a systemd health-check timer. The existing torrent
helper, Sonarr, movie organizer, manual-TV importer, retention timer and media
storage remain in place.

`server/tv/install-library-refresh.sh` installs a lightweight TV-import watcher.
It detects episode file changes once per minute and requests a full Jellyfin scan,
covering both Sonarr and manual imports when an import notification does not
update the remote NFS library. Pending scans are persisted and only marked done
after Jellyfin reports successful completion. Scan failures are retried without
resubmitting scans while another is running.

| n8n workflow | Replacement |
| --- | --- |
| Vicky OTT Torrent Bridge | Authenticated API, local torrent helper, durable duplicate-check jobs |
| TorrentMagURL | Legacy add endpoint using the same portal token |
| Jellyfin Movie Notifications | Existing secret movie-webhook URL, durable Telegram/Discord delivery |
| Vicky Server Monitor - Commands | Telegram webhook with a secret header, authorized-user checks, fixed status commands |
| Servers Schedule Health Check | systemd timer, existing check scripts, persistent change/recovery alert state |
| OTT (unpublished/manual) | Existing `ott-check`/`ott-process` tools plus the manual `ott-run` command |

## Access and credentials

The API runs as `oci-automation`, with no Docker-group membership. It binds only
to the Docker bridge gateway on port 8090. Caddy remains the public HTTPS gateway.
An additional root-owned systemd unit permits port 8090 only from that private
bridge, ahead of the host's existing reject rule. No public-interface rule is added.
Only a fixed root-owned stdin helper is permitted through sudo; it accepts a
limited action set and does not execute user-supplied shell commands.

The website's existing bridge URL and `x-portal-token` are retained. No website
environment change is required. The legacy `/webhook/torrent-add` endpoint now
also requires this token; callers must send it in the header. Bare unauthenticated
legacy requests are rejected.

Credentials are converted on the server into `/etc/oci-automation/config.json`
(root-owned, readable only by the service group). The Jellyfin SSH key remains
root-only. Its host key is pinned from an existing trusted SSH connection.
Never commit these configuration files, backups, tokens or keys.

Movie callers retain their existing secret webhook URL. Telegram uses both a
random URL and Telegram's secret-header verification. Monitor access remains
restricted to the user IDs from the original workflow.

## Deployment

1. Copy these source files into a root-private staging directory on the existing
   OCI host. Run `install.sh` as root. It backs up the database, encryption config,
   container metadata, Compose file and Caddy configuration before converting
   credentials. The old n8n data volume is retained intact.
2. Pin the Jellyfin SSH host key in `/etc/oci-automation/known_hosts` using its
   verified public host key. Do not accept an unverified `ssh-keyscan` result.
3. Verify the private API's status, library, TV search and monitoring calls.
4. Run `sudo python3 /usr/local/lib/oci-automation/cutover.py route`.
   This changes only the n8n site's matching webhook routes, validates/reloads
   Caddy, checks public HTTPS, and restores the original routing on failure.
5. Run `sudo python3 /usr/local/lib/oci-automation/cutover.py finish`.
   It checks bot credentials, stops n8n, registers the new bot webhook without
   dropping pending updates, imports outstanding portal duplicate checks, and
   enables the health timer. n8n is placed behind the `manual-n8n` Compose profile
   with restart disabled so it does not compete after reboot.

The installer retains an existing native configuration and queue. Re-running it
updates the root-owned code and units and restarts `oci-automation.service`.

## Operations

```sh
sudo systemctl status oci-automation.service oci-automation-health.timer
sudo journalctl -u oci-automation.service -u oci-automation-health.service
sudo python3 /usr/local/lib/oci-automation/cutover.py verify
```

`https://n8n.hemanthkasireddy.online/native-health` returns a generic worker
health response. Logs omit secret webhook paths and URLs. State and queued work
live under `/var/lib/oci-automation/state.sqlite`; include them in backups.

Notifications retry with backoff. Successful destinations are recorded separately
so a Discord failure does not resend an already successful Telegram notification.
A remote acceptance followed by a connection failure can still cause a duplicate
on retry; external delivery is not transactional. Duplicate torrent alerts are
acknowledged only after both destinations succeed. Metadata checks retain the
original two-minute interval and maximum 30 attempts.

Health alerts preserve the original CPU-only suppression, changes and recovery
behavior. Local monitoring cannot report a complete outage of its own host;
external monitoring is needed for that.

## Manual OTT

The old unpublished workflow had an empty final publish command. The new manual
runner checks files from `/mnt/storage/_incoming` by default. Explicit execution
uses the existing inexpensive compatibility processor if required, verifies
approval, then publishes into Movies without overwriting existing files. It
does not start automatically or perform video transcoding itself.

```sh
sudo ott-run /mnt/storage/_incoming/movies/example.mkv
sudo ott-run /mnt/storage/_incoming/movies/example.mkv --execute
```

Files requiring review are left in place. Processed output must be inside
`/mnt/storage/_processing`. The original source of a processed file is retained.
Existing Jellyfin library scans continue to discover published media.

## Rollback

```sh
sudo python3 /usr/local/lib/oci-automation/cutover.py rollback
```

This stops native scheduled checks, restores the original Compose and Caddy
configuration, starts n8n, and stops the replacement worker. n8n re-registers its
Telegram webhook on startup. Allow startup to finish before testing the editor.
Queued native work is retained for investigation; avoid replaying notifications
without reviewing delivery receipts. No n8n data volume or workflow is deleted.

## Verification

```sh
python3 -m unittest discover -s server/native -p 'test_*.py' -v
python3 -m unittest discover -s server/tv -p 'test_*.py' -v
```

The tests cover authentication, allowed actions/commands, manual-TV forwarding,
durable jobs, duplicate acknowledgements, partial delivery retries, and health
alert changes/recoveries. Live migration checks use read-only API calls and
invalid add requests; they do not download test media or send test notifications.
