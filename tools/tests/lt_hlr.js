// 🧠 기억 모델(HLR, 듀오링고 반감기 회귀) 시험 — 공식·학습 규칙·복습 순서·예전 카드 이전·퀴즈 연결
// 사용: 저장소 맨 위에서 python3 -m http.server 8765 --bind 127.0.0.1 을 켜 두고
//       NODE_PATH=/opt/node-tools/node_modules node tools/tests/lt_hlr.js [base=http://127.0.0.1:8765]
'use strict';
const { chromium } = require('playwright');
const BASE = (process.argv[2] || 'http://127.0.0.1:8765').replace(/\/$/, '');
const URL = BASE + '/language-teacher/index.html';
let bad = 0; const chk = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ FAIL ') + m); if (!c) bad++; };
const near = (a, b, eps) => Math.abs(a - b) <= (eps || 1e-9) * Math.max(1, Math.abs(b));
const MOCK = () => {
  try { Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: { speak(u) { setTimeout(() => u.onend && u.onend({}), 10); }, cancel() { }, getVoices() { return []; } } }); } catch (e) { }
  HTMLMediaElement.prototype.play = function () { return Promise.resolve(); };
};
// 공개 코드 experiment.py의 train_update를 그대로 옮긴 기준 구현(앱 코드와 따로 — 같은 답이 나와야 한다)
function refTrain(w, c, prior, y, dt, x) {
  const LN2 = Math.LN2, MIN = 15 / 1440, MAX = 274, clampH = h => Math.min(MAX, Math.max(MIN, h));
  const pt = Math.min(0.9999, Math.max(0.0001, y));
  const h = clampH(2 ** (w[0] * x[0] + w[1] * x[1] + w[2] * x[2])), p = 2 ** (-dt / h), ht = clampH(-dt / Math.log2(pt));
  const dlp = 2 * (p - pt) * LN2 ** 2 * p * (dt / h), dlh = 2 * (h - ht) * LN2 * h;
  const nw = w.slice();
  for (let k = 0; k < 3; k++) {
    const rate = (1 / (1 + pt)) * 0.001 / Math.sqrt(1 + c[k]);
    nw[k] = w[k] - rate * dlp * x[k] - rate * 0.01 * dlh * x[k] - rate * 0.1 * (w[k] - prior[k]);
  }
  return nw;
}
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const errors = [];
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
  const p = await ctx.newPage();
  p.on('pageerror', e => errors.push(e.message)); p.on('dialog', d => d.accept());
  await p.addInitScript(MOCK); await p.route('**/vendor/firebase/**', r => r.abort());
  await p.goto(URL); await p.evaluate(() => localStorage.clear());
  await p.evaluate(() => localStorage.setItem('lang_starter_v1', JSON.stringify({ schema: 4, active: 'es', settings: { rate: 1, voiceMode: 'natural', dailyGoal: 30 }, seen: { welcome_es: '2026-10-01', deqOfferShown: '2026-10-01', micAsk: '2026-10-01', micPrivacy: '2026-10-01' } })));
  await p.reload();
  await p.waitForFunction(() => typeof CUR !== 'undefined' && CUR && DATA && S.view === 'home', null, { timeout: 20000 });
  await p.evaluate(() => closeModal(true));

  console.log('=== 공식: p = 2^(−Δ/h), h = 2^(θ·x), x = [1, √(1+맞힘), √(1+틀림)], 15분~274일 ===');
  const f = await p.evaluate(() => {
    const w = HLR.prior, c = { hr: 3, hw: 1, ht: Date.now() - 2 * 864e5 };
    const hExp = 2 ** (w[0] + w[1] * Math.sqrt(4) + w[2] * Math.sqrt(2));
    return { h: hlrHalfLife(c), hExp, p: hlrP(c), pExp: 2 ** (-2 / hExp), hMin: hlrHalfLife({ hr: 0, hw: 50 }), hMax: hlrHalfLife({ hr: 500, hw: 0 }) };
  });
  chk(near(f.h, Math.min(274, Math.max(15 / 1440, f.hExp))), '반감기 = 2^(θ·x) (' + f.h.toFixed(3) + '일)');
  chk(near(f.p, 2 ** (-2 / f.h), 1e-6), '기억 확률 = 2^(−Δ/h) (Δ=2일 → ' + f.p.toFixed(3) + ')');
  chk(near(f.hMin, 15 / 1440) && near(f.hMax, 274), '반감기는 15분 ~ 274일로 자름');
  const mono = await p.evaluate(() => [0, 1, 2, 3].map(hw => hlrHalfLife({ hr: 4, hw })));
  chk(mono.every((h, i) => i === 0 || h < mono[i - 1]), '같은 맞힘 수에서 틀림이 많을수록 반감기가 짧다: ' + mono.map(h => h.toFixed(2)).join(' > '));
  const up = await p.evaluate(() => [0, 1, 2, 4, 6].map(hr => hlrNextDays({ hr, hw: 0 })));
  chk(up.every((d, i) => i === 0 || d >= up[i - 1]) && up[0] === 1 && up[4] >= 30, '맞힐수록 다음 복습이 멀어진다(틀린 적 없을 때): ' + up.join('·') + '일');

  console.log('=== 학습 규칙: 공개 코드(experiment.py)와 같은 한 걸음 ===');
  const tr = await p.evaluate(() => {
    const pr = prog(); delete pr.hlr;
    const x = hlrX({ hr: 2, hw: 1 }); hlrTrain(0, 3, x); const after1 = pr.hlr.w.slice(), c1 = pr.hlr.c.slice();
    hlrTrain(1, 10, x); return { x, after1, c1, after2: pr.hlr.w.slice(), n: pr.hlr.n, prior: HLR.prior.slice() };
  });
  const e1 = refTrain(tr.prior, [0, 0, 0], tr.prior, 0, 3, tr.x), e2 = refTrain(e1, [1, 1, 1], tr.prior, 1, 10, tr.x);
  chk(tr.after1.every((v, k) => near(v, e1[k], 1e-12)) && tr.c1.join() === '1,1,1', '틀린 관찰 한 번: 가중치가 기준 구현과 같게 움직임');
  chk(tr.after2.every((v, k) => near(v, e2[k], 1e-12)) && tr.n === 2, '맞힌 관찰 다음 걸음도 같음(학습률은 1/√(1+횟수)로 줄어듦)');
  chk(tr.after1[0] < tr.prior[0], '빨리 잊은 관찰(3일 만에 틀림)은 반감기를 줄이는 쪽으로 움직임');

  console.log('=== 복습 채점: 하루 한 번만 세고, 다음 복습일은 기억 모델이 정함 ===');
  const g = await p.evaluate(() => {
    const pr = prog(); delete pr.hlr;
    const c = { native: 'gato', pinyin: '', ko: '고양이', box: 2, due: todayStr(), hr: 1, hw: 0, ht: Date.now() - 3 * 864e5 };
    srsGrade(c, 'ok'); const a = { hr: c.hr, hw: c.hw, box: c.box, due: c.due, days: hlrNextDays(c) };
    srsGrade(c, 'ok'); const b = { hr: c.hr, hw: c.hw };
    srsGrade(c, 'fail'); const d = { hr: c.hr, hw: c.hw, box: c.box, due: c.due };
    srsGrade(c, 'fail'); const e = { hw: c.hw };
    return { a, b, d, e, today1: todayStr(1), dueExp: todayStr(a.days) };
  });
  chk(g.a.hr === 2 && g.a.hw === 0 && g.a.box === 3 && g.a.due === g.dueExp, '맞힘: 맞힌 수 +1, 상자 +1, 다음 복습 = 기억 모델(' + g.a.days + '일 뒤)');
  chk(g.b.hr === 2, '같은 날 또 맞혀도 맞힌 수는 그대로(하루 한 관찰)');
  chk(g.d.hw === 0.5 && g.d.box === 2 && g.d.due === g.today1, '같은 날 틀리면: 틀린 수 반 번만, 상자 −2(4→2), 내일 다시');
  chk(g.e.hw === 0.5, '같은 날 여러 번 틀려도 반 번만 더(부풀지 않음)');
  const hard = await p.evaluate(() => { const c = { native: 'x', box: 3, due: todayStr(), hr: 2, hw: 0, ht: Date.now() - 864e5 }; srsGrade(c, 'hard'); return { hr: c.hr, hw: c.hw, due: c.due, t1: todayStr(1) }; });
  chk(hard.hr === 2.5 && hard.hw === 0.5 && hard.due === hard.t1, '어렵게 맞힘: 맞힘·틀림 반씩, 내일 다시');

  console.log('=== 예전 카드(상자만 있음) 이전 · 복습 순서는 기억 확률이 낮은 것부터 ===');
  const mig = await p.evaluate(() => {
    const pr = prog(); pr.srs = {};
    pr.srs['a|'] = { native: 'a', pinyin: '', ko: 'A', box: 5, due: todayStr(-1), rv: todayStr(-16) };   // 오래 버틴 카드, 어제 예정
    pr.srs['b|'] = { native: 'b', pinyin: '', ko: 'B', box: 1, due: todayStr(), rv: todayStr(-2) };    // 새 카드, 오늘 예정
    pr.srs['c|'] = { native: 'c', pinyin: '', ko: 'C', box: 3, due: todayStr(3), rv: todayStr(-1) };   // 아직 예정 아님
    save(); const order = dueCards().map(c => c.native);
    const before = JSON.parse(JSON.stringify(pr.srs['c|']));
    return { order, pa: hlrP(pr.srs['a|']), pb: hlrP(pr.srs['b|']), cDue: before.due, t3: todayStr(3), hasHr: 'hr' in before };
  });
  chk(mig.order.join() === 'b,a', '예정된 카드만, 기억 확률 낮은 것부터(b ' + mig.pb.toFixed(2) + ' < a ' + mig.pa.toFixed(2) + ') — 예전처럼 날짜 순(a,b)이 아님');
  chk(mig.cDue === mig.t3 && !mig.hasHr, '예전 카드는 관찰 전까지 예정일·기록이 바뀌지 않음(복습이 쏟아지지 않음)');
  const mig2 = await p.evaluate(() => { const c = prog().srs['a|']; srsGrade(c, 'ok'); return { hr: c.hr, hw: c.hw }; });
  chk(mig2.hr === 5 && mig2.hw === 0, '예전 카드 첫 채점: 상자 5 → 맞힌 수 4로 시작해 +1');

  console.log('=== 저장·기기 합치기: 기록 칸이 살아남고, 가중치는 기록 많은 쪽 ===');
  const sv = await p.evaluate(() => {
    const pr = prog(); pr.srs['a|'].hr = 4.5; pr.hlr = { w: [1, 2, -3], c: [5, 5, 5], n: 5 }; save();
    const raw = JSON.parse(localStorage.getItem('lang_starter_v1')), s2 = normalizeStore(raw), q = s2.byLang.es;
    const m = LANG_EXT.hlr.merge({ w: [9, 9, 9], c: [1, 1, 1], n: 1 }, q.hlr), m2 = LANG_EXT.hlr.merge(q.hlr, { w: [0, 0, 0], c: [1, 1, 1], n: 99 });
    return { card: q.srs['a|'], hlr: q.hlr, m: m.w, m2: m2.n, junk: LANG_EXT.hlr.clean({ w: [1, 'x', 2] }) };
  });
  chk(sv.card.hr === 4.5 && sv.card.hw === 0 && sv.card.ht > 0 && /^\d{4}-\d\d-\d\d$/.test(sv.card.hd), '카드의 맞힘·틀림·시각·날이 저장 후에도 그대로');
  chk(sv.hlr.w.join() === '1,2,-3' && sv.m.join() === '1,2,-3' && sv.m2 === 99 && sv.junk === undefined, '가중치 저장 · 합칠 때 기록 많은 쪽 · 망가진 값은 버림');

  console.log('=== 퀴즈에서 맞히거나 틀린 것도 기억 모델에 들어간다 ===');
  const qz = await p.evaluate(() => {
    const pr = prog(); pr.srs = {};
    for (let i = 0; i < ALL.length; i++) {
      const l = ALL[i]; addWordsToSrs(l);
      const k = (l.quiz || []).findIndex(it => (it.type === 'listen' || it.type === 'choice') && Array.isArray(it.choices) && nativeText(it) && pr.srs[srsKeyOf(nativeText(it), romanText(it))]);
      if (k >= 0) { const c = pr.srs[srsKeyOf(nativeText(l.quiz[k]), romanText(l.quiz[k]))]; c.due = todayStr(30); c.hr = 2; c.hw = 0; c.ht = Date.now() - 864e5; delete c.hd; save(); return { idx: i, k, key: srsKeyOf(nativeText(l.quiz[k]), romanText(l.quiz[k])), ans: l.quiz[k].answer, n: l.quiz[k].choices.length }; }
    }
    return null;
  });
  chk(!!qz, '복습 카드와 같은 글을 묻는 퀴즈 문항을 찾음');
  if (qz) {
    await p.evaluate(o => { openLesson(o.idx, 4); S.quiz = newQuizState([o.k]); renderLesson(); }, qz); await p.waitForTimeout(300);
    const wrong = (qz.ans + 1) % qz.n;
    await p.click('[data-choice="' + wrong + '"]'); await p.waitForTimeout(200);
    const after = await p.evaluate(k => { const c = prog().srs[k]; return { hw: c.hw, hr: c.hr, due: c.due, t1: todayStr(1) }; }, qz.key);
    chk(after.hw === 1 && after.hr === 2 && after.due === after.t1, '퀴즈에서 틀림 → 틀린 수 +1, 30일 뒤였던 복습이 내일로 당겨짐');
  }

  console.log('=== 교차 검수 반영: 강한 카드를 퀴즈에서 틀리면 내일 · 같은 날 맞혀도 앞서 잡힌 내일을 덮지 않음 · 예전 카드 첫 복습은 지난 간격으로 학습 · 합치기 순서 무관 ===');
  const r2 = await p.evaluate(() => {
    const pr = prog(); pr.srs = {}; delete pr.hlr;
    const strong = { native: 'perro', pinyin: '', ko: '개', box: 6, due: todayStr(), hr: 20, hw: 0, ht: Date.now() - 10 * 864e5 };
    pr.srs['perro|'] = strong; hlrSeen('perro', '', true);   // 그날 첫 관찰(맞힘) → 멀리
    const far = strong.due;
    hlrSeen('perro', '', false);   // 같은 날 틀림 → 내일
    const afterMiss = strong.due;
    hlrSeen('perro', '', true);    // 같은 날 또 맞힘 → 내일 그대로
    const weak = { native: 'casa', pinyin: '', ko: '집', box: 7, due: todayStr(), hr: 30, hw: 0, ht: Date.now() - 864e5 };
    pr.srs['casa|'] = weak; hlrSeen('casa', '', false);   // 그날 첫 관찰이 틀림(강한 카드)
    return { far, afterMiss, kept: strong.due, weakDue: weak.due, t1: todayStr(1) };
  });
  chk(r2.far > r2.t1 && r2.afterMiss === r2.t1 && r2.kept === r2.t1, '같은 날: 맞힘(멀리) → 틀림(내일) → 또 맞힘(내일 그대로)');
  chk(r2.weakDue <= r2.t1, '맞힌 수 30인 강한 카드도 퀴즈에서 틀리면 내일 다시(몇 주 뒤로 밀리지 않음)');
  const legacy = await p.evaluate(() => {
    const pr = prog(); pr.srs = {}; delete pr.hlr;
    pr.srs['luna|'] = { native: 'luna', pinyin: '', ko: '달', box: 4, due: todayStr(), rv: todayStr(-15), rt: Date.now() - 15 * 864e5 };
    save(); S.review = newReview(dueCards(), 20); S.view = 'review'; renderReview(); return true;
  });
  await p.waitForTimeout(150);
  if (await p.$('#fcFlip')) { await p.click('#fcFlip'); await p.waitForTimeout(100); }
  await p.click('#fcPass'); await p.waitForTimeout(150);
  const lg = await p.evaluate(() => { const c = prog().srs['luna|'], h = prog().hlr; return { n: h && h.n, hr: c.hr, moved: h && h.w.some((v, k) => v !== HLR.prior[k]) }; });
  chk(lg.n === 1 && lg.moved && lg.hr === 4, '복습 탭에서 예전 카드 첫 채점: 지난 15일 간격으로 학습(가중치가 움직임) · 맞힌 수 3→4');
  const mg = await p.evaluate(() => { const a = { w: [1, 2, 3], c: [1, 1, 1], n: 4 }, b = { w: [3, 2, 1], c: [1, 1, 1], n: 4 }; return JSON.stringify(LANG_EXT.hlr.merge(a, b)) === JSON.stringify(LANG_EXT.hlr.merge(b, a)) && JSON.stringify(LANG_EXT.bb.merge({ th: 1, n: 2 }, { th: 2, n: 2 })) === JSON.stringify(LANG_EXT.bb.merge({ th: 2, n: 2 }, { th: 1, n: 2 })); });
  chk(mg, '관찰 수가 같아도 어느 쪽에서 합치든 같은 결과');
  const cm = await p.evaluate(() => {   // 카드의 기억 칸은 기기 합치기에서 최신 판정 쪽이 통째로 남는다
    const a = { completed: {}, srs: { 'k|': { native: 'k', box: 2, due: todayStr(1), rv: todayStr(-1), rt: 1, hr: 1, hw: 0, ht: 1 } } };
    const b = { completed: {}, srs: { 'k|': { native: 'k', box: 3, due: todayStr(5), rv: todayStr(), rt: 2, hr: 2, hw: 1, ht: 2, hd: todayStr() } } };
    const m1 = mergeLang(a, b).srs['k|'], m2 = mergeLang(b, a).srs['k|'];
    return m1.hr === 2 && m1.hw === 1 && m1.hd && m2.hr === 2 && m2.ht === 2;
  });
  chk(cm, '기기 합치기: 카드의 맞힘·틀림·시각은 최신 판정 쪽이 통째로(어느 쪽에서 합쳐도)');

  chk(!errors.length, 'pageerror 없음' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(bad ? 'RESULT: ' + bad + '건 실패' : 'RESULT: ALL PASS'); process.exit(bad ? 1 : 0);
})().catch(e => { console.log('CRASH', e); process.exit(2); });
