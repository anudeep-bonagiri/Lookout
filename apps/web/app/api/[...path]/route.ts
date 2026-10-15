import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const base = (process.env["API_URL"] || "http://127.0.0.1:8000").replace(/\/$/, "");
  const target = new URL(`${base}/${path.join("/")}`);
  target.search = request.nextUrl.search;
  const headers = new Headers(request.headers);
  headers.delete("host");
  // The shared API key never leaves the server: strip whatever the browser sent and add ours.
  headers.delete("x-lookout-key");
  const key = process.env["LOOKOUT_API_KEY"];
  if (key) headers.set("x-lookout-key", key);
  const method = request.method;
  const hasBody = method !== "GET" && method !== "HEAD";
  const response = await fetch(target, {
    method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    cache: "no-store",
  });
  const outgoing = new Headers(response.headers);
  outgoing.delete("content-encoding");
  outgoing.delete("content-length");
  return new Response(response.body, { status: response.status, headers: outgoing });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
