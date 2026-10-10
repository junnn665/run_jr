// 東海にゅ〜す：電波がないときでも前回の内容を見られるようにする仕組み
// ・ページとニュースのデータは「まずネットから取り、取れなければ前回保存したもの」を使う
// ・文字のフォントやアイコンは一度取ったものを使い回す
const CACHE = "tokai-news-v1";
const CORE = ["./", "index.html", "news.json", "linear.json", "finance.json",
              "manifest.json", "icon-192.png", "icon-512.png", "apple-touch-icon.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // 自分のサイトのページとデータ：ネット優先、だめなら保存分
  if (url.origin === location.origin) {
    e.respondWith(fromNetworkThenCache(req, url));
    return;
  }

  // Googleフォント：保存分があればそれを使い、裏で新しくする
  if (url.hostname.endsWith("googleapis.com") || url.hostname.endsWith("gstatic.com")) {
    e.respondWith(
      caches.open(CACHE).then(c => c.match(req).then(hit => {
        const net = fetch(req).then(res => { c.put(req, res.clone()); return res; }).catch(() => hit);
        return hit || net;
      }))
    );
  }
});

async function fromNetworkThenCache(req, url) {
  const key = url.origin + url.pathname;   // ?t=… を外して1つにまとめて保存
  try {
    const res = await fetch(req);
    if (res.ok) {
      const c = await caches.open(CACHE);
      await c.put(key, res.clone());
    }
    return res;
  } catch (err) {
    const hit = (await caches.match(key)) ||
                (await caches.match(req, {ignoreSearch: true})) ||
                (req.mode === "navigate" ? await caches.match(new URL("index.html", self.registration.scope).href) : null);
    return hit || Response.error();
  }
}
