import { BridgeError, bridgeRequest, errorResponse, parseMagnet } from "@/lib/torrent-bridge";

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({})) as { magnet?: unknown; mediaType?: unknown; tvdbId?: unknown };
    const parsed = parseMagnet(body.magnet);
    const mediaType = body.mediaType ?? "movie";
    if (mediaType !== "movie" && mediaType !== "show") throw new BridgeError(400, "Choose Movie or TV Show.");
    if (mediaType === "show" && (!Number.isSafeInteger(body.tvdbId) || Number(body.tvdbId) <= 0)) {
      throw new BridgeError(400, "Select a TV show before adding its torrent.");
    }
    return Response.json(await bridgeRequest("add", { ...parsed, mediaType, ...(mediaType === "show" ? { tvdbId: body.tvdbId } : {}) }));
  } catch (error) { return errorResponse(error); }
}
