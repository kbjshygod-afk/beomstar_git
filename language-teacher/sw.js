/* 랭귀지 스타터 서비스 워커 — 한 번 연 언어는 인터넷이 끊겨도 열리게
   - 앱 화면(범위 주소 또는 index.html, ?lang= 등은 무시) : 네트워크 우선. 저장본이 있으면 2초 안에 정상 응답이 없거나
     서버 오류(5xx·404 등)일 때 저장본 → 배포하면 다음에 열 때 바로 새 화면. 저장은 text/html 응답만, HTML_KEY 한 칸에만
     그 밖의 탐색(아이콘·manifest·설정 파일을 주소창으로 연 경우 등)은 건드리지 않음
   - cloud-config.js : 저장본을 먼저 주고 뒤에서 갱신(설정을 바꾸면 그다음에 열 때 반영).
                       저장본이 없을 때만 네트워크를 1.5초 기다리고, 그래도 없으면 '설정 없음'
   - data-XX.js / stories-XX.js : ?v= 주소 그대로 캐시 우선 + 뒤에서 확인(바뀌었으면 다음에 열 때 새것)
                                   새 버전을 못 받으면(오류 응답·오프라인) 저장된 옛 버전
                                   '다시 시도'가 붙이는 &r= 는 캐시 칸 이름에서 뺌(요청은 그대로 보냄)
                                   DATA_VER는 tools/stamp-data-ver.mjs 가 파일 내용으로 자동으로 정함
   - 그 밖(아이콘·manifest·Firebase 묶음) : 저장본을 먼저 주고 뒤에서 갱신
                                   Firebase 묶음의 ?v=FB_VER 는 tools/firebase/build.mjs 가 내용 해시로 적음
   - audio/{언어}/index.json(녹음 목록) : 네트워크 우선, 못 받으면 저장본 / audio/{언어}/{id}.mp3 : 캐시 우선(AUDIO)
                                   ?v= 는 목소리가 바뀔 때만 바뀐다(앱이 index.json의 목소리로 정함) — 옛 버전 칸은 정리
   - 다른 사이트(구글 로그인·Firestore·통계)는 건드리지 않음
   캐시 이름
   - DATA('lt-data')는 바꾸지 않는다. 항목이 ?v= 로 나뉘어 이름을 올릴 필요가 없고, 바꾸면 모든 언어의 오프라인 자료가 사라진다
   - 화면 쪽을 비워야 할 때만 SHELL('lt-shell-vN')의 번호를 올린다. 옛 SHELL은 activate에서 지우고,
     앱 화면·cloud-config.js는 install에서 다시 담고, 아이콘·Firebase 묶음은 다시 요청될 때 담긴다
   - 예전 이름의 데이터 캐시(lt-data-v2 등)는 activate에서 DATA로 옮겨 담은 뒤 지운다
   비상 정지: tools/sw-killswitch.js 를 이 파일 자리에 복사해 배포(캐시를 모두 지우고 서비스 워커 해제) */
const SHELL = 'lt-shell-v2';
const DATA = 'lt-data';
const AUDIO = 'lt-audio';   // 녹음된 자연 음성(들은 문장만 담긴다)
const SCOPE = self.registration.scope;              // .../language-teacher/
const SCOPE_PATH = new URL(SCOPE).pathname;
const HTML_KEY = SCOPE;                              // ?lang= 이 붙어도 같은 화면이므로 한 칸에 저장
const CONFIG_KEY = new URL('cloud-config.js', SCOPE).href;
const CONFIG_FALLBACK = 'window.CLOUD_CONFIG = window.CLOUD_CONFIG || null; window.SITE_CONTACT = window.SITE_CONTACT || null;';
const HTML_WAIT = 2000;     // 저장본이 있을 때 새 화면을 기다리는 시간(느린 망·응답 없는 망)
const CONFIG_WAIT = 1500;   // 설정 저장본이 없을 때 기다리는 시간(설정 파일이 화면을 막으므로 짧게)

const isAppPage = u => { const p = new URL(u).pathname; return p === SCOPE_PATH || p === SCOPE_PATH + 'index.html'; };
const isHtml = res => /^text\/html/i.test(res.headers.get('content-type') || '');
const isData = path => /\/(data|stories)-[a-z]{2}\.js$/.test(path);
const isConfig = path => /\/cloud-config\.js$/.test(path);
const isAudioIndex = path => /\/audio\/[a-z]{2}\/index\.json$/.test(path);
const isClip = path => /\/audio\/[a-z]{2}\/[0-9a-f]{12}\.mp3$/.test(path);
function dataKey(u) { const x = new URL(u); if (x.searchParams.has('r')) x.searchParams.delete('r'); return x.href; }
function samePath(a, b) { return new URL(a).pathname === new URL(b).pathname; }
async function dropOtherVersions(cache, key) {
  for (const k of await cache.keys()) if (samePath(k.url, key) && k.url !== key) await cache.delete(k);
}
// 앱 화면은 HTML_KEY 한 칸만: 예전 버전(또는 옛 워커가 받은 warm)이 담은 'index.html'·'index.html?lang=…' 칸과
// HTML이 아닌 것이 담긴 앱 화면 칸을 정리한다
async function tidyShell(sh) {
  for (const k of await sh.keys()) if (k.url !== HTML_KEY && isAppPage(k.url)) await sh.delete(k);
  const h = await sh.match(HTML_KEY);
  if (h && !isHtml(h)) await sh.delete(HTML_KEY);
}

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil((async () => {
    // 첫 설치: 아무것도 받지 않는다. 페이지가 보내는 warm(방금 받은 주소 → HTTP 캐시)으로 담아서,
    // 허브의 ?lang= 주소로 온 첫 방문이 HTML·설정을 한 번 더 받지 않게 한다
    if (!self.registration.active) return;
    // 업데이트: 새 앱 화면을 담고, 설정이 없으면(SHELL 이름을 올린 경우) 설정도 다시 담는다
    const sh = await caches.open(SHELL);
    try { const r = await fetch(HTML_KEY, { cache: 'no-cache' }); if (r.ok && isHtml(r)) await sh.put(HTML_KEY, r); } catch (err) { }
    if (!(await sh.match(CONFIG_KEY))) {
      try { const r = await fetch(CONFIG_KEY, { cache: 'no-cache' }); if (r.ok) await sh.put(CONFIG_KEY, r); } catch (err) { }
    }
  })());
});
self.addEventListener('activate', e => e.waitUntil((async () => {
  const data = await caches.open(DATA);
  for (const k of await caches.keys()) {
    if (!k.startsWith('lt-') || k === SHELL || k === DATA || k === AUDIO) continue;
    if (k.startsWith('lt-data')) {   // 예전 이름의 오프라인 자료는 버리지 않고 옮겨 담는다
      try {
        const old = await caches.open(k);
        for (const r of await old.keys()) {
          if (await data.match(r)) continue;
          const res = await old.match(r);
          if (res) await data.put(r, res);
        }
      } catch (err) { }
    }
    await caches.delete(k);
  }
  try { await tidyShell(await caches.open(SHELL)); } catch (err) { }
  await self.clients.claim();
})()));

async function appPage(req, ev) {
  const cache = await caches.open(SHELL);
  const cached = await cache.match(HTML_KEY);
  let saving = null;
  const net = fetch(req, { cache: 'no-cache' }).then(res => {   // no-cache: GitHub Pages의 10분 HTTP 캐시를 건너뛰고 ETag로 확인
    if (res.ok && res.type === 'basic' && isHtml(res)) saving = cache.put(HTML_KEY, res.clone()).catch(() => { });
    return res;
  });
  ev.waitUntil(net.then(() => saving, () => { }));   // 저장본을 먼저 보여 줘도, 새 화면은 끝까지 받아 담는다
  if (!cached) return net;                    // 저장본이 없으면 받은 그대로(오류 화면이라도)
  // 정상 응답과 주소 이동(리디렉션)만 쓰고, 서버 오류·없음(404)·응답 없음은 저장본으로
  const usable = net.then(res => (res.ok || res.type === 'opaqueredirect' || (res.status >= 300 && res.status < 400)) ? res : Promise.reject(res));
  const timeout = new Promise(r => setTimeout(() => r(null), HTML_WAIT));
  try { return (await Promise.race([usable, timeout])) || cached; } catch (err) { return cached; }
}
async function configFirst(req, ev) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(CONFIG_KEY);
  let saving = null;
  const net = fetch(req, { cache: 'no-cache' }).then(res => {
    if (res.ok && res.type === 'basic') saving = cache.put(CONFIG_KEY, res.clone()).catch(() => { });
    return res;
  });
  ev.waitUntil(net.then(() => saving, () => { }));
  if (hit) return hit;                        // 저장본을 먼저 주고 뒤에서 갱신 → 다음에 열 때 반영
  const fb = () => new Response(CONFIG_FALLBACK, { headers: { 'Content-Type': 'text/javascript; charset=utf-8' } });
  const timeout = new Promise(r => setTimeout(() => r(null), CONFIG_WAIT));
  try { const res = await Promise.race([net, timeout]); return res && res.ok ? res : fb(); } catch (err) { return fb(); }
}
async function dataCacheFirst(req, ev) {
  const cache = await caches.open(DATA);
  const key = dataKey(req.url);                                          // ?v= 까지 같은 것(&r= 는 뺌)
  const hit = await cache.match(key);
  if (hit) {
    // 뒤에서 확인: 버전을 안 올리고 내용만 고쳐도 한 번 열고 나면 새것으로 바뀐다
    ev.waitUntil(fetch(req, { cache: 'no-cache' }).then(res => { if (res.ok && res.type === 'basic') return cache.put(key, res); }).catch(() => { }));
    return hit;
  }
  let res = null;
  try { res = await fetch(req); } catch (err) { res = null; }
  if (res && res.ok) {
    await cache.put(key, res.clone());
    await dropOtherVersions(cache, key);                                 // 옛 버전 정리
    return res;
  }
  // 새 버전을 못 받았으면(서버 오류·오프라인) 옛 버전이라도
  return (await cache.match(key, { ignoreSearch: true })) || res || Response.error();
}
async function audioIndex(req) {
  const cache = await caches.open(AUDIO);
  try {
    const res = await fetch(req, { cache: 'no-cache' });
    if (res.ok && res.type === 'basic') await cache.put(req.url.split('?')[0], res.clone());
    else if (res.status === 404) await cache.delete(req.url.split('?')[0]);
    return res;
  } catch (err) { return (await cache.match(req.url.split('?')[0])) || Response.error(); }
}
async function clipFirst(req) {
  const cache = await caches.open(AUDIO);
  const hit = await cache.match(req.url);
  if (hit) return hit;
  let res = null;
  try { res = await fetch(req); } catch (err) { res = null; }
  if (res && res.status === 200 && res.type === 'basic') { await cache.put(req.url, res.clone()); await dropOtherVersions(cache, req.url); return res; }
  return res || (await cache.match(req.url, { ignoreSearch: true })) || Response.error();
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
  if (req.mode === 'navigate') {
    if (isAppPage(req.url)) e.respondWith(appPage(req, e));
    return;                                                              // 앱 화면이 아닌 탐색은 네트워크에 맡김
  }
  if (isConfig(url.pathname)) return e.respondWith(configFirst(req, e));
  if (isData(url.pathname)) return e.respondWith(dataCacheFirst(req, e));
  if (isAudioIndex(url.pathname)) return e.respondWith(audioIndex(req));
  if (isClip(url.pathname)) { if (req.headers.has('range')) return; return e.respondWith(clipFirst(req)); }
  if (/\/sw\.js$/.test(url.pathname)) return;
  e.respondWith(staleWhileRevalidate(req));
});
// 첫 방문: 서비스 워커가 켜지기 전에 받은 파일을 캐시에 옮겨 담기(HTTP 캐시에서 오므로 추가 다운로드 거의 없음)
// 앱 화면은 페이지가 처음 들어온 주소(?lang= 포함)를 보내 오고, HTML_KEY 한 칸에만 담는다
self.addEventListener('message', e => {
  if (!e.data || e.data.type !== 'warm' || !Array.isArray(e.data.urls)) return;
  e.waitUntil((async () => {
    const d = await caches.open(DATA), sh = await caches.open(SHELL);
    await Promise.all(e.data.urls.filter(u => typeof u === 'string' && u.startsWith(SCOPE)).map(async u => {
      try {
        const path = new URL(u).pathname;
        if (isAppPage(u)) {
          if (!(await sh.match(HTML_KEY))) { const r = await fetch(u).catch(() => null); if (r && r.ok && isHtml(r)) await sh.put(HTML_KEY, r); }
          return;
        }
        if (isConfig(path)) { if (!(await sh.match(CONFIG_KEY))) { const r = await fetch(u).catch(() => null); if (r && r.ok) await sh.put(CONFIG_KEY, r); } return; }
        if (isData(path)) {
          const key = dataKey(u);
          if (!(await d.match(key))) { const r = await fetch(u).catch(() => null); if (r && r.ok) { await d.put(key, r); await dropOtherVersions(d, key); } }
          return;
        }
        if (!(await sh.match(u))) await sh.add(u).catch(() => { });
      } catch (err) { }
    }));
    await tidyShell(sh).catch(() => { });
  })());
});
