import { bridgeRequest } from "@/lib/torrent-bridge";

export async function GET(request: Request) {
  const itemId = new URL(request.url).searchParams.get("id") || "";
  if (!/^[a-fA-F0-9]{16,64}$/.test(itemId)) {
    return new Response("Invalid poster ID", { status: 400 });
  }

  try {
    const result = await bridgeRequest("poster", { itemId }) as {
      found?: boolean; mimeType?: string; dataBase64?: string;
    };
    if (!result.found || !result.dataBase64 || !result.mimeType) {
      return new Response("Poster not found", { status: 404 });
    }
    const bytes = Uint8Array.from(atob(result.dataBase64), (character) => character.charCodeAt(0));
    return new Response(bytes, {
      headers: {
        "Content-Type": result.mimeType,
        "Cache-Control": "private, max-age=86400",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return new Response("Poster unavailable", { status: 502 });
  }
}
