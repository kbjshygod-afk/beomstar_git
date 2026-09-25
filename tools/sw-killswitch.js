/* 서비스 워커 비상 정지 — 이 파일을 language-teacher/sw.js 자리에 그대로 복사해 배포하세요.
   모든 사용자의 브라우저에서 랭귀지 스타터 캐시를 지우고 서비스 워커를 해제한 뒤, 열려 있는 화면을 새로 불러옵니다.
   (문제가 풀리면 원래 sw.js로 되돌려 배포하면 다시 켜집니다) */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k.startsWith('lt-')) await caches.delete(k);
  await self.registration.unregister();
  const wins = await self.clients.matchAll({ type: 'window' });
  wins.forEach(c => { try { c.navigate(c.url); } catch (err) { } });
})()));
