/* 랭귀지 스타터 서비스 워커 — 한 번 연 언어는 인터넷이 끊겨도 열리게
   - 화면(HTML)·cloud-config.js : 네트워크 우선(느리면 4초 뒤 저장본) → 배포하면 다음에 열 때 바로 새 화면
   - data-XX.js / stories-XX.js : ?v= 주소 그대로 캐시 우선 → 내용을 고치면 index.html의 DATA_VER만 올리면 새로 받음
   - 그 밖(아이콘·manifest·Firebase 묶음) : 저장본을 먼저 주고 뒤에서 갱신
   - 다른 사이트(구글 로그인·Firestore·통계)는 건드리지 않음
   비상 정지: 문제가 생기면 이 파일을 "캐시를 모두 지우고 self.registration.unregister()" 하는 내용으로 바꿔 배포 */
const SHELL = 'lt-shell-v1';
const DATA = 'lt-data-v1';
const SCOPE = self.registration.scope;              // .../language-teacher/
const HTML_KEY = SCOPE;                              // ?lang= 이 붙어도 같은 화면이므로 한 칸에 저장
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(['./', './manifest.webmanifest', './icons/icon-192.png', './icons/icon-512.png', './icons/favicon-32.png']).catch(() => { })));
});
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k.startsWith('lt-') && k !== SHELL && k !== DATA) await caches.delete(k);
  await self.clients.claim();
})()));

async function networkFirst(req, key) {
  const cache = await caches.open(SHELL);
  const cached = await cache.match(key || req);
  const net = fetch(req, { cache: 'no-cache' }).then(res => {           // no-cache: GitHub Pages의 10분 HTTP 캐시를 건너뛰고 ETag로 확인
    if (res.ok && res.type === 'basic') cache.put(key || req, res.clone());
    return res;
  });
  if (!cached) return net;
  const timeout = new Promise(r => setTimeout(() => r(null), 4000));   // 지하철처럼 느린 망: 4초 뒤 저장본
  try { return (await Promise.race([net, timeout])) || cached; } catch (err) { return cached; }
}
function samePath(a, b) { return new URL(a).pathname === new URL(b).pathname; }
async function dataCacheFirst(req) {
  const cache = await caches.open(DATA);
  const hit = await cache.match(req);                                  // ?v= 까지 정확히 같은 것
  if (hit) return hit;
  try {
    const res = await fetch(req);
    if (res.ok) {
      await cache.put(req, res.clone());
      for (const k of await cache.keys()) if (samePath(k.url, req.url) && k.url !== req.url) await cache.delete(k);   // 옛 버전 정리
    }
    return res;
  } catch (err) {
    return (await cache.match(req, { ignoreSearch: true })) || Response.error();   // 새 버전을 못 받았으면 옛 버전이라도
  }
}
async function staleWhileRevalidate(req) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(req);
  const net = fetch(req).then(res => { if (res.ok && res.type === 'basic') cache.put(req, res.clone()); return res; }).catch(() => hit || Response.error());
  return hit || net;
}
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin || !req.url.startsWith(SCOPE)) return;
  if (req.mode === 'navigate') return e.respondWith(networkFirst(req, HTML_KEY));
  if (/\/cloud-config\.js$/.test(url.pathname)) return e.respondWith(networkFirst(req, new URL('cloud-config.js', SCOPE).href));
  if (/\/(data|stories)-[a-z]{2}\.js$/.test(url.pathname)) return e.respondWith(dataCacheFirst(req));
  if (/\/sw\.js$/.test(url.pathname)) return;
  e.respondWith(staleWhileRevalidate(req));
});
// 첫 방문: 서비스 워커가 켜지기 전에 받은 파일을 캐시에 옮겨 담기(HTTP 캐시에서 오므로 추가 다운로드 거의 없음)
self.addEventListener('message', e => {
  if (!e.data || e.data.type !== 'warm' || !Array.isArray(e.data.urls)) return;
  e.waitUntil((async () => {
    const d = await caches.open(DATA), sh = await caches.open(SHELL);
    await Promise.all(e.data.urls.filter(u => typeof u === 'string' && u.startsWith(SCOPE)).map(async u => {
      const isData = /\/(data|stories)-[a-z]{2}\.js/.test(new URL(u).pathname);
      const c = isData ? d : sh;
      if (!(await c.match(u))) await c.add(u).catch(() => { });
    }));
  })());
});
