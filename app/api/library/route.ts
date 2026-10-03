import { bridgeRequest, errorResponse } from "@/lib/torrent-bridge";

export async function GET() {
  try {
    return Response.json(await bridgeRequest("library"));
  } catch (error) {
    return errorResponse(error);
  }
}
