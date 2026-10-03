import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export const PORTAL_SESSION_COOKIE = "vicky_ott_session";
const SESSION_LIFETIME_SECONDS = 30 * 24 * 60 * 60;
const encoder = new TextEncoder();

function requiredSecret(name: "PORTAL_ACCESS_PASSWORD" | "PORTAL_SESSION_SECRET") {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is not configured`);
  if (name === "PORTAL_SESSION_SECRET" && value.length < 32) {
    throw new Error("PORTAL_SESSION_SECRET must contain at least 32 characters");
  }
  return value;
}

function hex(bytes: ArrayBufferLike) {
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function digest(value: string) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
}

function equalBytes(left: Uint8Array, right: Uint8Array) {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left[index] ^ right[index];
  return difference === 0;
}

async function signature(payload: string) {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(requiredSecret("PORTAL_SESSION_SECRET")),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return hex(await crypto.subtle.sign("HMAC", key, encoder.encode(payload)));
}

export async function portalPasswordMatches(candidate: unknown) {
  if (typeof candidate !== "string" || candidate.length > 512) return false;
  const [provided, expected] = await Promise.all([
    digest(candidate),
    digest(requiredSecret("PORTAL_ACCESS_PASSWORD")),
  ]);
  return equalBytes(provided, expected);
}

export async function createPortalSession() {
  const expires = Math.floor(Date.now() / 1000) + SESSION_LIFETIME_SECONDS;
  const nonce = hex(crypto.getRandomValues(new Uint8Array(16)).buffer);
  const payload = `${expires}.${nonce}`;
  return `${payload}.${await signature(payload)}`;
}

export function portalSessionCookieOptions(maxAge = SESSION_LIFETIME_SECONDS) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}

async function validSessionValue(value: string | undefined) {
  if (!value) return false;
  const [expiresText, nonce, suppliedSignature, ...extra] = value.split(".");
  if (extra.length || !/^\d+$/.test(expiresText) || !/^[a-f0-9]{32}$/.test(nonce) || !/^[a-f0-9]{64}$/.test(suppliedSignature)) return false;
  if (Number(expiresText) <= Math.floor(Date.now() / 1000)) return false;
  const expectedSignature = await signature(`${expiresText}.${nonce}`);
  return equalBytes(encoder.encode(suppliedSignature), encoder.encode(expectedSignature));
}

export async function hasPortalSession() {
  const cookieStore = await cookies();
  return validSessionValue(cookieStore.get(PORTAL_SESSION_COOKIE)?.value);
}

export async function requirePortalSession() {
  if (!(await hasPortalSession())) redirect("/login");
}

export async function getPortalSessionFingerprint() {
  const cookieStore = await cookies();
  const value = cookieStore.get(PORTAL_SESSION_COOKIE)?.value;
  if (!(await validSessionValue(value))) return null;
  return `family-${hex((await digest(value!)).buffer).slice(0, 24)}`;
}
