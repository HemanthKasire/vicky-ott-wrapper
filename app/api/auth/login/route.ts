import {
  createPortalSession,
  portalPasswordMatches,
  portalSessionCookieOptions,
  PORTAL_SESSION_COOKIE,
} from "@/lib/portal-auth";
import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({})) as { password?: unknown };
  if (!(await portalPasswordMatches(body.password))) {
    return NextResponse.json({ error: "Incorrect access password" }, { status: 401 });
  }

  const response = NextResponse.json({ authenticated: true });
  response.cookies.set(
    PORTAL_SESSION_COOKIE,
    await createPortalSession(),
    portalSessionCookieOptions(),
  );
  return response;
}
