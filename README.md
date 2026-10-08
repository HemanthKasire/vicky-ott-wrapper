# Vicky OTT Portal

Vicky OTT Portal is a private-facing request dashboard for a Jellyfin and
qBittorrent setup. It lets approved users:

- view storage and torrent status;
- submit magnet links to qBittorrent through an authenticated n8n bridge;
- search the Jellyfin movie and TV catalog;
- optionally load Jellyfin posters; and
- detect duplicate requests after torrent metadata becomes available.

The browser never receives qBittorrent, Jellyfin, SSH, or n8n credentials.
Browser requests go to the server-side API routes, which call the n8n bridge.

## Project layout

- `app/` — portal pages and server-side API routes
- `components/` — shared interface components
- `lib/torrent-bridge.ts` — authenticated n8n bridge client
- `server/torrent-portal.py` — OCI helper for qBittorrent, storage, Jellyfin,
  duplicate checks, and torrent retention
- `BRIDGE_CONTRACT.md` — request and response contract for the n8n webhook

## Local development

Requirements:

- Node.js 22.13 or newer
- npm

Install and run:

```bash
npm ci
npm run dev
```

Before using the live bridge, provide these environment variables outside the
repository:

```text
N8N_TORRENT_BRIDGE_URL
N8N_TORRENT_BRIDGE_TOKEN
PORTAL_ACCESS_PASSWORD
PORTAL_SESSION_SECRET
```

Copy `.env.example` to `.env.local` for local development and replace every
placeholder. Never commit the resulting values. `.env*` (except the safe
example), `.portal-token`, private keys, dependencies, and generated build
output are ignored.

## Checks

```bash
npm run lint
npm run build
python3 -m py_compile server/torrent-portal.py
```

## Deployment

The portal is configured for Vercel through Vinext and Nitro:

1. Import this GitHub repository into Vercel.
2. Leave the root directory as the repository root.
3. Add all four variables from `.env.example` in Project Settings → Environment
   Variables for Production and Preview.
4. Deploy. `vercel.json` selects the Nitro framework and uses the locked npm
   installation and build commands.
5. Add the selected subdomain under Project Settings → Domains, then create the
   CNAME record Vercel provides at the existing DNS provider.

The shared password creates a signed, HTTP-only session cookie lasting 30 days.
Changing `PORTAL_ACCESS_PASSWORD` affects new sign-ins. Changing
`PORTAL_SESSION_SECRET` immediately invalidates all existing sessions.

## Security notes

- Keep the repository private if infrastructure details are added later.
- Use a unique portal password and generate a random session secret containing
  at least 32 characters.
- Keep qBittorrent and Jellyfin off the public internet.
- Validate the shared portal token in n8n before executing any action.
- Apply rate limits and an explicit user allowlist before sharing the portal.
- Do not commit API keys, webhook tokens, SSH keys, cookies, or `.env` files.

## TV show requests

Choose **TV Show**, search for the series, select the correct title/year, and
paste a magnet link for that series. The portal registers the selected series
with Sonarr without searching for additional releases. qBittorrent downloads
into `/downloads/tv` with category `portal-tv`. Sonarr imports completed
recognisable episodes into `Shows/<Series>/Season <NN>/` and refreshes Jellyfin.
Unclear episode names or a magnet for a different series require manual review.

Sonarr uses a single `/data` mount for downloads and the Shows library so imports
can use hardlinks during import. Its API stays private. The n8n bridge
must forward `mediaType` and `tvdbId` for `add`, and support `series-search`
with `{ "query": "show title" }`. Existing movie requests still use the movie
organiser. No indexers are configured; only submitted magnets are downloaded.

Backend checks: `python3 server/tv/test_tv_requests.py`.

### Enter TV details manually

Choose **TV Show → Enter manually**, then enter the show title and season.
**Episode is optional:** enter it only when the torrent has one episode video.
Leave it blank for episode folders or season packs; the sorter reads episode
numbers from filenames (`S01E02`, `1x02`, `E02`, `Episode 02`, or `02 - Title`).
The supplied season must agree with explicit season markers in filenames.
Unrecognised files and existing destinations are left intact and reported in
**TV sorting** after refreshing storage. No show search is needed in this mode.

Manual downloads use category `portal-tv-manual` and `/downloads/tv-manual`.
A background service checks completed downloads every minute, creates hardlinks
under `Shows/<Title>/Season <NN>/`, preserves adjacent subtitles, and refreshes
Jellyfin. It refuses an episode override for multi-video torrents. Unimported
manual downloads are excluded from automatic torrent retention cleanup.

Use `server/tv/install-manual-tv.sh` on the OCI host after deploying the updated
helper. n8n must forward `manualTV: {title, season, episode}` instead of `tvdbId`
for manual requests; `episode` can be `null`. Run both backend test files under
`server/tv/` to verify request routing and manual sorting.

### Stop seeding and clean imported TV downloads

Torrent requests use zero seeding limits. The TV cleanup installer applies
`configure-no-seeding.py` once to update existing torrents and global settings. The host also sets global zero limits
with the Stop action, so completed downloads stop automatically. Uploads may
still occur while a torrent is actively downloading.

Install `server/tv/install-tv-cleanup.sh` after deploying the portal helper.
Every minute the cleanup service checks completed `portal-tv` and
`portal-tv-manual` torrents. It removes the torrent and its original download
files only when every selected video is a verified hardlink in Shows. Manual
imports must also be marked imported. Incomplete or unrecognised episodes are
kept for review. Movies are excluded from this TV cleanup. Sonarr's own completed
download removal stays disabled so there is only one cleanup owner.

Run the installed cleanup helper with `--preview` to check without deleting.
Import records remain available for status and Jellyfin refresh retries.

### Clean imported movie downloads

Install `server/movies/install-movie-cleanup.sh` on the OCI host. The existing
movie organizer continues moving films and subtitles into Movies and requesting
Jellyfin refreshes. A separate timer checks completed, uncategorized torrents in
`/downloads/complete` every minute, then removes the torrent entry and original
download leftovers only after every selected video has a verified library copy.
TV torrents and other download locations are excluded.

Verification uses hardlink identity where available. For files already moved or
copied, it checks exact size and first, middle, and last independently readable
pieces against qBittorrent's torrent hashes. This is sampled content verification,
not a full integrity scan. Unsupported metadata, incomplete or missing videos,
unsafe paths, and hash mismatches keep the torrent for review. Piece reads are
bounded at 32 MiB each, with low CPU priority and a 20% service CPU limit.

Run `/usr/local/bin/portal-movie-cleanup.py --preview` as root to verify without
deleting; cleanup manifests are private under `/var/lib/torrent-portal/movie-cleanup`.
Backend checks: `python3 -m unittest discover -s server/movies`.
