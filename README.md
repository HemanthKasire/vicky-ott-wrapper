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
```

Never commit their values. `.env*`, `.portal-token`, private keys, dependencies,
and generated build output are ignored.

## Checks

```bash
npm run lint
npm run build
python3 -m py_compile server/torrent-portal.py
```

## Deployment

The current ChatGPT Sites project metadata is retained in `.openai/hosting.json`.
The planned VM deployment will clone this repository, store secrets only on the
VM, run the web service privately, and expose it through the existing Caddy
reverse proxy. VM deployment files will be added when that deployment is set up.

## Security notes

- Keep the repository private if infrastructure details are added later.
- Keep qBittorrent and Jellyfin off the public internet.
- Validate the shared portal token in n8n before executing any action.
- Apply rate limits and an explicit user allowlist before sharing the portal.
- Do not commit API keys, webhook tokens, SSH keys, cookies, or `.env` files.
