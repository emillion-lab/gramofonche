/* Грамофонче — service worker
   SHELL: index.html + манифест + икона, за да тръгва без мрежа.
   AUDIO: свалените mp3-ки. Пълни се от страницата (caches.open), тук само се сервира.
   Range: ако отговорът е четим (CORS), режем 206. Ако е opaque, връщаме целия —
   Chrome го приема и буферира локално, така че превъртането пак работи. */

const SHELL = "gramo-shell-v1";
const AUDIO = "gramo-audio-v1";
const SHELL_FILES = ["./", "index.html", "manifest.webmanifest", "icon.svg"];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(SHELL)
      .then(c => Promise.all(SHELL_FILES.map(f => c.add(f).catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== SHELL && k !== AUDIO).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

const isAudio = url => /\.mp3(\?|$)/i.test(url);

async function fromAudioCache(req) {
  const c = await caches.open(AUDIO);
  const hit = await c.match(req.url, { ignoreVary: true });
  if (!hit) return null;

  const range = req.headers.get("range");
  if (!range || hit.type === "opaque" || hit.status === 0) return hit;

  try {
    const buf = await hit.arrayBuffer();
    const size = buf.byteLength;
    const m = /bytes=(\d*)-(\d*)/.exec(range);
    let start = m && m[1] ? parseInt(m[1], 10) : 0;
    let end = m && m[2] ? parseInt(m[2], 10) : size - 1;
    if (start >= size) return new Response(null, { status: 416 });
    if (end >= size) end = size - 1;
    const body = buf.slice(start, end + 1);
    return new Response(body, {
      status: 206,
      statusText: "Partial Content",
      headers: {
        "Content-Type": hit.headers.get("Content-Type") || "audio/mpeg",
        "Content-Range": "bytes " + start + "-" + end + "/" + size,
        "Content-Length": String(body.byteLength),
        "Accept-Ranges": "bytes"
      }
    });
  } catch (err) {
    return hit;
  }
}

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;

  if (isAudio(req.url)) {
    e.respondWith((async () => {
      const cached = await fromAudioCache(req);
      if (cached) return cached;
      return fetch(req);
    })());
    return;
  }

  let url;
  try { url = new URL(req.url); } catch (err) { return; }
  if (url.origin !== self.location.origin) return;

  e.respondWith((async () => {
    const c = await caches.open(SHELL);
    const hit = await c.match(req, { ignoreSearch: true });
    const net = fetch(req)
      .then(r => { if (r && r.ok && r.type === "basic") c.put(req, r.clone()); return r; })
      .catch(() => null);
    if (hit) return hit;                       // cache-first: тръгва мигновено и без мрежа
    const r = await net;
    if (r) return r;
    if (req.mode === "navigate") {
      const fallback = await c.match("index.html");
      if (fallback) return fallback;
    }
    return Response.error();
  })());
});

self.addEventListener("message", e => {
  if (e.data === "skipWaiting") self.skipWaiting();
});
