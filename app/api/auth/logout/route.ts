import {
  portalSessionCookieOptions,
  PORTAL_SESSION_COOKIE,
} from "@/lib/portal-auth";
import { NextResponse } from "next/server";

export async function GET(request: Request) {
  const response = NextResponse.redirect(new URL("/login", request.url), 303);
  response.cookies.set(PORTAL_SESSION_COOKIE, "", portalSessionCookieOptions(0));
  return response;
}
