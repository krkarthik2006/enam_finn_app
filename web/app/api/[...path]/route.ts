import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

async function proxy(request: NextRequest, context: {params: Promise<{path: string[]}>}) {
  if (!["GET","HEAD"].includes(request.method)) {
    const origin = request.headers.get("origin");
    let sameOrigin = !origin;
    try { if (origin) sameOrigin = new URL(origin).host === request.headers.get("host"); } catch {}
    if (!sameOrigin) return Response.json({detail:"Cross-origin write refused"},{status:403});
  }
  const {path} = await context.params;
  const target = new URL(`/api/${path.map(encodeURIComponent).join("/")}`, process.env.FINN_BACKEND_URL || "http://127.0.0.1:8000");
  target.search = request.nextUrl.search;
  const headers: Record<string, string> = {"Content-Type": "application/json"};
  if (process.env.FINN_API_TOKEN) headers.Authorization = `Bearer ${process.env.FINN_API_TOKEN}`;
  try {
    const response = await fetch(target, {method: request.method, headers, cache: "no-store", signal: request.signal,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.text()});
    return new Response(response.body, {status: response.status, headers: {"Content-Type": response.headers.get("content-type") || "application/json", "Cache-Control": "no-store"}});
  } catch {
    return Response.json({detail: "Backend is offline. The saved demo is available."}, {status: 503});
  }
}
export {proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE};
