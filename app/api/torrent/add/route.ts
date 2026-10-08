import { BridgeError, bridgeRequest, errorResponse, parseMagnet } from "@/lib/torrent-bridge";

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({})) as { magnet?: unknown; mediaType?: unknown; tvdbId?: unknown; manualTV?: unknown };
    const parsed = parseMagnet(body.magnet);
    const mediaType = body.mediaType ?? "movie";
    if (mediaType !== "movie" && mediaType !== "show") throw new BridgeError(400, "Choose Movie or TV Show.");
    let tvDetails: Record<string, unknown> = {};
    if (mediaType === "show") {
      if (body.manualTV !== undefined) {
        if (!body.manualTV || typeof body.manualTV !== "object" || Array.isArray(body.manualTV)) throw new BridgeError(400, "Enter the show title and season.");
        const value = body.manualTV as { title?: unknown; season?: unknown; episode?: unknown };
        const title = typeof value.title === "string" ? value.title.trim() : "";
        if (!title || title.length > 120 || new TextEncoder().encode(title).length > 160 || /[\\/<>:"|?*\x00-\x1f]/.test(title) || title === "." || title === ".." || title.endsWith(".")) {
          throw new BridgeError(400, "Enter a show title without path separators or special filename characters.");
        }
        if (!Number.isSafeInteger(value.season) || Number(value.season) < 0 || Number(value.season) > 999) throw new BridgeError(400, "Season must be a whole number between 0 and 999.");
        const episode = value.episode ?? null;
        if (episode !== null && (!Number.isSafeInteger(episode) || Number(episode) < 1 || Number(episode) > 9999)) throw new BridgeError(400, "Episode must be 1 to 9999, or left blank for automatic sorting.");
        tvDetails = { manualTV: { title, season: value.season, episode } };
      } else {
        if (!Number.isSafeInteger(body.tvdbId) || Number(body.tvdbId) <= 0) throw new BridgeError(400, "Select a TV show or enter its details manually.");
        tvDetails = { tvdbId: body.tvdbId };
      }
    }
    return Response.json(await bridgeRequest("add", { ...parsed, mediaType, ...tvDetails }));
  } catch (error) { return errorResponse(error); }
}
