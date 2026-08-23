const CACHE = "palworld-tcg-v1";
const PRECACHE = [
  "/",
  "/offline",
  "/static/css/app.css",
  "/static/js/app.js",
  "/static/js/chat.js",
  "/static/js/offline.js",
  "/static/img/favicon.svg",
  "/static/img/icon-512.png",
  "/manifest.webmanifest",
  "/api/catalog.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.pathname.startsWith("/api/chat") || url.pathname.startsWith("/api/collection") || url.pathname.startsWith("/api/decks") || url.pathname.startsWith("/admin") || url.pathname.startsWith("/konto")) {
    return;
  }
  if (url.pathname.startsWith("/static/") || url.pathname.startsWith("/images/") || url.pathname === "/api/catalog.json") {
    event.respondWith(
      caches.match(req).then((hit) => {
        const fetched = fetch(req).then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put(req, copy));
          }
          return res;
        }).catch(() => hit);
        return hit || fetched;
      })
    );
    return;
  }
  event.respondWith(
    fetch(req).then((res) => {
      if (res.ok && (url.pathname === "/" || url.pathname.startsWith("/card/"))) {
        const copy = res.clone();
        caches.open(CACHE).then((cache) => cache.put(req, copy));
      }
      return res;
    }).catch(() => caches.match(req).then((hit) => hit || caches.match("/offline")))
  );
});
