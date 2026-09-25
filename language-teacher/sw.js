/* 랭귀지 스타터 서비스 워커 — 한 번 연 언어는 인터넷이 끊겨도 열리게
   - 화면(HTML)·cloud-config.js : 네트워크 우선(느리면 4초 뒤 저장본) → 배포하면 다음에 열 때 바로 새 화면
   - data-XX.js / stories-XX.js : ?v= 주소 그대로 캐시 우선 + 뒤에서 확인(바뀌었으면 다음에 열 때 새것)
                                   DATA_VER는 tools/stamp-data-ver.mjs 가 파일 내용으로 자동으로 정함
   - 그 밖(아이콘·manifest·Firebase 묶음) : 저장본을 먼저 주고 뒤에서 갱신
   - 다른 사이트(구글 로그인·Firestore·통계)는 건드리지 않음
   비상 정지: 문제가 생기면 이 파일을 "캐시를 모두 지우고 self.registration.unregister()" 하는 내용으로 바꿔 배포 */
const SHELL = 'lt-shell-v2';
const DATA = 'lt-data-v2';
const CONFIG_KEY = new URL('cloud-config.js', self.registration.scope).href;
const CONFIG_FALLBACK = 'window.CLOUD_CONFIG = window.CLOUD_CONFIG || null;';
const SCOPE = self.registration.scope;              // .../language-teacher/
const HTML_KEY = SCOPE;                              // ?lang= 이 붙어도 같은 화면이므로 한 칸에 저장
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(SHELL).then(c => c.add('./').catch(() => { })));   // 아이콘 등은 처음 요청될 때 담는다(첫 방문을 무겁게 하지 않게)
});
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k.startsWith('lt-') && k !== SHELL && k !== DATA) await caches.delete(k);
  await self.clients.claim();
})()));

async function networkFirst(req, key, fallbackBody, waitMs) {
  const cache = await caches.open(SHELL);
  const cached = await cache.match(key || req, { ignoreSearch: true });
  const net = fetch(req, { cache: 'no-cache' }).then(res => {           // no-cache: GitHub Pages의 10분 HTTP 캐시를 건너뛰고 ETag로 확인
    if (res.ok && res.type === 'basic') cache.put(key || req, res.clone());
    return res;
  });
  const timeout = new Promise(r => setTimeout(() => r(null), waitMs || 4000));   // 지하철처럼 느린 망: 4초(설정 파일은 1.5초) 뒤 저장본
  if (!cached) {
    if (!fallbackBody) return net;
    // 설정 파일은 화면을 막으므로, 저장본이 없고 응답도 없으면 '설정 없음'으로 넘어간다
    const fb = () => new Response(fallbackBody, { headers: { 'Content-Type': 'text/javascript; charset=utf-8' } });
    try { return (await Promise.race([net, timeout])) || fb(); } catch (err) { return fb(); }
  }
  try { return (await Promise.race([net, timeout])) || cached; } catch (err) { return cached; }
}
function samePath(a, b) { return new URL(a).pathname === new URL(b).pathname; }
async function dataCacheFirst(req, ev) {
  const cache = await caches.open(DATA);
  const hit = await cache.match(req);                                  // ?v= 까지 정확히 같은 것
  if (hit) {
    // 뒤에서 확인: 버전을 안 올리고 내용만 고쳐도 한 번 열고 나면 새것으로 바뀐다
    ev.waitUntil(fetch(req, { cache: 'no-cache' }).then(res => { if (res.ok && res.type === 'basic') return cache.put(req, res); }).catch(() => { }));
    return hit;
  }
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
  if (/\/cloud-config\.js$/.test(url.pathname)) return e.respondWith(networkFirst(req, CONFIG_KEY, CONFIG_FALLBACK, 1500));
  if (/\/(data|stories)-[a-z]{2}\.js$/.test(url.pathname)) return e.respondWith(dataCacheFirst(req, e));
  if (/\/sw\.js$/.test(url.pathname)) return;
  e.respondWith(staleWhileRevalidate(req));
});
// 첫 방문: 서비스 워커가 켜지기 전에 받은 파일을 캐시에 옮겨 담기(HTTP 캐시에서 오므로 추가 다운로드 거의 없음)
self.addEventListener('message', e => {
  if (!e.data || e.data.type !== 'warm' || !Array.isArray(e.data.urls)) return;
  e.waitUntil((async () => {
    const d = await caches.open(DATA), sh = await caches.open(SHELL);
    await Promise.all(e.data.urls.filter(u => typeof u === 'string' && u.startsWith(SCOPE)).map(async u => {
      const path = new URL(u).pathname;
      if (/\/cloud-config\.js$/.test(path)) { if (!(await sh.match(CONFIG_KEY))) { const r = await fetch(u).catch(() => null); if (r && r.ok) await sh.put(CONFIG_KEY, r); } return; }
      const c = /\/(data|stories)-[a-z]{2}\.js/.test(path) ? d : sh;
      if (!(await c.match(u))) await c.add(u).catch(() => { });
    }));
  })());
});
