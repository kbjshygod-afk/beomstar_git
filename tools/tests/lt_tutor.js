// 🤖 AI 튜터 화면 시험 (Playwright, 서버·키 없이: 중계 함수 응답은 가짜로 바꿔 끼움)
// 사용: NODE_PATH=/opt/node-tools/node_modules node tools/tests/lt_tutor.js [base=http://127.0.0.1:8765]
'use strict';
const { chromium } = require('playwright');
const BASE = (process.argv[2] || 'http://127.0.0.1:8765').replace(/\/$/, '');
const URL = BASE + '/language-teacher/index.html', TUTOR = 'https://tutor.test/t';
let bad = 0; const chk = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ FAIL ') + m); if (!c) bad++; };
const MOCK = () => {
  try { Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: { speak(u) { setTimeout(() => u.onend && u.onend({}), 10); }, cancel() { }, getVoices() { return []; } } }); } catch (e) { }
  HTMLMediaElement.prototype.play = function () { return Promise.resolve(); };
};
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const errors = [];
  // withUrl: 설정 파일에 tutorUrl을 끼워 넣는다 · 파이어베이스 묶음은 막아 로그인 상태를 시험이 정한다
  const newPage = async (withUrl, handler) => {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
    const p = await ctx.newPage(); p.reqs = [];
    p.on('pageerror', e => errors.push(e.message)); p.on('dialog', d => d.accept());
    await p.addInitScript(MOCK);
    await p.route('**/vendor/firebase/**', r => r.abort());
    await p.route('**/cloud-config.js*', async r => { const res = await r.fetch(); let b = await res.text(); if (withUrl) b = b.replace('tutorUrl: null', "tutorUrl: '" + TUTOR + "'"); r.fulfill({ response: res, body: b }); });
    await p.route(TUTOR, async r => {
      const rq = r.request(); p.reqs.push({ method: rq.method(), auth: rq.headers().authorization, body: JSON.parse(rq.postData() || '{}') });
      if (r.request().method() === 'OPTIONS') return r.fulfill({ status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*' } });
      const out = handler ? await handler(p.reqs.length, rq) : { status: 200, json: { reply: '你好!(nǐ hǎo) 안녕하세요', remaining: 29, engine: 'gemini' } };
      r.fulfill({ status: out.status, headers: { 'access-control-allow-origin': '*', 'content-type': 'application/json' }, body: JSON.stringify(out.json), ...(out.delay ? {} : {}) });
    });
    return { ctx, p };
  };
  const until = async (p, fn, arg, ms) => { const end = Date.now() + (ms || 8000); while (Date.now() < end) { if (await p.evaluate(fn, arg)) return true; await p.waitForTimeout(60); } return false; };
  const open = async (p, code, signedIn, lessons) => {
    await p.goto(URL); await p.evaluate(() => localStorage.clear());
    await p.evaluate(c => localStorage.setItem('lang_starter_v1', JSON.stringify({ schema: 4, active: c, settings: { rate: 1, voiceMode: 'natural', dailyGoal: 30 }, seen: { ['welcome_' + c]: '2026-10-01', deqOfferShown: '2026-10-01', micAsk: '2026-10-01', micPrivacy: '2026-10-01', playTrainerHint: '2026-10-01' } })), code);
    await p.reload();
    if (!await until(p, () => typeof CUR !== 'undefined' && CUR && DATA && S.view === 'home', null, 20000)) throw new Error('앱이 열리지 않음');
    await p.evaluate(([n, si]) => { const pr = prog(); ALL.slice(0, n).forEach(l => { pr.completed[l.id] = { score: 8, total: 8, date: todayStr() }; addWordsToSrs(l); }); save(); closeModal(true);
      if (si) CLOUD.user = { uid: 'u1', displayName: '시험', getIdToken: async () => 'tok123' }; go('play'); }, [lessons == null ? 6 : lessons, !!signedIn]);
    await p.waitForTimeout(250);
  };
  const tile = p => p.$('[data-play="tutor"]');
  const ids = p => p.evaluate(() => Array.from(document.querySelectorAll('[data-play]')).map(e => e.dataset.play));
  let ctx, p;

  console.log('=== tutorUrl이 없으면: 놀이 탭에 AI 튜터 타일이 없다(배포 전 안전) ===');
  ({ ctx, p } = await newPage(false)); await open(p, 'zh', true);
  chk(!(await ids(p)).includes('tutor'), '타일 숨김');
  chk(await p.evaluate(() => typeof tutorUrl === 'function' && tutorUrl() === ''), 'tutorUrl() 빈 값'); await ctx.close();

  console.log('=== 설정은 있고 로그인 전: 타일은 보이고 열면 로그인 안내(입력칸 없음) ===');
  ({ ctx, p } = await newPage(true)); await open(p, 'zh', false);
  chk((await ids(p)).includes('tutor'), '타일 보임');
  chk(/구글 로그인 필요/.test(await (await tile(p)).innerText()), '타일에 "구글 로그인 필요"');
  await (await tile(p)).click(); await p.waitForTimeout(300);
  chk(await p.evaluate(() => S.view) === 'tutor', 'tutor 화면 열림');
  chk(!(await p.$('#tuIn')), '로그인 전에는 입력칸이 없다');
  chk(/구글 로그인/.test(await p.evaluate(() => document.getElementById('main').innerText)), '로그인 안내 문구');
  chk(p.reqs.length === 0, '서버 요청 없음'); await ctx.close();

  console.log('=== 로그인 후 대화: 요청 모양·토큰·답 표시·남은 횟수 ===');
  ({ ctx, p } = await newPage(true)); await open(p, 'zh', true, 12);
  await (await tile(p)).click(); await p.waitForTimeout(300);
  chk(!!(await p.$('#tuIn')), '입력칸 보임'); chk((await p.$$('.tu-start')).length === 4, '시작 버튼 4개');
  await (await p.$('.tu-start')).click(); await p.waitForSelector('.tu-row.ai .tu-bub:not(.typing)', { timeout: 5000 });
  const rq = p.reqs[0];
  chk(rq.method === 'POST' && rq.auth === 'Bearer tok123', 'POST + 로그인 토큰');
  chk(rq.body.lang === 'zh' && rq.body.engine === 'gemini' && rq.body.mode === 'chat', '언어 zh · 기본 Gemini · 대화');
  chk(rq.body.level >= 0 && rq.body.level <= 5, '수준 0~5: ' + rq.body.level);
  chk(rq.body.messages.length === 1 && rq.body.messages[0].role === 'user', '글 1개(user)');
  chk(/你好/.test(await p.innerText('.tu-row.ai')), 'AI 답이 보임');
  chk(/오늘 29번 남음/.test(await p.innerText('.lt-sub')), '남은 횟수 표시');
  chk(!(await p.$('.tu-starters')), '대화가 시작되면 시작 버튼은 사라짐');

  console.log('=== 이어 말하기: 기록이 함께 가고, AI를 바꾸면 engine이 바뀐다 ===');
  await p.click('[data-tu-engine="openai"]'); await p.waitForTimeout(100);
  chk(await p.getAttribute('[data-tu-engine="openai"]', 'aria-pressed') === 'true', 'ChatGPT 선택됨');
  chk(/OpenAI/.test(await p.innerText('.lg-note')), '안내문이 고른 AI 이름으로 바뀜');
  await p.fill('#tuIn', '你好吗？'); await p.press('#tuIn', 'Enter'); await p.waitForFunction(() => document.querySelectorAll('.tu-row.ai').length >= 2, null, { timeout: 5000 });
  const r2 = p.reqs[1];
  chk(r2.body.engine === 'openai', '두 번째 요청 engine=openai');
  chk(r2.body.messages.map(m => m.role).join() === 'user,assistant,user', '기록이 user,assistant,user 순으로 간다');
  chk(r2.body.messages[2].text === '你好吗？', '방금 쓴 글이 마지막');
  chk(await p.inputValue('#tuIn') === '', '보낸 뒤 입력칸이 비워짐');

  console.log('=== Shift+Enter는 줄바꿈(보내지 않음) · 빈 글·공백은 안 보냄 ===');
  const n0 = p.reqs.length; await p.fill('#tuIn', '   '); await p.press('#tuIn', 'Enter'); await p.waitForTimeout(150);
  chk(p.reqs.length === n0, '공백만이면 요청 없음');
  await p.fill('#tuIn', 'a'); await p.press('#tuIn', 'Shift+Enter'); await p.waitForTimeout(150);
  chk(p.reqs.length === n0, 'Shift+Enter는 보내지 않음');

  console.log('=== 방식 바꾸기(교정): 시작 문구가 바뀌고 mode=correct로 간다 ===');
  await p.click('[data-tu-mode="correct"]'); await p.waitForTimeout(100);
  chk(await p.getAttribute('[data-tu-mode="correct"]', 'aria-pressed') === 'true', '교정 선택됨');
  await p.fill('#tuIn', '我是韩国人'); await p.click('#tuSend'); await p.waitForFunction(() => document.querySelectorAll('.tu-row.ai').length >= 3, null, { timeout: 5000 });
  chk(p.reqs[2].body.mode === 'correct', 'mode=correct');

  console.log('=== 화면: 가로 넘침 없음 · 단추 44px · 뒤로 가기 ===');
  chk(await p.evaluate(() => document.documentElement.scrollWidth) <= 390, 'scrollWidth ≤ 390');
  const small = await p.evaluate(() => Array.from(document.querySelectorAll('#main button, #main textarea')).filter(b => { const r = b.getBoundingClientRect(); return r.width && (r.height < 44 || r.width < 44); }).map(b => (b.id || b.className || b.tagName) + ':' + Math.round(b.getBoundingClientRect().width) + 'x' + Math.round(b.getBoundingClientRect().height)));
  chk(!small.length, '모든 단추·입력칸 44px 이상' + (small.length ? ' → ' + small.join(',') : ''));
  chk(await p.evaluate(() => document.querySelector('.tu-bar').getBoundingClientRect().bottom <= window.innerHeight + 1), '입력줄이 화면 안에 보임');
  await p.click('#tuBack'); await p.waitForTimeout(200); chk(await p.evaluate(() => S.view) === 'play', '← 로 놀이 탭');
  await (await tile(p)).click(); await p.waitForTimeout(200);
  chk(await p.evaluate(() => S.tutor.msgs.length) >= 6, '다시 들어와도 대화가 남아 있다(메모리)');
  await p.evaluate(() => history.length); await ctx.close();

  console.log('=== 안전: AI 답에 HTML이 있어도 글자로만 그려진다 ===');
  ({ ctx, p } = await newPage(true, async () => ({ status: 200, json: { reply: '<img src=x onerror="window.__xss=1"><script>window.__xss=2<\/script>**굵게**', remaining: 5 } })));
  await open(p, 'en', true); await (await tile(p)).click(); await p.waitForTimeout(200);
  await p.fill('#tuIn', 'hi'); await p.click('#tuSend'); await p.waitForSelector('.tu-row.ai .tu-bub:not(.typing)', { timeout: 5000 }); await p.waitForTimeout(200);
  chk(await p.evaluate(() => window.__xss) === undefined, '스크립트가 실행되지 않음');
  chk(!(await p.$('.tu-bub img, .tu-bub script')), '태그가 요소로 만들어지지 않음');
  chk(/<img src=x/.test(await p.innerText('.tu-row.ai')), '글자 그대로 보임');
  chk(p.reqs[0].body.lang === 'en', '언어 en'); await ctx.close();

  console.log('=== 실패 처리: 429(한도)·500·연결 끊김 → 토스트, 보낸 글은 입력칸으로 돌아오고 기록에서 빠진다 ===');
  for (const [name, h] of [['429', async () => ({ status: 429, json: { error: '오늘 쓸 수 있는 AI 튜터 횟수(30번)를 다 썼어요. 내일 다시 만나요!', remaining: 0 } })], ['500', async () => ({ status: 502, json: { error: 'AI가 지금 답하지 못해요. 잠시 뒤 다시 해 주세요' } })], ['401', async () => ({ status: 401, json: { error: '로그인이 만료됐어요. 다시 로그인해 주세요' } })]]) {
    ({ ctx, p } = await newPage(true, h)); await open(p, 'ja', true); await (await tile(p)).click(); await p.waitForTimeout(200);
    await p.fill('#tuIn', 'こんにちは'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy, null, { timeout: 5000 }); await p.waitForTimeout(200);
    chk(await p.inputValue('#tuIn') === 'こんにちは', name + ': 글이 입력칸으로 돌아옴');
    chk(await p.evaluate(() => S.tutor.msgs.length) === 0, name + ': 기록에 안 남음');
    chk(/🤖/.test(await p.evaluate(() => document.getElementById('toastBox').innerText)), name + ': 토스트');
    if (name === '429') chk(/오늘 0번 남음/.test(await p.innerText('.lt-sub')), '429: 남은 횟수 0');
    await ctx.close();
  }
  ({ ctx, p } = await newPage(true)); await open(p, 'es', true); await (await tile(p)).click();
  await p.unroute(TUTOR); await p.route(TUTOR, r => r.abort('failed'));
  await p.fill('#tuIn', 'hola'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy, null, { timeout: 5000 }); await p.waitForTimeout(200);
  chk(await p.inputValue('#tuIn') === 'hola', '연결 끊김: 글이 돌아옴'); chk(/인터넷/.test(await p.evaluate(() => document.getElementById('toastBox').innerText)), '연결 끊김: 안내'); await ctx.close();

  console.log('=== 중복 전송 막기 · 대체 AI 안내 · 언어를 바꾸면 대화가 새로 시작 ===');
  let release; const gate = new Promise(r => { release = r; });
  ({ ctx, p } = await newPage(true, async () => { await gate; return { status: 200, json: { reply: '응답', remaining: 3, fellBack: true, engine: 'openai' } }; }));
  await open(p, 'fr', true); await (await tile(p)).click(); await p.waitForTimeout(200);
  await p.fill('#tuIn', 'bonjour'); await p.click('#tuSend'); await p.waitForTimeout(150);
  chk(await p.evaluate(() => TUTOR.busy), '답을 기다리는 중');
  chk(await p.$eval('#tuSend', b => b.disabled), '보내기 단추 잠김'); chk(!!(await p.$('.tu-bub.typing')), '"쓰는 중" 표시');
  await p.evaluate(() => tutorSend('두 번째')); await p.waitForTimeout(100);
  chk(p.reqs.length === 1, '기다리는 동안 두 번째 요청은 보내지 않음');
  release(); await p.waitForFunction(() => !TUTOR.busy, null, { timeout: 5000 }); await p.waitForTimeout(200);
  chk(/바빠서 다른 AI/.test(await p.innerText('#tuLog')), '대체 AI 안내 줄');
  chk(!(await p.evaluate(() => S.tutor.msgs.filter(m => m.role === 'note').length === 0)), 'note가 기록에 있음(서버로는 안 보냄)');
  await p.evaluate(() => tutorSend('suite')); await p.waitForFunction(() => !TUTOR.busy, null, { timeout: 5000 });
  chk(p.reqs[1] && p.reqs[1].body.messages.every(m => m.role === 'user' || m.role === 'assistant'), 'note는 서버로 가지 않는다');
  await p.evaluate(() => { activateLanguage('zh'); });
  await until(p, () => CUR && CUR.code === 'zh', null, 8000);
  chk(await p.evaluate(() => tutorState().msgs.length) === 0 && await p.evaluate(() => S.tutor.code) === 'zh', '언어를 바꾸면 새 대화'); await ctx.close();

  console.log('=== 개인정보 안내: tutorUrl이 있을 때만 AI 튜터 문구가 보인다 ===');
  for (const withUrl of [false, true]) {
    const c2 = await browser.newContext({ viewport: { width: 390, height: 844 } }), pg = await c2.newPage();
    await pg.route('**/cloud-config.js*', async r => { const res = await r.fetch(); let b = await res.text(); if (withUrl) b = b.replace('tutorUrl: null', "tutorUrl: '" + TUTOR + "'"); r.fulfill({ response: res, body: b }); });
    await pg.goto(BASE + '/privacy.html'); await pg.waitForTimeout(300);
    const vis = await pg.evaluate(() => Array.from(document.querySelectorAll('.tutor-only')).map(e => getComputedStyle(e).display !== 'none'));
    chk(vis.length >= 3 && vis.every(v => v === withUrl), (withUrl ? 'tutorUrl 있음' : 'tutorUrl 없음') + ': .tutor-only ' + vis.length + '곳 모두 ' + (withUrl ? '보임' : '숨김'));
    if (withUrl) chk(/저장하지 않아요/.test(await pg.innerText('body')) && /OpenAI/.test(await pg.innerText('body')), '저장 안 함·OpenAI 문구');
    await c2.close();
  }

  chk(!errors.length, 'pageerror 없음' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(bad ? 'RESULT: ' + bad + '건 실패' : 'RESULT: ALL PASS'); process.exit(bad ? 1 : 0);
})().catch(e => { console.log('CRASH', e); process.exit(2); });
