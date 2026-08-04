// Catch-all proxy from Next.js /api/* to the FastAPI backend.
//
// Path mapping:
//   /api/me          → ${BACKEND_URL}/api/me
//   /api/threads     → ${BACKEND_URL}/threads
//   /api/threads/:id → ${BACKEND_URL}/threads/:id
//   /api/chat        → ${BACKEND_URL}/chat
//
// The only backend route that lives under /api itself is /api/me
// (an identity-style convenience path). Everything else is at root.
//
// Auth handling:
//   - In prod behind Container Apps Easy Auth, the CAE forwards the
//     principal via X-MS-CLIENT-PRINCIPAL-* headers; we pass them
//     through untouched.
//   - In dev, we set NEXT_PUBLIC_DEV_BEARER in .env.local and the
//     browser sends it as the Authorization header (the DevBearer
//     wrapper below injects it on the client). We simply forward
//     Authorization straight to the backend.

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

// Headers we must NEVER forward to the backend.
const HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

function mapPath(segments: string[]): string {
  if (segments[0] === "me") return "/api/me";
  return "/" + segments.join("/");
}

function pickHeaders(req: NextRequest): Headers {
  const out = new Headers();
  req.headers.forEach((v, k) => {
    if (!HOP_HEADERS.has(k.toLowerCase())) out.set(k, v);
  });
  return out;
}

async function proxy(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await ctx.params;
  const backendPath = mapPath(path);
  const url = new URL(backendPath, BACKEND_URL);
  req.nextUrl.searchParams.forEach((v, k) => url.searchParams.append(k, v));

  const method = req.method;
  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers: pickHeaders(req),
    cache: "no-store",
  };
  if (method !== "GET" && method !== "HEAD") {
    init.body = req.body;
    init.duplex = "half";
  }

  const upstream = await fetch(url, init);
  const respHeaders = new Headers(upstream.headers);
  HOP_HEADERS.forEach((h) => respHeaders.delete(h));

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: respHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
export const PATCH = proxy;
