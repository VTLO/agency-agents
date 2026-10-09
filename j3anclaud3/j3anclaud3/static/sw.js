// Minimal service worker: makes J3anClaud3 installable and keeps the app shell
// available offline. API calls and the live stream always go to the network.
const SHELL = "j3anclaud3-shell-v1";
const ASSETS = ["/", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // Network first so updates show immediately; cached shell when offline.
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        const copy = r.clone();
        if (r.ok && ASSETS.includes(url.pathname)) caches.open(SHELL).then((c) => c.put(e.request, copy));
        return r;
      })
      .catch(() => caches.match(e.request))
  );
});
