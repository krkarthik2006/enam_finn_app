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
  const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.text();
  let requestedMode = request.nextUrl.searchParams.get("mode");
  if (body) {
    try {requestedMode = JSON.parse(body).mode || requestedMode;} catch {}
  }
  if (requestedMode && requestedMode !== "live") return Response.json({detail: "Company data must use primary sources."}, {status: 422});
  if (path[0] === "demo") return Response.json({detail: "Test fixtures are unavailable in the public app."}, {status: 404});
  const target = new URL(`/api/${path.map(encodeURIComponent).join("/")}`, process.env.FINN_BACKEND_URL || "http://127.0.0.1:8000");
  target.search = request.nextUrl.search;
  const headers: Record<string, string> = {"Content-Type": "application/json"};
  if (process.env.FINN_API_TOKEN) headers.Authorization = `Bearer ${process.env.FINN_API_TOKEN}`;
  try {
    const response = await fetch(target, {method: request.method, headers, cache: "no-store", redirect: "manual", signal: request.signal,
      body});
    const responseHeaders = new Headers({"Content-Type": response.headers.get("content-type") || "application/json", "Cache-Control": "no-store"});
    for (const name of ["location", "content-disposition", "retry-after"]) {
      const value = response.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new Response(response.body, {status: response.status, headers: responseHeaders});
  } catch {
    return Response.json({detail: "Connection unavailable. Saved company data is available offline."}, {status: 503});
  }
}
export {proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE};
