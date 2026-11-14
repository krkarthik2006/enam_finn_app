const CACHE = "finn-static-v6";
self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(["/", "/demo.json", "/icon.svg"]);
    const shell = await cache.match("/");
    const html = await shell.text();
    const assets = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map(match => match[1].replaceAll("&amp;", "&")).filter(path => path.startsWith("/_next/static/"));
    await cache.addAll([...new Set(assets)]);
    await self.skipWaiting();
  })());
});
self.addEventListener("activate", event => {event.waitUntil((async () => {await Promise.all((await caches.keys()).filter(k => k.startsWith("finn-static-") && k !== CACHE).map(k => caches.delete(k))); await self.clients.claim();})());});
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (event.request.mode === "navigate") {event.respondWith(fetch(event.request).catch(() => caches.match("/"))); return;}
  if (url.pathname.startsWith("/_next/static/") || ["/demo.json", "/icon.svg"].includes(url.pathname)) {
    event.respondWith(caches.open(CACHE).then(async cache => {
      const saved = await cache.match(event.request); if (saved) return saved;
      const response = await fetch(event.request); if (response.ok) cache.put(event.request, response.clone()); return response;
    }));
  }
});
