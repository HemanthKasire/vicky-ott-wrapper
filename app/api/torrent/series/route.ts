import { BridgeError, bridgeRequest, errorResponse } from "@/lib/torrent-bridge";

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({})) as { query?: unknown };
    if (typeof body.query !== "string" || body.query.trim().length < 2 || body.query.trim().length > 120) {
      throw new BridgeError(400, "Enter a show name between 2 and 120 characters.");
    }
    return Response.json(await bridgeRequest("series-search", { query: body.query.trim() }));
  } catch (error) { return errorResponse(error); }
}
