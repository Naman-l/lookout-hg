/* Lookout service worker: reads only. It keeps the last-read screens readable when the connection drops.
   Nothing that changes data is ever cached or replayed: approvals, rejections and runs need the live server. */
const SHELL = "lookout-shell-v1";
const DATA = "lookout-data-v1";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.add("/")).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => ![SHELL, DATA].includes(k)).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

const stamped = (res) => {
  const h = new Headers(res.headers);
  h.set("x-lookout-fetched", new Date().toISOString());
  return res.clone().blob().then((b) => new Response(b, { status: res.status, statusText: res.statusText, headers: h }));
};

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // Data: network first; when it fails, answer from the last copy, marked as cached.
  if (url.pathname.startsWith("/api/")) {
    if (req.headers.get("accept")?.includes("text/event-stream") || url.pathname.endsWith("/stream")) return;
    e.respondWith(
      fetch(req).then(
        async (res) => {
          if (res.ok) { const copy = await stamped(res); const c = await caches.open(DATA); await c.put(req, copy); }
          return res;
        },
        async () => {
          const hit = await (await caches.open(DATA)).match(req);
          if (!hit) return new Response(JSON.stringify({ detail: "offline" }), { status: 503, headers: { "content-type": "application/json" } });
          const h = new Headers(hit.headers);
          h.set("x-lookout-cached", h.get("x-lookout-fetched") || "");
          return new Response(await hit.blob(), { status: hit.status, headers: h });
        },
      ),
    );
    return;
  }

  // Pages: network first, the shell when offline (the app routes itself).
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).catch(() => caches.match("/")));
    return;
  }

  // Built files are fingerprinted: cache first.
  if (url.pathname.startsWith("/assets/")) {
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then(async (res) => { if (res.ok) (await caches.open(SHELL)).put(req, res.clone()); return res; })),
    );
  }
});
