const CACHE = "finn-static-v12";
self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(["/", "/snapshot.json", "/icon.svg"]);
    const shell = await cache.match("/");
    const html = await shell.text();
    const assets = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map(match => match[1].replaceAll("&amp;", "&")).filter(path => path.startsWith("/_next/static/"));
    await cache.addAll([...new Set(assets)]);
    await self.skipWaiting();
  })());
});
self.addEventListener("activate", event => {event.waitUntil((async () => {
  const previous = (await caches.keys()).filter(k => k.startsWith("finn-static-") && k !== CACHE);
  await Promise.all(previous.map(k => caches.delete(k)));
  await self.clients.claim();
  if (previous.length) {
    const windows = await self.clients.matchAll({type: "window"});
    // Let activation finish before the replacement page loads through this worker.
    for (const client of windows) client.navigate(client.url).catch(() => {});
  }
})());});
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (event.request.mode === "navigate") {event.respondWith(fetch(event.request).catch(() => caches.match("/"))); return;}
  if (url.pathname.startsWith("/_next/static/") || ["/snapshot.json", "/icon.svg"].includes(url.pathname)) {
    event.respondWith(caches.open(CACHE).then(async cache => {
      const saved = await cache.match(event.request); if (saved) return saved;
      const response = await fetch(event.request); if (response.ok) cache.put(event.request, response.clone()); return response;
    }));
  }
});
