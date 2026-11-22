// Shows invite notifications ("Pat wants to play") and opens the table when one is tapped, and opens the app with no
// internet. Pages still come straight from the server whenever it answers within a few seconds, so new versions arrive
// as before; with no internet (or none good enough) the app opens from the copy src/offline.ts keeps on the phone.
const APP = "bridge-app"; // the page and its files (offline.ts fills it)
const ENGINE = "bridge-engine"; // the offline engine: Pyodide and the game
const WAIT = 4000; // how long the server gets to answer before the phone's copy is used

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

function slow(ms) {
  return new Promise((_, reject) => setTimeout(() => reject(new Error("slow")), ms));
}

// the server's answer when it comes in time (and kept for next time), otherwise the copy here
async function networkFirst(name, request, key) {
  const cache = await caches.open(name);
  const net = fetch(request).then((res) => {
    if (res.ok) cache.put(key || request, res.clone()).catch(() => {});
    return res;
  });
  try {
    return await Promise.race([net, slow(WAIT)]);
  } catch {
    return (await cache.match(key || request)) || net;
  }
}

// files that never change at the same address: the copy here, or fetched once and kept
async function cacheFirst(name, request) {
  const cache = await caches.open(name);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  if (res.ok) cache.put(request, res.clone()).catch(() => {});
  return res;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  const path = url.pathname;
  if (path.startsWith("/offline/pyodide/") || path === "/offline/engine.zip") return event.respondWith(cacheFirst(ENGINE, req));
  if (path.startsWith("/assets/")) return event.respondWith(cacheFirst(APP, req));
  if (req.mode === "navigate") return event.respondWith(networkFirst(APP, req, "/"));
  // the server's answers stay live, but for the lists the table menu shows
  if (path.startsWith("/api/") || path.startsWith("/ws/") || path.startsWith("/mcp") || path === "/sw.js") {
    if (path !== "/api/conventions" && path !== "/api/lessons") return;
  }
  event.respondWith(networkFirst(APP, req));
});

self.addEventListener("push", (event) => {
  let msg = { title: "Bridge", body: "", url: "/" }; // the server sends the site's name
  try {
    msg = { ...msg, ...event.data.json() };
  } catch {
    /* an empty push: show the plain title */
  }
  event.waitUntil(
    self.registration.showNotification(msg.title, { body: msg.body, icon: "/icon-192.png", badge: "/icon-192.png", data: { url: msg.url }, tag: "invite" }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if ("navigate" in w) return w.navigate(url).then((c) => c && c.focus());
      }
      return self.clients.openWindow(url);
    }),
  );
});
