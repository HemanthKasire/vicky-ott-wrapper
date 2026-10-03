import { bridgeRequest, errorResponse, parseMagnet } from "@/lib/torrent-bridge";

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({})) as { magnet?: unknown };
    const parsed = parseMagnet(body.magnet);
    return Response.json(await bridgeRequest("add", parsed));
  } catch (error) { return errorResponse(error); }
}
