import { headers } from "next/headers";

const USER_ID_HEADER = "oai-authenticated-user-id";
const USER_EMAIL_HEADER = "oai-authenticated-user-email";
const MAX_MAGNET_LENGTH = 8192;

export class BridgeError extends Error {
  constructor(public status: number, message: string, public detail?: string) {
    super(message);
  }
}

export function parseMagnet(value: unknown) {
  if (typeof value !== "string" || value.length < 20 || value.length > MAX_MAGNET_LENGTH) {
    throw new BridgeError(400, "Invalid magnet link", "Paste one complete magnet link.");
  }

  let url: URL;
  try { url = new URL(value); }
  catch { throw new BridgeError(400, "Invalid magnet link", "The magnet link could not be parsed."); }

  if (url.protocol !== "magnet:") {
    throw new BridgeError(400, "Invalid magnet link", "Only magnet links are accepted.");
  }

  const exactTopics = url.searchParams.getAll("xt");
  const btih = exactTopics.map((topic) => /^urn:btih:([a-zA-Z0-9]+)$/i.exec(topic)?.[1]).find(Boolean);
  if (!btih || !(/^[a-fA-F0-9]{40}$/.test(btih) || /^[a-zA-Z2-7]{32}$/.test(btih))) {
    throw new BridgeError(400, "Invalid BitTorrent info hash", "The link needs a valid 40-character hex or 32-character base32 btih hash.");
  }

  return { magnet: value, infoHash: btih.toUpperCase() };
}

export async function bridgeRequest(action: "status" | "library" | "poster" | "add", payload: Record<string, unknown> = {}) {
  const bridgeUrl = process.env.N8N_TORRENT_BRIDGE_URL;
  const bridgeToken = process.env.N8N_TORRENT_BRIDGE_TOKEN;
  if (!bridgeUrl || !bridgeToken) {
    throw new BridgeError(503, "OCI bridge not connected", "Add the n8n production webhook URL and portal token in the site environment.");
  }

  const requestHeaders = await headers();
  const userId = requestHeaders.get(USER_ID_HEADER);
  const userEmail = requestHeaders.get(USER_EMAIL_HEADER);
  const host = requestHeaders.get("host") || "";
  const localPreview = host.startsWith("127.0.0.1") || host.startsWith("localhost");
  if (!userId && !localPreview) {
    throw new BridgeError(401, "Sign-in required", "Please sign in again before using the portal.");
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20_000);
  try {
    const response = await fetch(bridgeUrl, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-portal-token": bridgeToken,
        "x-portal-user-id": userId || "local-preview",
        "x-portal-user-email": userEmail || "local-preview",
      },
      body: JSON.stringify({ action, ...payload }),
      signal: controller.signal,
      cache: "no-store",
    });

    const data = await response.json().catch(() => null) as Record<string, unknown> | null;
    if (!response.ok) {
      const safeMessage = typeof data?.message === "string" ? data.message : `OCI bridge returned HTTP ${response.status}`;
      throw new BridgeError(response.status >= 500 ? 502 : response.status, "OCI request failed", safeMessage);
    }
    if (!data || typeof data !== "object") throw new BridgeError(502, "Invalid OCI response", "The n8n webhook did not return JSON.");
    return data;
  } catch (error) {
    if (error instanceof BridgeError) throw error;
    if (error instanceof Error && error.name === "AbortError") throw new BridgeError(504, "OCI request timed out", "The OCI bridge did not answer in time.");
    throw new BridgeError(502, "Could not reach OCI", error instanceof Error ? error.message : "Network request failed");
  } finally { clearTimeout(timeout); }
}

export function errorResponse(error: unknown) {
  if (error instanceof BridgeError) return Response.json({ error: error.message, detail: error.detail }, { status: error.status });
  return Response.json({ error: "Unexpected server error" }, { status: 500 });
}
