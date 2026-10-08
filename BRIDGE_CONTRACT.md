# n8n torrent bridge contract

The Site sends authenticated server-to-server `POST` requests to one n8n production webhook. The browser never receives the webhook URL or token.

Required request header:

```text
x-portal-token: <shared random secret>
```

The JSON body always has an `action` field. n8n must reject an incorrect token before doing any work and should rate-limit each `x-portal-user-id`.

## `status`

Return HTTP 200 with:

```json
{
  "connected": true,
  "storage": [{
    "id": "media-block",
    "label": "Media block volume",
    "totalBytes": 107374182400,
    "usedBytes": 53687091200,
    "availableBytes": 53687091200,
    "mounted": true,
    "healthy": true
  }],
  "queue": { "downloading": 1, "seeding": 2, "paused": 0 },
  "checkedAt": "2026-10-02T09:30:00Z"
}
```

## `inspect`

Input includes `magnet` and `infoHash`. Resolve metadata without starting a download (for example, add paused, wait for metadata, then keep or remove the paused probe). Normalize title/year and compare it with the movie library. Never return an absolute server path.

Return HTTP 200 with:

```json
{
  "inspectionId": "opaque-short-lived-id",
  "valid": true,
  "metadataResolved": true,
  "title": "Example Movie",
  "year": 2026,
  "sizeBytes": 8589934592,
  "infoHash": "0123456789ABCDEF0123456789ABCDEF01234567",
  "existingMedia": {
    "title": "Example Movie (2026)",
    "sizeBytes": 6442450944,
    "year": 2026,
    "match": "exact"
  },
  "storage": [],
  "recommendedStorageId": "media-block",
  "canAdd": true,
  "warnings": ["A library copy already exists."],
  "expiresAt": "2026-10-02T09:40:00Z"
}
```

The `inspectionId` must be random, short-lived, tied to the user and info hash, and single-use after a successful add.

## `add`

Input includes `inspectionId`, `magnet`, `infoHash`, and `storageId`. Re-check the inspection, mount, free space, duplicate status, and storage allowlist. Do not accept a raw filesystem path from the client.

Return HTTP 200 with:

```json
{ "queued": true, "message": "Example Movie was added to the download queue." }
```

## TV extensions

The current direct `add` flow accepts `magnet`, `infoHash`, and `mediaType`
(`movie` or `show`, default `movie`). A show request also requires a positive
integer `tvdbId` selected from `series-search`. The server rechecks mounted
storage and the 95% capacity limit. The legacy inspection flow above is not
used by the current portal.

`series-search` accepts `{ "action": "series-search", "query": "show title" }`
and returns `{ "items": [{ "tvdbId": 123, "title": "Example", "year": 2024 }] }`.
Keep this action behind the same authenticated bridge as other requests.
