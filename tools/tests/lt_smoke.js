// 기본 점검 시험 — 5개 언어에서 모든 탭·놀이 타일을 열어 보고 오류·가로 넘침·빈 화면이 없는지 본다.
// (예전 회귀 시험 묶음은 저장소 밖 임시 폴더에만 있어 사라졌다. 이 시험이 그 빈자리를 메우는 최소한의 안전망이다.)
// 사용: NODE_PATH=/opt/node-tools/node_modules node tools/tests/lt_smoke.js [base=http://127.0.0.1:8765]
'use strict';
const { chromium } = require('playwright');
const BASE = (process.argv[2] || 'http://127.0.0.1:8765').replace(/\/$/, '');
const URL = BASE + '/language-teacher/index.html';
let bad = 0; const chk = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ FAIL ') + m); if (!c) bad++; };
const MOCK = () => {
  try { Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: { speak(u) { setTimeout(() => u.onend && u.onend({}), 10); }, cancel() { }, getVoices() { return []; } } }); } catch (e) { }
  class FakeSR { start() { setTimeout(() => { if (this.onend) this.onend(); }, 30); } stop() { } abort() { } }
  window.SpeechRecognition = FakeSR; window.webkitSpeechRecognition = FakeSR;
  HTMLMediaElement.prototype.play = function () { return Promise.resolve(); };
};
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  for (const code of ['zh', 'en', 'ja', 'es', 'fr']) {
    console.log('=== ' + code + ' ===');
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
    const p = await ctx.newPage(), errors = [];
    p.on('pageerror', e => errors.push(e.message)); p.on('dialog', d => d.accept());
    await p.addInitScript(MOCK); await p.clock.setFixedTime(new Date('2026-10-05T12:30:00'));
    await p.route('**/vendor/firebase/**', r => r.abort());
    await p.goto(URL); await p.evaluate(() => localStorage.clear());
    await p.evaluate(c => localStorage.setItem('lang_starter_v1', JSON.stringify({ schema: 4, active: c, settings: { rate: 1, voiceMode: 'natural', dailyGoal: 30 }, seen: { ['welcome_' + c]: '2026-10-01', deqOfferShown: '2026-10-01', micAsk: '2026-10-01', micPrivacy: '2026-10-01', playTrainerHint: '2026-10-01', in_puzzle: '2026-10-01', in_rush: '2026-10-01', in_feed: '2026-10-01' } })), code);
    await p.reload();
    await p.waitForFunction(() => typeof CUR !== 'undefined' && CUR && DATA && S.view === 'home', null, { timeout: 20000 });
    await p.evaluate(() => { const pr = prog(); ALL.slice(0, 14).forEach(l => { pr.completed[l.id] = { score: 8, total: 8, date: todayStr() }; addWordsToSrs(l); }); save(); closeModal(true); go('home'); });
    await p.waitForTimeout(300);
    const look = async (what) => {
      await p.waitForTimeout(250);
      const r = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, len: document.getElementById('main').innerText.trim().length, view: S.view }));
      chk(r.sw <= 390 && r.len > 5, what + ' — 가로 넘침 없음·빈 화면 아님 (view=' + r.view + ', ' + r.len + '자)');
    };
    for (const v of ['home', 'review', 'play', 'story', 'history', 'settings']) { await p.evaluate(v => { closeModal(true); go(v); }, v); await look('탭 ' + v); }
    await p.evaluate(() => go('play')); await p.waitForTimeout(250);
    const tiles = await p.evaluate(() => Array.from(document.querySelectorAll('[data-play]')).map(e => e.dataset.play));
    chk(tiles.length >= 8, '놀이 타일 ' + tiles.length + '개: ' + tiles.join(','));
    chk(tiles.includes('tutor'), 'AI 튜터 타일이 있다(내 키 방식 — 로그인·서버 없이)');
    for (const t of tiles) {
      await p.evaluate(() => { closeModal(true); go('play'); }); await p.waitForTimeout(150);
      await p.evaluate(id => { const t = playTile(id); if (t && tileOpen(t)) t.open(); }, t); await look('놀이 ' + t);
      await p.evaluate(() => { closeModal(true); try { handleBack(); } catch (e) { } });
    }
    await p.evaluate(() => { closeModal(true); go('play'); }); await p.waitForTimeout(150);
    await p.evaluate(() => { try { handleBack(); } catch (e) { } });
    chk(!errors.length, 'pageerror 없음' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
    await ctx.close();
  }
  await browser.close();
  console.log(bad ? 'RESULT: ' + bad + '건 실패' : 'RESULT: ALL PASS'); process.exit(bad ? 1 : 0);
})().catch(e => { console.log('CRASH', e); process.exit(2); });
