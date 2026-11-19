// 🤖 AI 튜터 화면 시험 (Playwright, 서버·키 없이: 구글(Gemini)·중계 함수 응답은 가짜로 바꿔 끼움)
// 앞부분 = 내 키 방식(기본), 뒷부분 = 중계 방식(tutorUrl이 있을 때)
// 사용: NODE_PATH=/opt/node-tools/node_modules node tools/tests/lt_tutor.js [base=http://127.0.0.1:8765]
'use strict';
const { chromium } = require('playwright');
const BASE = (process.argv[2] || 'http://127.0.0.1:8765').replace(/\/$/, '');
const URL = BASE + '/language-teacher/index.html', TUTOR = 'https://tutor.test/t';
const KEY = 'AIzaTESTkey_0123456789abcdefghijklmnopq', GOOD = t => ({ status: 200, json: { candidates: [{ content: { parts: [{ text: t }] }, finishReason: 'STOP' }] } });
const BADKEY = { status: 400, json: { error: { code: 400, message: 'API key not valid. Please pass a valid API key.', status: 'INVALID_ARGUMENT', details: [{ reason: 'API_KEY_INVALID' }] } } };
let bad = 0; const chk = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ FAIL ') + m); if (!c) bad++; };
const MOCK = () => {
  try { Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: { speak(u) { setTimeout(() => u.onend && u.onend({}), 10); }, cancel() { }, getVoices() { return []; } } }); } catch (e) { }
  HTMLMediaElement.prototype.play = function () { return Promise.resolve(); };
  // 가짜 음성 인식: 만든 것을 window.__srs에 모아 두고, 시험이 onresult/onend를 직접 부른다. stop()은 곧 끝 신호를 준다(__srNoEnd면 안 줌).
  window.__srs = [];
  window.SpeechRecognition = class { constructor() { window.__srs.push(this); } start() { this.started = true; } stop() { this.stopped = true; if (!window.__srNoEnd) setTimeout(() => this.onend && this.onend(), 30); } abort() { this.aborted = true; } };
};
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const errors = [];
  // withUrl: 설정 파일에 tutorUrl을 끼워 넣는다 · 파이어베이스 묶음은 막아 로그인 상태를 시험이 정한다
  // ghandler(n, {model, body, list}) : 구글(Gemini) 쪽 가짜 응답. 없으면 목록 200 · 답 '你好'
  const newPage = async (withUrl, handler, ghandler) => {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
    const p = await ctx.newPage(); p.reqs = []; p.greqs = [];
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
    await p.route('https://generativelanguage.googleapis.com/**', async r => {
      const rq = r.request(), u = new (require('url').URL)(rq.url()), cors = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*' };
      if (rq.method() === 'OPTIONS') return r.fulfill({ status: 204, headers: cors });
      const m = /models\/([^:/]+):generateContent/.exec(u.pathname), list = !m;
      const g = { method: rq.method(), url: rq.url(), key: rq.headers()['x-goog-api-key'], model: m ? decodeURIComponent(m[1]) : '', list, body: list ? null : JSON.parse(rq.postData() || '{}') };
      p.greqs.push(g);
      const out = ghandler ? await ghandler(p.greqs.length, g) : (list ? { status: 200, json: { models: [] } } : GOOD('你好!(nǐ hǎo) 안녕하세요'));
      r.fulfill({ status: out.status, headers: { ...cors, 'content-type': 'application/json' }, body: JSON.stringify(out.json) });
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

  const toast = p => p.evaluate(() => document.getElementById('toastBox').innerText);
  const small = p => p.evaluate(() => Array.from(document.querySelectorAll('#main button, #main textarea, #main input, #main a.btn')).filter(b => { const r = b.getBoundingClientRect(); return r.width && (r.height < 44 || r.width < 44); }).map(b => (b.id || b.className || b.tagName) + ':' + Math.round(b.getBoundingClientRect().width) + 'x' + Math.round(b.getBoundingClientRect().height)));
  const withKey = p => p.evaluate(k => { localStorage.setItem('lang_starter_tutor_key', k); }, KEY);
  const gens = p => p.greqs.filter(g => !g.list);

  console.log('=== 내 키 방식 · 키가 없을 때: 타일은 보이고, 열면 키 넣는 화면(입력칸 없음, 요청 없음) ===');
  ({ ctx, p } = await newPage(false)); await open(p, 'zh', false);
  chk(await p.evaluate(() => tutorUrl() === ''), 'tutorUrl() 빈 값(중계 꺼짐)');
  chk((await ids(p)).includes('tutor'), '타일 보임(로그인 없이)');
  chk(/무료 키로 켜기/.test(await (await tile(p)).innerText()), '타일에 "무료 키로 켜기"');
  await (await tile(p)).click(); await p.waitForTimeout(300);
  chk(await p.evaluate(() => S.view) === 'tutor' && !!(await p.$('#tuKey')) && !(await p.$('#tuIn')), '키 넣는 화면(대화 입력칸 없음)');
  chk(await p.getAttribute('#tuKey', 'type') === 'password', '키 칸은 가려짐(password)');
  const link = await p.$('a.tu-link');
  chk(await link.getAttribute('href') === 'https://aistudio.google.com/apikey' && /noopener/.test(await link.getAttribute('rel')) && await link.getAttribute('target') === '_blank', '구글 AI 스튜디오 링크(새 창·noopener)');
  chk(/이 기기에만/.test(await p.innerText('.lg-note')), '키 보관 안내');
  chk(!(await p.$('#tuKeyDel')), '키가 없으면 지우기 단추 없음');
  let sm = await small(p); chk(!sm.length, '키 화면 단추·입력칸 44px 이상' + (sm.length ? ' → ' + sm.join(',') : ''));
  chk(await p.evaluate(() => document.documentElement.scrollWidth) <= 390, '키 화면 가로 넘침 없음');
  chk(p.greqs.length === 0 && p.reqs.length === 0, '아직 아무 요청도 없음');

  console.log('=== 키 저장: 모양이 틀리면 요청 없이 거절 · 구글이 거절하면 저장 안 함 · 맞으면 저장하고 대화 화면 ===');
  await p.fill('#tuKey', '짧은 키'); await p.click('#tuKeySave'); await p.waitForTimeout(150);
  chk(/키 모양이 아니에요/.test(await p.innerText('#tuKeyMsg')) && p.greqs.length === 0, '모양이 틀린 키: 안내, 요청 없음');
  await ctx.close();
  ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? BADKEY : GOOD('x'))); await open(p, 'zh', false); await (await tile(p)).click(); await p.waitForTimeout(200);
  await p.fill('#tuKey', KEY); await p.click('#tuKeySave'); await p.waitForFunction(() => !TUTOR.checking, null, { timeout: 5000 }); await p.waitForTimeout(150);
  chk(/키가 맞지 않아요/.test(await p.innerText('#tuKeyMsg')), '구글이 거절한 키: 안내');
  chk(await p.evaluate(() => localStorage.getItem('lang_starter_tutor_key')) === null && !(await p.$('#tuIn')), '저장하지 않고 키 화면에 머묾');
  chk(await p.$eval('#tuKeySave', b => !b.disabled), '저장 단추 다시 누를 수 있음'); await ctx.close();
  console.log('=== 키 확인 응답이 끝내 오지 않으면 15초 뒤 풀리고 다시 누를 수 있다 ===');
  ({ ctx, p } = await newPage(false, null, async (n, g) => g.list && n === 1 ? new Promise(() => { }) : { status: 200, json: {} }));
  await open(p, 'zh', false); await (await tile(p)).click(); await p.waitForTimeout(200);
  await p.fill('#tuKey', KEY); await p.click('#tuKeySave'); await p.waitForTimeout(300);
  chk(await p.evaluate(() => TUTOR.checking) && await p.$eval('#tuKeySave', b => b.disabled), '확인 중(단추 잠김)');
  chk(await until(p, () => !TUTOR.checking, null, 18000), '15초 뒤 확인 중 상태가 풀림');
  chk(/너무 오래/.test(await p.innerText('#tuKeyMsg')) && await p.$eval('#tuKeySave', b => !b.disabled), '안내가 나오고 단추를 다시 누를 수 있음');
  await p.click('#tuKeySave'); chk(!!(await p.waitForSelector('#tuIn', { timeout: 5000 }).catch(() => null)), '다시 누르면 저장되고 대화 화면'); await ctx.close();
  ({ ctx, p } = await newPage(false)); await open(p, 'zh', false);
  const stalled = await p.evaluate(async k => { const real = window.fetch; window.fetch = (u, o) => Promise.resolve({ ok: false, status: 400, json: () => new Promise((_, rej) => o.signal.addEventListener('abort', () => rej(new Error('aborted')))) });
    const t0 = Date.now(); try { const r = await tutorKeyCheck(k); return { r, ms: Date.now() - t0 }; } finally { window.fetch = real; } }, KEY);
  chk(!stalled.r.ok && /너무 오래/.test(stalled.r.msg) && stalled.ms < 17000, '오류 본문을 읽다 멈춰도 15초 뒤 끝남(' + Math.round(stalled.ms / 1000) + '초)'); await ctx.close();
  ({ ctx, p } = await newPage(false)); await open(p, 'zh', false, 12); await (await tile(p)).click(); await p.waitForTimeout(200);
  await p.fill('#tuKey', '  ' + KEY + '  '); await p.press('#tuKey', 'Enter'); await p.waitForSelector('#tuIn', { timeout: 5000 });
  const kc = p.greqs[0];
  chk(kc.list && kc.method === 'GET' && kc.key === KEY && !kc.url.includes(KEY), '키 확인: 목록 요청, 키는 헤더로만(주소에 없음)');
  chk(await p.evaluate(() => localStorage.getItem('lang_starter_tutor_key')) === KEY, '앞뒤 빈칸을 떼고 이 기기에 저장');
  chk(!(await p.evaluate(k => (localStorage.getItem('lang_starter_v1') || '').includes(k), KEY)), '학습 기록(클라우드로 가는 칸)에는 키가 없다');
  chk(!(await p.$('[data-tu-engine]')) && (await p.$$('[data-tu-mode]')).length === 2 && !!(await p.$('#tuKeyBtn')), 'AI 고르기 없음 · 방식 2개 · 🔑 키 단추');
  chk(/Google\(Gemini\)로 바로/.test(await p.innerText('.lg-note')), '안내문: 구글로 바로 보냄');

  console.log('=== 내 키로 대화: 구글로 바로, 지시문·기록 모양, 답 표시 ===');
  await (await p.$('.tu-start')).click(); await p.waitForSelector('.tu-row.ai .tu-bub:not(.typing)', { timeout: 5000 });
  let g1 = gens(p)[0];
  chk(g1.method === 'POST' && g1.model === 'gemini-flash-latest' && g1.key === KEY && !g1.url.includes(KEY), 'POST · 첫 모델 · 키는 헤더로만');
  chk(/중국어/.test(g1.body.systemInstruction.parts[0].text) && /병음/.test(g1.body.systemInstruction.parts[0].text) && /대화 상대/.test(g1.body.systemInstruction.parts[0].text), '지시문: 중국어·병음·대화 상대');
  chk(g1.body.contents.length === 1 && g1.body.contents[0].role === 'user' && g1.body.generationConfig.thinkingConfig.thinkingBudget === 0, '글 1개(user) · 생각 끄기');
  chk(/你好/.test(await p.innerText('.tu-row.ai')), 'AI 답이 보임');
  chk(p.reqs.length === 0, '중계 서버로는 아무것도 가지 않음');
  await p.click('[data-tu-mode="correct"]'); await p.fill('#tuIn', '我是韩国人'); await p.press('#tuIn', 'Enter'); await p.waitForFunction(() => !TUTOR.busy && document.querySelectorAll('.tu-row.ai .tu-bub:not(.typing)').length >= 2, null, { timeout: 5000 });
  g1 = gens(p)[1];
  chk(g1.body.contents.map(c => c.role).join() === 'user,model,user' && g1.body.contents[2].parts[0].text === '我是韩国人', '기록이 user,model,user 순으로 간다');
  chk(/교정 선생님/.test(g1.body.systemInstruction.parts[0].text), '교정 방식의 지시문');
  sm = await small(p); chk(!sm.length, '대화 화면 단추 44px 이상' + (sm.length ? ' → ' + sm.join(',') : ''));
  chk(await p.evaluate(() => document.documentElement.scrollWidth) <= 390, '대화 화면 가로 넘침 없음');

  console.log('=== 🔑 키: 끝 4자리만 보이고, 돌아가기·지우기 ===');
  await p.click('#tuKeyBtn'); await p.waitForTimeout(150);
  chk(new RegExp('····' + KEY.slice(-4)).test(await p.innerText('.tu-key')) && !(await p.innerText('#main')).includes(KEY), '끝 4자리만 보임(전체 키는 화면에 없음)');
  await p.click('#tuKeyDone'); await p.waitForTimeout(150); chk(!!(await p.$('#tuIn')) && await p.evaluate(() => S.tutor.msgs.length) === 4, '돌아가면 대화가 그대로');
  await p.click('#tuKeyBtn'); await p.waitForTimeout(100); await p.evaluate(() => handleBack()); await p.waitForTimeout(150);
  chk(await p.evaluate(() => S.view) === 'tutor' && !!(await p.$('#tuIn')), '키 화면에서 휴대폰 뒤로 가기: 튜터를 나가지 않고 대화로');
  await p.evaluate(() => handleBack()); await p.waitForTimeout(150); chk(await p.evaluate(() => S.view) === 'play', '대화 화면에서 뒤로 가기: 놀이 탭으로');
  await (await tile(p)).click(); await p.waitForTimeout(200);
  await p.click('#tuKeyBtn'); await p.click('#tuKeyDel'); await p.waitForTimeout(200);
  chk(await p.evaluate(() => localStorage.getItem('lang_starter_tutor_key')) === null && !!(await p.$('#tuKey')) && !(await p.$('#tuIn')), '지우면 이 기기에서 사라지고 키 화면으로');
  chk(await p.evaluate(() => S.tutor.msgs.length) === 0, '대화도 비움'); await ctx.close();

  console.log('=== 모델 이름이 없으면(404) 다음 모델 · 생각 끄기를 안 받으면(400) 설정 없이 다시 · 생각에 길이를 다 쓰면 넉넉히 다시 ===');
  ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: {} } : g.model === 'gemini-flash-latest' ? { status: 404, json: { error: { code: 404, status: 'NOT_FOUND' } } } : GOOD('둘째 모델')));
  await open(p, 'en', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
  await p.fill('#tuIn', 'hi'); await p.click('#tuSend'); await p.waitForSelector('.tu-row.ai .tu-bub:not(.typing)', { timeout: 5000 });
  chk(gens(p).map(g => g.model).join() === 'gemini-flash-latest,gemini-flash-lite-latest' && /둘째 모델/.test(await p.innerText('.tu-row.ai')), '404 → 다음 모델이 답함');
  await p.fill('#tuIn', 'again'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy && document.querySelectorAll('.tu-row.ai .tu-bub:not(.typing)').length >= 2, null, { timeout: 5000 });
  chk(gens(p).length === 3 && gens(p)[2].model === 'gemini-flash-lite-latest', '없는 모델은 건너뛰고 다음부터 되는 모델을 바로 씀'); await ctx.close();
  ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: {} } : g.body.generationConfig.thinkingConfig ? { status: 400, json: { error: { code: 400, message: 'Thinking budget is not supported', status: 'INVALID_ARGUMENT' } } } : GOOD('설정 없이 답')));
  await open(p, 'ja', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
  await p.fill('#tuIn', 'こんにちは'); await p.click('#tuSend'); await p.waitForSelector('.tu-row.ai .tu-bub:not(.typing)', { timeout: 5000 });
  chk(gens(p).length === 3 && gens(p)[1].body.generationConfig.thinkingConfig.thinkingLevel === 'minimal' && !gens(p)[2].body.generationConfig.thinkingConfig && gens(p)[2].body.generationConfig.maxOutputTokens >= 2000 && /설정 없이 답/.test(await p.innerText('.tu-row.ai')), '400(생각 끄기 거절) → 설정 없이 넉넉한 길이로 다시');
  chk(/히라가나/.test(gens(p)[0].body.systemInstruction.parts[0].text), '일본어 지시문: 히라가나'); await ctx.close();
  ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: {} } : g.body.generationConfig.thinkingConfig ? { status: 200, json: { candidates: [{ content: { parts: [] }, finishReason: 'MAX_TOKENS' }] } } : { status: 200, json: { candidates: [{ content: { parts: [{ text: '속생각', thought: true }, { text: '진짜 답' }] } }] } }));
  await open(p, 'es', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
  await p.fill('#tuIn', 'hola'); await p.click('#tuSend'); await p.waitForSelector('.tu-row.ai .tu-bub:not(.typing)', { timeout: 5000 });
  chk(gens(p).length === 2 && (await p.innerText('.tu-row.ai')).trim() === '진짜 답', '빈 답(MAX_TOKENS) → 다시 · 생각 부분은 보여 주지 않음'); await ctx.close();

  console.log('=== 모델 고르기: 이 키로 쓸 수 있는 목록에서 고르고, 한 모델의 한도가 차면(429) 다음 모델이 답한다 ===');
  {
    const M = n => ({ name: 'models/' + n, supportedGenerationMethods: ['generateContent'] });
    const LIST = { models: [M('gemini-3.5-flash-lite'), M('gemini-3.8-flash'), M('gemini-3.6-flash'), M('gemini-flash-latest'), M('gemini-flash-lite-latest'), M('gemini-3.1-flash-lite'), M('gemini-4.0-flash-preview-09-2026'),
      M('gemini-3.8-flash-image'), M('gemini-3.8-pro'), M('gemini-3.8-flash-tts'), { name: 'models/gemini-embedding-001', supportedGenerationMethods: ['embedContent'] }, { name: 'models/gemini-9.9-flash', supportedGenerationMethods: ['embedContent'] }] };
    const order = await (async () => { ({ ctx, p } = await newPage(false)); await open(p, 'zh', false); const o = await p.evaluate(l => tutorRankModels(l.models.filter(m => m.supportedGenerationMethods.includes('generateContent')).map(m => m.name.replace('models/', ''))), LIST); await ctx.close(); return o; })();
    chk(order.join() === 'gemini-flash-latest,gemini-3.8-flash,gemini-3.6-flash,gemini-flash-lite-latest,gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-4.0-flash-preview-09-2026', '순서: 일반(최신 별칭·높은 버전) → 가벼운 모델 → 미리보기 · 그림·음성·pro는 뺌 → ' + order.join());
    let lim = new Set(['gemini-flash-latest', 'gemini-3.8-flash']);
    ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: LIST } : lim.has(g.model) ? { status: 429, json: { error: { code: 429, status: 'RESOURCE_EXHAUSTED' } } } : GOOD('답: ' + g.model)));
    await open(p, 'zh', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
    await p.fill('#tuIn', '你好'); await p.click('#tuSend'); await p.waitForSelector('.tu-row.ai .tu-bub:not(.typing)', { timeout: 5000 });
    chk(gens(p).map(g => g.model).join() === 'gemini-flash-latest,gemini-3.8-flash,gemini-3.6-flash' && /답: gemini-3\.6-flash/.test(await p.innerText('.tu-row.ai')), '앞의 두 모델이 한도(429)여도 세 번째 모델이 답함');
    chk(p.greqs.filter(g => g.list).length === 1 && /pageSize=1000/.test(p.greqs.find(g => g.list).url), '모델 목록은 한 번만 물어봄');
    await p.fill('#tuIn', '再见'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy && document.querySelectorAll('.tu-row.ai .tu-bub:not(.typing)').length >= 2, null, { timeout: 5000 });
    chk(gens(p).length === 4 && gens(p)[3].model === 'gemini-3.6-flash' && p.greqs.filter(g => g.list).length === 1, '한도가 찬 모델은 잠깐 건너뛰고 바로 되는 모델로(요청 낭비 없음)');
    lim = new Set(order); await p.evaluate(() => { TUTOR.skip = {}; });
    await p.fill('#tuIn', '谢谢'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy, null, { timeout: 8000 }); await p.waitForTimeout(200);
    chk(/무료 한도/.test(await toast(p)) && await p.inputValue('#tuIn') === '谢谢' && gens(p).length === 4 + order.length, '모든 모델이 한도면: 한도 안내, 글은 돌아옴');
    lim = new Set(); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy && S.tutor.msgs.length >= 6, null, { timeout: 5000 });
    chk(/답: gemini-flash-latest/.test(await p.evaluate(() => S.tutor.msgs[S.tutor.msgs.length - 1].text)), '모두 쉬는 중이면 처음 모델부터 다시 물어봄(한도가 풀리면 바로 됨)'); await ctx.close();

    console.log('=== 권한 없는 모델(403)은 다음 모델로 · 모두 403이면 키 화면 · 길이에 잘린 답은 보여 주지 않고 다시 ===');
    ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: LIST } : g.model === 'gemini-flash-latest' ? { status: 403, json: { error: { code: 403, status: 'PERMISSION_DENIED' } } } : GOOD('둘째가 답')));
    await open(p, 'en', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
    await p.fill('#tuIn', 'hi'); await p.click('#tuSend'); await p.waitForSelector('.tu-row.ai .tu-bub:not(.typing)', { timeout: 5000 });
    chk(/둘째가 답/.test(await p.innerText('.tu-row.ai')) && gens(p).length === 2, '첫 모델이 403이어도 다음 모델이 답함'); await ctx.close();
    ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: LIST } : { status: 403, json: { error: { code: 403, status: 'PERMISSION_DENIED' } } }));
    await open(p, 'en', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
    await p.fill('#tuIn', 'hi'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy, null, { timeout: 8000 }); await p.waitForTimeout(200);
    chk(/키가 맞지 않거나 막혀/.test(await toast(p)) && !!(await p.$('#tuKey')), '모든 모델이 403이면: 키 안내와 키 화면'); await ctx.close();
    ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: LIST } : g.body.generationConfig.thinkingConfig ? { status: 200, json: { candidates: [{ content: { parts: [{ text: '중간에 끊긴 답…' }] }, finishReason: 'MAX_TOKENS' }] } } : GOOD('끝까지 쓴 답')));
    await open(p, 'ja', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
    await p.fill('#tuIn', 'こんにちは'); await p.click('#tuSend'); await p.waitForSelector('.tu-row.ai .tu-bub:not(.typing)', { timeout: 5000 });
    chk((await p.innerText('.tu-row.ai')).trim() === '끝까지 쓴 답' && gens(p).length === 2 && gens(p)[1].body.generationConfig.maxOutputTokens >= 8000, '잘린 답(MAX_TOKENS)은 버리고 넉넉한 길이로 다시 받아 보여 줌'); await ctx.close();
    console.log('=== 교차 검수 반영: 목록이 멈춰도 답을 받는다 · 403/5xx 모델도 쉬게 한다 · 한 모델만 403이면 키 화면으로 안 간다 · 잘림 뒤에도 빠른 설정을 다시 쓴다 ===');
    ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? (/pageSize=1000/.test(g.url) ? new Promise(() => { }) : { status: 200, json: {} }) : GOOD('목록 없이 답')));
    await open(p, 'zh', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
    const tl = Date.now(); await p.fill('#tuIn', '你好'); await p.click('#tuSend');
    chk(!!(await p.waitForSelector('.tu-row.ai .tu-bub:not(.typing)', { timeout: 12000 }).catch(() => null)) && /목록 없이 답/.test(await p.innerText('.tu-row.ai')), '모델 목록 요청이 멈춰도 약 6초 뒤 알려진 모델로 답을 받음(' + Math.round((Date.now() - tl) / 1000) + '초)');
    chk(gens(p)[0].model === 'gemini-flash-latest' && await p.evaluate(() => TUTOR.models === null), '알려진 이름을 쓰고, 목록은 다음에 다시 물어봄'); await ctx.close();
    for (const st of [403, 503]) {
      ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: LIST } : g.model === 'gemini-flash-latest' ? { status: st, json: { error: { code: st } } } : GOOD('둘째')));
      await open(p, 'en', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
      await p.fill('#tuIn', 'one'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy && S.tutor.msgs.length >= 2, null, { timeout: 5000 });
      await p.fill('#tuIn', 'two'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy && S.tutor.msgs.length >= 4, null, { timeout: 5000 });
      chk(gens(p).map(g => g.model).join() === 'gemini-flash-latest,gemini-3.8-flash,gemini-3.8-flash', st + ': 실패한 모델은 다음 글에서 건너뜀(같은 실패를 되풀이하지 않음)'); await ctx.close();
    }
    ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: LIST } : g.model === 'gemini-4.0-flash-preview-09-2026' ? { status: 403, json: { error: { code: 403 } } } : { status: 404, json: { error: { code: 404 } } }));
    await open(p, 'en', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
    await p.fill('#tuIn', 'hi'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy, null, { timeout: 8000 }); await p.waitForTimeout(200);
    chk(!(await p.$('#tuKey')) && /답하지 못해요 \(404\)/.test(await toast(p)) && await p.inputValue('#tuIn') === 'hi', '마지막 모델만 403(나머지 404): 키 화면으로 가지 않고 오류 안내'); await ctx.close();
    let longOnce = true;
    ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: LIST } : (g.body.generationConfig.thinkingConfig && longOnce) ? { status: 200, json: { candidates: [{ content: { parts: [{ text: '끊긴…' }] }, finishReason: 'MAX_TOKENS' }] } } : GOOD('답')));
    await open(p, 'fr', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
    await p.fill('#tuIn', 'un'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy && S.tutor.msgs.length >= 2, null, { timeout: 5000 }); longOnce = false;
    await p.fill('#tuIn', 'deux'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy && S.tutor.msgs.length >= 4, null, { timeout: 5000 });
    chk(gens(p).length === 3 && !gens(p)[1].body.generationConfig.thinkingConfig && gens(p)[2].body.generationConfig.thinkingConfig.thinkingBudget === 0, '한 번 잘려 넉넉하게 받은 뒤에도 다음 글은 다시 빠른 설정부터'); await ctx.close();
    ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: LIST } : { status: 200, json: { candidates: [{ content: { parts: [{ text: '아주 긴 답의 앞부분' }] }, finishReason: 'MAX_TOKENS' }] } }));
    await open(p, 'es', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
    await p.fill('#tuIn', 'hola'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy && S.tutor.msgs.length >= 2, null, { timeout: 5000 });
    chk(/아주 긴 답의 앞부분\n…\(답이 너무 길어 여기까지만 보여요\)/.test(await p.evaluate(() => S.tutor.msgs[1].text)) && gens(p).length === 2 && await p.evaluate(() => Object.keys(TUTOR.think).length === 0), '넉넉한 길이로도 잘리면: 끊겼다고 표시하고, 그 설정을 기억하지 않음'); await ctx.close();
  }

  console.log('=== 🎤 누르고 말하기: 누르는 동안 듣고, 떼면 들린 말을 바로 보낸다 (음성 인식은 가짜) ===');
  {
    const sr = (p, fn, arg) => p.evaluate(fn, arg);
    const last = p => p.evaluate(() => { const r = window.__srs[window.__srs.length - 1]; return r ? { lang: r.lang, continuous: r.continuous, interim: r.interimResults, started: r.started, stopped: r.stopped, aborted: r.aborted, n: window.__srs.length } : null; });
    const emit = (p, list) => p.evaluate(l => { const r = window.__srs[window.__srs.length - 1]; r.onresult({ resultIndex: 0, results: l.map(([t, f]) => Object.assign([{ transcript: t }], { isFinal: !!f })) }); }, list);
    const hold = async p => { const b = await p.$('#tuMic'); const box = await b.boundingBox(); await p.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await p.mouse.down(); await p.waitForTimeout(80); };
    const body = g => g.body.contents[g.body.contents.length - 1].parts[0].text;
    ({ ctx, p } = await newPage(false)); await open(p, 'zh', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
    chk(!!(await p.$('#tuMic')) && (await p.innerText('#tuMicLang')).trim() === '中' && await p.$eval('#tuHeard', e => e.hidden), '마이크 단추와 언어 단추가 있고, 듣는 중 표시는 숨어 있음');
    sm = await small(p); chk(!sm.length, '마이크 단추 포함 44px 이상' + (sm.length ? ' → ' + sm.join(',') : ''));
    chk(await p.evaluate(() => document.documentElement.scrollWidth) <= 390 && /음성 인식으로 보내질 수/.test(await p.innerText('.lg-note')), '가로 넘침 없음 · 음성 인식 안내 문구');
    await p.fill('#tuIn', '쓰던 글'); await hold(p);
    let st = await last(p);
    chk(st && st.started && st.lang === 'zh-CN' && st.continuous && st.interim, '누르면 듣기 시작(중국어 · 이어 듣기)');
    chk(await p.$eval('#tuMic', b => b.classList.contains('on') && b.getAttribute('aria-pressed') === 'true') && /듣고 있어요/.test(await p.innerText('#tuHeard')), '듣는 중 표시');
    await emit(p, [['你', false]]); chk((await p.innerText('#tuHeard')).trim() === '你', '들리는 대로 화면에 보임');
    await emit(p, [['你好', true], ['你好吗', true]]);   // 안드로이드 크롬: 앞 결과를 포함한 글을 다시 준다
    await p.waitForTimeout(400); chk(gens(p).length === 0, '누르고 있는 동안에는 보내지 않음');
    await p.mouse.up(); await p.waitForFunction(() => !TUTOR.busy && S.tutor.msgs.length >= 2, null, { timeout: 5000 });
    chk((await last(p)).stopped && gens(p).length === 1 && body(gens(p)[0]) === '你好吗', '떼면 바로 보냄 · 겹친 결과는 긴 쪽만("你好吗")');
    chk(/你好/.test(await p.innerText('.tu-row.ai')) && await p.inputValue('#tuIn') === '쓰던 글' && await p.$eval('#tuHeard', e => e.hidden), 'AI가 답함 · 쓰던 글은 입력칸에 그대로 · 표시 닫힘');

    await p.fill('#tuIn', ''); const n0 = gens(p).length;
    await hold(p); await p.mouse.up(); await p.waitForTimeout(300);
    chk(gens(p).length === n0 && /누르고 있는 동안/.test(await toast(p)) && (await last(p)).aborted, '톡 누르기만 하면: 보내지 않고 쓰는 법 안내');

    await p.click('#tuMicLang'); await p.waitForTimeout(100);
    chk((await p.innerText('#tuMicLang')).trim() === '한' && /한국어/.test(await p.getAttribute('#tuMicLang', 'aria-label')), '언어 단추: 한국어로 바뀜');
    await hold(p); st = await last(p); chk(st.lang === 'ko-KR', '한국어로 듣기');
    await emit(p, [['중국어로 고맙다는', true]]); await p.waitForTimeout(350);
    await sr(p, () => { const r = window.__srs[window.__srs.length - 1]; r.onend(); });   // 조용해서 브라우저가 스스로 끝냄 — 아직 누르고 있다
    await p.waitForTimeout(500); const n1 = (await last(p)).n;
    await sr(p, () => { const r = window.__srs[window.__srs.length - 1]; r.onend(); }); await p.waitForTimeout(100);
    chk((await last(p)).n === n1 + 1 && (await last(p)).started, '누르고 있는데 인식이 스스로 끝나면 이어서 다시 듣는다');
    await emit(p, [['말이 뭐예요', false]]);
    await p.mouse.up(); await p.waitForFunction(g => !TUTOR.busy && S.tutor.msgs.length >= g, 4, { timeout: 5000 });
    chk(body(gens(p)[gens(p).length - 1]) === '중국어로 고맙다는 말이 뭐예요', '나눠 들린 말을 이어 붙여 보냄(끝 결과가 없으면 마지막 중간 결과)');
    // 교차 검수 반영: 누르고 있는 동안에는 어떤 경우에도 보내지 않는다 · 같은 말을 두 번 해도 지우지 않는다 · 영어는 띄어서 잇는다
    await p.click('#tuMicLang'); await p.waitForTimeout(100); await p.evaluate(() => activateLanguage('en')); await until(p, () => CUR && CUR.code === 'en', null, 8000); await p.evaluate(() => tutorOpen('play')); await p.waitForTimeout(200);
    const g0 = gens(p).length; await hold(p); await emit(p, [['no', true], ['no', true]]); await p.waitForTimeout(450);
    await sr(p, () => window.__srs[window.__srs.length - 1].onend()); await p.waitForTimeout(60);
    await emit(p, [['thank you', true]]); await sr(p, () => window.__srs[window.__srs.length - 1].onend());   // 다시 켠 인식이 0.4초 안에 끝남 — 더 이어 듣지 않는다
    await p.waitForTimeout(400);
    chk(gens(p).length === g0 && await p.evaluate(() => TUTOR_MIC.held && !TUTOR_MIC.rec) && /no no thank you/.test(await p.innerText('#tuHeard')), '인식이 더 이어지지 않아도 누르고 있는 동안에는 보내지 않음');
    await p.mouse.up(); await p.waitForFunction(() => !TUTOR.busy && S.tutor.msgs.length >= 2, null, { timeout: 5000 });
    chk(body(gens(p)[gens(p).length - 1]) === 'no no thank you', '손을 떼면 보냄 · 같은 말 두 번("no no")은 그대로 · 영어는 띄어서 이음');
    await sr(p, () => { window.__srNoEnd = true; }); await hold(p); await emit(p, [['wait', false]]); await p.waitForTimeout(350); await p.mouse.up(); await p.waitForTimeout(100);
    chk(await p.$eval('#tuMic', b => b.disabled), '알아듣는 동안에는 마이크 단추 잠김(눌러도 반응 없는 상태를 만들지 않음)');
    await p.waitForFunction(() => !TUTOR.busy && S.tutor.msgs.length >= 4, null, { timeout: 6000 }); chk(await p.$eval('#tuMic', b => !b.disabled), '끝나면 다시 누를 수 있음');
    await ctx.close();

    console.log('=== 🎤 끝 신호가 안 오는 브라우저 · 권한 거절 · 화면을 떠남 · 답을 기다리는 중 · 음성 인식이 없는 브라우저 ===');
    ({ ctx, p } = await newPage(false)); await open(p, 'en', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
    await sr(p, () => { window.__srNoEnd = true; });
    await hold(p); await emit(p, [['hello there', false]]); await p.waitForTimeout(350); await p.mouse.up();
    chk(/알아듣는 중|hello there/.test(await p.innerText('#tuHeard')), '떼면 알아듣는 중 표시');
    await p.waitForFunction(() => !TUTOR.busy && S.tutor.msgs.length >= 2, null, { timeout: 6000 });
    chk(body(gens(p)[0]) === 'hello there' && (await last(p)).aborted, '끝 신호가 없어도 1.5초 뒤 들린 만큼으로 보냄');
    await sr(p, () => { window.__srNoEnd = false; });
    await hold(p); await p.waitForTimeout(350); await sr(p, () => { const r = window.__srs[window.__srs.length - 1]; r.onerror({ error: 'not-allowed' }); r.onend(); }); await p.waitForTimeout(200);
    chk(/마이크|허용|브라우저/.test(await toast(p)) && gens(p).length === 1 && await p.$eval('#tuHeard', e => e.hidden), '마이크 권한 거절: 안내하고 보내지 않음'); await p.mouse.up();
    await hold(p); await emit(p, [['do not send', true]]); await p.evaluate(() => go('play')); await p.mouse.up(); await p.waitForTimeout(400);
    chk(gens(p).length === 1 && (await last(p)).aborted && await p.evaluate(() => !TUTOR_MIC.held && !TUTOR_MIC.rec), '말하는 중에 화면을 떠나면: 끊고 보내지 않음');
    await ctx.close();
    let rel2; const g9 = new Promise(r => { rel2 = r; });
    ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: {} } : (await g9, GOOD('ok'))));
    await open(p, 'en', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
    await p.fill('#tuIn', 'hi'); await p.click('#tuSend'); await p.waitForTimeout(150);
    chk(await p.$eval('#tuMic', b => b.disabled), '답을 기다리는 중에는 마이크 단추 잠김'); rel2(); await ctx.close();
    ({ ctx, p } = await newPage(false)); await p.addInitScript(() => { window.SpeechRecognition = undefined; window.webkitSpeechRecognition = undefined; });
    await open(p, 'en', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
    chk(!(await p.$('#tuMic')) && !(await p.$('#tuMicLang')) && !!(await p.$('#tuIn')) && !/음성 인식/.test(await p.innerText('.lg-note')), '음성 인식이 없는 브라우저: 마이크 단추 없이 글로만'); await ctx.close();
  }

  console.log('=== 내 키 방식 실패 처리: 한도(429)·서버 오류·빈 답·연결 끊김 → 토스트, 글은 입력칸으로 · 키 오류면 키 화면으로 ===');
  for (const [name, out, re] of [['429', { status: 429, json: { error: { code: 429, status: 'RESOURCE_EXHAUSTED' } } }, /무료 한도/], ['503', { status: 503, json: { error: { code: 503 } } }, /바빠요/], ['빈 답', { status: 200, json: { promptFeedback: { blockReason: 'SAFETY' } } }, /답하지 못해요/]]) {
    ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: {} } : out)); await open(p, 'fr', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
    await p.fill('#tuIn', 'bonjour'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy, null, { timeout: 5000 }); await p.waitForTimeout(200);
    chk(re.test(await toast(p)), name + ': 안내 토스트'); chk(await p.inputValue('#tuIn') === 'bonjour' && await p.evaluate(() => S.tutor.msgs.length) === 0, name + ': 글이 돌아오고 기록에 안 남음');
    if (name === '429') chk(gens(p).length === 4 && new Set(gens(p).map(g => g.model)).size === 4, '429: 알려진 모델 4개를 한 번씩 써 본 뒤 한도 안내');
    await ctx.close();
  }
  ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: {} } : BADKEY)); await open(p, 'zh', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
  await p.fill('#tuIn', '你好'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy, null, { timeout: 5000 }); await p.waitForTimeout(200);
  chk(/키가 맞지 않거나/.test(await toast(p)) && !!(await p.$('#tuKey')), '키 오류: 안내하고 키 화면으로');
  chk(await p.evaluate(() => S.tutor.draft) === '你好' && gens(p).length === 1, '쓴 글은 남겨 둠 · 한 번만 시도');
  await p.click('#tuKeyDone'); await p.waitForTimeout(150); chk(await p.inputValue('#tuIn') === '你好', '돌아가면 입력칸에 그대로'); await ctx.close();
  ({ ctx, p } = await newPage(false)); await open(p, 'zh', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
  await p.unroute('https://generativelanguage.googleapis.com/**'); await p.route('https://generativelanguage.googleapis.com/**', r => r.abort('failed'));
  await p.fill('#tuIn', '你好'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy, null, { timeout: 5000 }); await p.waitForTimeout(200);
  chk(/인터넷/.test(await toast(p)) && await p.inputValue('#tuIn') === '你好', '연결 끊김: 안내, 글이 돌아옴'); await ctx.close();

  console.log('=== 기다리는 동안 새로 쓴 글은 실패해도 남는다 · 언어를 바꾸면 진행 중인 요청을 끊고 새 화면이 잠기지 않는다 ===');
  { let rel; const g8 = new Promise(r => { rel = r; });
    ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: {} } : (await g8, { status: 503, json: { error: { code: 503 } } })));
    await open(p, 'fr', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
    await p.fill('#tuIn', 'bonjour'); await p.click('#tuSend'); await p.waitForTimeout(150);
    await p.fill('#tuIn', 'ça va ?'); rel(); await p.waitForFunction(() => !TUTOR.busy, null, { timeout: 5000 }); await p.waitForTimeout(200);
    chk(await p.inputValue('#tuIn') === 'bonjour\nça va ?', '실패한 글과 새로 쓴 글이 둘 다 입력칸에 남음'); await ctx.close(); }
  ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: {} } : new Promise(() => { })));
  await open(p, 'en', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
  await p.fill('#tuIn', 'hello'); await p.click('#tuSend'); await p.waitForTimeout(150);
  chk(await p.evaluate(() => TUTOR.busy), '답을 기다리는 중');
  await p.evaluate(() => activateLanguage('ja')); await until(p, () => CUR && CUR.code === 'ja', null, 8000); await p.evaluate(() => tutorOpen('play'));
  chk(await until(p, () => !TUTOR.busy && !document.querySelector('.tu-bub.typing') && document.getElementById('tuSend') && !document.getElementById('tuSend').disabled, null, 3000), '새 언어 화면: 쓰는 중 표시 없고 보내기 가능(바로 풀림)');
  chk(await p.evaluate(() => S.tutor.code === 'ja' && S.tutor.msgs.length === 0), '새 언어는 빈 대화'); await ctx.close();

  console.log('=== 내 키 방식 안전: 답에 HTML이 있어도 글자로만 · 로그인해도 화면이 바뀌지 않음 · 기록 지우기에 키 포함 ===');
  ({ ctx, p } = await newPage(false, null, async (n, g) => g.list ? { status: 200, json: {} } : GOOD('<img src=x onerror="window.__xss=1"><script>window.__xss=2<\/script>')));
  await open(p, 'en', false); await withKey(p); await (await tile(p)).click(); await p.waitForTimeout(200);
  await p.fill('#tuIn', 'hi'); await p.click('#tuSend'); await p.waitForSelector('.tu-row.ai .tu-bub:not(.typing)', { timeout: 5000 }); await p.waitForTimeout(200);
  chk(await p.evaluate(() => window.__xss) === undefined && !(await p.$('.tu-bub img, .tu-bub script')) && /<img src=x/.test(await p.innerText('.tu-row.ai')), '태그가 실행·생성되지 않고 글자로 보임');
  chk(/TUTOR_KEY_LS\]\.forEach/.test(await p.evaluate(() => cloudLogout.toString())), '로그아웃하며 기기 기록을 지울 때 키도 지운다'); await ctx.close();

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
  await p.fill('#tuIn', '你好吗？'); await p.press('#tuIn', 'Enter'); await p.waitForFunction(() => !TUTOR.busy && document.querySelectorAll('.tu-row.ai .tu-bub:not(.typing)').length >= 2, null, { timeout: 5000 });
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
  await p.fill('#tuIn', '我是韩国人'); await p.click('#tuSend'); await p.waitForFunction(() => !TUTOR.busy && document.querySelectorAll('.tu-row.ai .tu-bub:not(.typing)').length >= 3, null, { timeout: 5000 });
  chk(p.reqs[2].body.mode === 'correct', 'mode=correct');

  console.log('=== 화면: 가로 넘침 없음 · 단추 44px · 뒤로 가기 ===');
  chk(await p.evaluate(() => document.documentElement.scrollWidth) <= 390, 'scrollWidth ≤ 390');
  sm = await small(p); chk(!sm.length, '모든 단추·입력칸 44px 이상' + (sm.length ? ' → ' + sm.join(',') : ''));
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
  await p.fill('#tuIn', '다음에 보낼 글'); await p.press('#tuIn', 'Enter'); await p.waitForTimeout(100);
  chk(p.reqs.length === 1 && await p.inputValue('#tuIn') === '다음에 보낼 글', '기다리는 중 Enter: 보내지 않고 글은 입력칸에 남음');
  release(); await p.waitForFunction(() => !TUTOR.busy, null, { timeout: 5000 }); await p.waitForTimeout(200);
  chk(/바빠서 다른 AI/.test(await p.innerText('#tuLog')), '대체 AI 안내 줄');
  chk(await p.inputValue('#tuIn') === '다음에 보낼 글', '답이 온 뒤에도 쓰던 글이 그대로');
  await p.fill('#tuIn', '');
  chk(!(await p.evaluate(() => S.tutor.msgs.filter(m => m.role === 'note').length === 0)), 'note가 기록에 있음(서버로는 안 보냄)');
  await p.evaluate(() => tutorSend('suite')); await p.waitForFunction(() => !TUTOR.busy, null, { timeout: 5000 });
  chk(p.reqs[1] && p.reqs[1].body.messages.every(m => m.role === 'user' || m.role === 'assistant'), 'note는 서버로 가지 않는다');
  await p.evaluate(() => { activateLanguage('zh'); });
  await until(p, () => CUR && CUR.code === 'zh', null, 8000);
  chk(await p.evaluate(() => tutorState().msgs.length) === 0 && await p.evaluate(() => S.tutor.code) === 'zh', '언어를 바꾸면 새 대화'); await ctx.close();

  console.log('=== 개인정보 안내: tutorUrl이 없으면 "내 키" 문구, 있으면 중계 문구(둘 중 하나만) ===');
  for (const withUrl of [false, true]) {
    const c2 = await browser.newContext({ viewport: { width: 390, height: 844 } }), pg = await c2.newPage();
    await pg.route('**/cloud-config.js*', async r => { const res = await r.fetch(); let b = await res.text(); if (withUrl) b = b.replace('tutorUrl: null', "tutorUrl: '" + TUTOR + "'"); r.fulfill({ response: res, body: b }); });
    await pg.goto(BASE + '/privacy.html'); await pg.waitForTimeout(300);
    const vis = await pg.evaluate(() => Array.from(document.querySelectorAll('.tutor-only')).map(e => getComputedStyle(e).display !== 'none'));
    chk(vis.length >= 3 && vis.every(v => v === withUrl), (withUrl ? 'tutorUrl 있음' : 'tutorUrl 없음') + ': .tutor-only ' + vis.length + '곳 모두 ' + (withUrl ? '보임' : '숨김'));
    const own = await pg.evaluate(() => Array.from(document.querySelectorAll('.tutor-own')).map(e => getComputedStyle(e).display !== 'none'));
    chk(own.length >= 4 && own.every(v => v === !withUrl), (withUrl ? 'tutorUrl 있음' : 'tutorUrl 없음') + ': .tutor-own ' + own.length + '곳 모두 ' + (withUrl ? '숨김' : '보임'));
    if (!withUrl) chk(/이 기기에서 Google\(Gemini API\)로 바로/.test(await pg.innerText('body')) && /키 지우기/.test(await pg.innerText('body')) && !/OpenAI/.test(await pg.innerText('body')), '내 키 문구(바로 보냄·키 지우기) · OpenAI 문구 없음');
    if (withUrl) chk(/저장하지 않아요/.test(await pg.innerText('body')) && /OpenAI/.test(await pg.innerText('body')), '저장 안 함·OpenAI 문구');
    await c2.close();
  }

  chk(!errors.length, 'pageerror 없음' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(bad ? 'RESULT: ' + bad + '건 실패' : 'RESULT: ALL PASS'); process.exit(bad ? 1 : 0);
})().catch(e => { console.log('CRASH', e); process.exit(2); });
