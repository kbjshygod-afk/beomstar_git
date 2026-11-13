// 🎯 맞춤 연습(듀오링고 Birdbrain 축소판) 시험 — 정답 확률 예측·문제 고르기·도전 문제·틀린 것 다시·모델 갱신·만들기 문제
// 사용: 저장소 맨 위에서 python3 -m http.server 8765 --bind 127.0.0.1 을 켜 두고
//       NODE_PATH=/opt/node-tools/node_modules node tools/tests/lt_coach.js [base=http://127.0.0.1:8765]
'use strict';
const { chromium } = require('playwright');
const BASE = (process.argv[2] || 'http://127.0.0.1:8765').replace(/\/$/, '');
const URL = BASE + '/language-teacher/index.html';
let bad = 0; const chk = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ FAIL ') + m); if (!c) bad++; };
const MOCK = () => {
  try { Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: { speak(u) { setTimeout(() => u.onend && u.onend({}), 10); }, cancel() { }, getVoices() { return []; } } }); } catch (e) { }
  HTMLMediaElement.prototype.play = function () { return Promise.resolve(); };
};
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const errors = [];
  const open = async (code, lessons, th) => {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
    const p = await ctx.newPage();
    p.on('pageerror', e => errors.push(e.message)); p.on('dialog', d => d.accept());
    await p.addInitScript(MOCK); await p.route('**/vendor/firebase/**', r => r.abort());
    await p.goto(URL); await p.evaluate(() => localStorage.clear());
    await p.evaluate(c => localStorage.setItem('lang_starter_v1', JSON.stringify({ schema: 4, active: c, settings: { rate: 1, voiceMode: 'natural', dailyGoal: 30, sfx: false }, seen: { ['welcome_' + c]: '2026-10-01', deqOfferShown: '2026-10-01', micAsk: '2026-10-01', micPrivacy: '2026-10-01', in_coach: '2026-10-01' } })), code);
    await p.reload();
    await p.waitForFunction(() => typeof CUR !== 'undefined' && CUR && DATA && S.view === 'home', null, { timeout: 20000 });
    await p.evaluate(([n, th]) => {
      const pr = prog(); ALL.slice(0, n).forEach(l => { pr.completed[l.id] = { score: 8, total: 8, date: todayStr() }; addWordsToSrs(l); });
      // 서로 다른 기억 상태 — 실제 복습 대상처럼 기억 확률 0.45~0.95 사이(마지막 연습 시각을 거꾸로 맞춘다)
      Object.values(pr.srs).forEach((c, i) => { c.hr = i % 4; c.hw = i % 3 === 0 ? 1 : 0; const pm = 0.45 + (i * 37 % 51) / 100; c.ht = Date.now() - hlrHalfLife(c) * Math.log2(1 / pm) * 864e5; });
      if (th != null) pr.bb = { th, n: 50, dt: {}, di: {} };
      save(); closeModal(true); go('play');
    }, [lessons, th]);
    await p.waitForTimeout(250);
    return { ctx, p };
  };
  let ctx, p;

  console.log('=== 열리는 조건 · 화면 ===');
  ({ ctx, p } = await open('es', 0)); chk(await p.evaluate(() => !PLAY_TILES.find(t => t.id === 'coach').need()), '복습 카드가 없으면 잠김'); await ctx.close();
  ({ ctx, p } = await open('es', 6));
  chk(await p.evaluate(() => PLAY_TILES.find(t => t.id === 'coach').need()) && !!(await p.$('[data-play="coach"]')), '카드가 모이면 놀이 탭에 🎯 맞춤 연습');
  await p.click('[data-play="coach"]'); await p.waitForTimeout(300);
  const st = await p.evaluate(() => ({ view: S.view, q: S.coach.q.map(x => ({ key: x.key, type: x.type, P: x.P, probe: x.probe })), pool: coachPool().map(x => ({ key: x.key, pm: x.pm })) }));
  chk(st.view === 'coach' && st.q.length === 10, '10문제 세션');
  const weakest = st.pool.slice().sort((a, b) => a.pm - b.pm).slice(0, 10).map(x => x.key).sort().join('|');
  chk(st.q.map(x => x.key).sort().join('|') === weakest, '기억 확률(HLR)이 가장 낮은 카드 10장으로 만듦');
  const main = st.q.filter(x => !x.probe), probes = st.q.filter(x => x.probe);
  chk(probes.length === 2 && st.q.slice(-2).every(x => x.probe), '도전 문제 2개가 끝에');
  chk(main.every((x, i) => i === 0 || x.P <= main[i - 1].P), '쉬운 것 → 어려운 것 순서');
  const mean = main.reduce((a, x) => a + x.P, 0) / main.length;
  chk(mean >= 0.8, '일반 문제의 평균 예측 정답률 ' + mean.toFixed(2) + ' (듀오링고처럼 높게)');
  const probeOk = await p.evaluate(() => S.coach.q.filter(x => x.probe).every(x => { const c = prog().srs[x.key], ds = COACH.types.filter(t => coachCanType(c, t)).map(t => Math.abs(bbPredict(c, x.key, t) - 0.7)); return Math.abs(Math.abs(x.P - 0.7) - Math.min(...ds)) < 0.005; }));   // 만든 뒤 시간이 조금 흘러 기억 확률이 아주 조금 달라진다
  chk(probeOk, '도전 문제는 쓸 수 있는 유형 중 예측 정답률이 0.7에 가장 가까운 것: ' + probes.map(x => x.type + ' ' + x.P.toFixed(2)).join(', '));
  const small = await p.evaluate(() => Array.from(document.querySelectorAll('#main button')).filter(b => { const r = b.getBoundingClientRect(); return r.width && (r.height < 44 || r.width < 44); }).map(b => b.id || b.className));
  chk(!small.length && await p.evaluate(() => document.documentElement.scrollWidth) <= 390, '단추 44px 이상 · 가로 넘침 없음' + (small.length ? ' → ' + small.join(',') : ''));

  console.log('=== 답하면: 실력·난이도(Birdbrain)와 기억(HLR)이 함께 갱신, 틀린 것은 끝에 다시 ===');
  const before = await p.evaluate(() => { const it = S.coach.q[0], c = prog().srs[it.key], bb = bbState(); return { key: it.key, type: it.type, P: bbPredict(c, it.key, it.type), th: bb.th, n: bb.n, hw: c.hw, hr: c.hr, dt: bbDt(bb, it.type), di: bbDi(bb, it.key) }; });
  await p.evaluate(() => coachAnswer(false, { pick: -1 })); await p.waitForTimeout(150);
  const after = await p.evaluate(k => { const bb = bbState(), c = prog().srs[k]; return { th: bb.th, n: bb.n, hw: c.hw, hr: c.hr, due: c.due, t1: todayStr(1), q: S.coach.q.length, last: S.coach.q[S.coach.q.length - 1], dt: bbDt(bb, S.coach.q[0].type), di: bbDi(bb, k) }; }, before.key);
  const k = 0.4 / Math.sqrt(1 + before.n / 20), e = 0 - before.P;
  chk(Math.abs(after.th - (before.th + k * e)) < 1e-9 && Math.abs(after.dt - (before.dt - k * e / 2)) < 1e-9 && Math.abs(after.di - (before.di - k * e / 2)) < 1e-9, '틀림: 실력 θ += K(y−P), 유형·단어 난이도 −= K(y−P)/2 (실력↓ 난이도↑)');
  chk(after.hw === before.hw + 1 && after.hr === before.hr && after.due === after.t1, '틀림: 기억 모델 틀린 수 +1, 내일 다시');
  chk(after.q === 11 && after.last.key === before.key && after.last.again, '틀린 문제가 세션 끝에 "다시 한 번"으로 붙음');
  chk(/정답/.test(await p.innerText('.co-fb')), '정답을 보여 줌');
  // 다시 나온 문제는 모델을 고치지 않는다
  const n0 = await p.evaluate(() => bbState().n);
  await p.evaluate(() => { S.coach.ans = null; S.coach.i = S.coach.q.length - 1; renderCoach(); coachAnswer(true, {}); });
  chk(await p.evaluate(n => bbState().n === n && S.coach.ok === 0, n0), '다시 나온 문제는 맞혀도 실력·기억을 다시 세지 않음');
  await ctx.close();

  console.log('=== 실력에 따라 문제 유형이 달라진다(알아보기 → 만들기) ===');
  ({ ctx, p } = await open('es', 6, -2)); const low = await p.evaluate(() => coachBuild().q.filter(x => !x.probe).map(x => x.type)); await ctx.close();
  ({ ctx, p } = await open('es', 6, 6)); const high = await p.evaluate(() => coachBuild().q.filter(x => !x.probe).map(x => x.type)); await ctx.close();
  const rank = t => ['recog', 'listen', 'recall', 'build'].indexOf(t), avg = a => a.reduce((s, t) => s + rank(t), 0) / a.length;
  chk(avg(high) > avg(low) && low.every(t => t === 'recog'), '실력 낮음: ' + low.join(',') + ' / 높음: ' + high.join(','));

  console.log('=== 만들기 문제(조각) · 맞히면 XP · 끝 요약 ===');
  ({ ctx, p } = await open('zh', 8, 6));
  await p.evaluate(() => coachOpen('play')); await p.waitForTimeout(200);
  const bi = await p.evaluate(() => S.coach.q.findIndex(x => x.type === 'build'));
  chk(bi >= 0, '중국어에서 만들기 문제가 나옴(글자 조각)');
  if (bi >= 0) {
    await p.evaluate(i => { S.coach.i = i; renderCoach(); }, bi); await p.waitForTimeout(100);
    const need = await p.evaluate(() => S.coach.q[S.coach.i].need.slice());
    const tiles = await p.evaluate(() => S.coach.q[S.coach.i].tiles.slice());
    const used = new Set();
    for (const t of need) { const idx = tiles.findIndex((x, j) => x === t && !used.has(j)); used.add(idx); await p.click('[data-tile="' + idx + '"]'); }
    const xp0 = await p.evaluate(() => S.coach.xp);
    await p.click('#coCheck'); await p.waitForTimeout(150);
    chk(/맞아요/.test(await p.innerText('.co-fb')) && await p.evaluate(x => S.coach.xp > x, xp0), '조각을 순서대로 누르면 정답 · XP');
  }
  await p.evaluate(() => { S.coach.i = S.coach.q.length; S.coach.ans = null; renderCoach(); }); await p.waitForTimeout(100);
  chk(/연습 끝/.test(await p.innerText('#main')) && !!(await p.$('#coAgain')), '끝 요약과 한 번 더');
  await p.click('#coDone'); await p.waitForTimeout(150); chk(await p.evaluate(() => S.view) === 'play', '끝내기 → 놀이 탭');

  console.log('=== 저장·합치기 ===');
  const sv = await p.evaluate(() => {
    save(); const q = normalizeStore(JSON.parse(localStorage.getItem('lang_starter_v1'))).byLang.zh;
    return { th: q.bb.th, n: q.bb.n, junk: LANG_EXT.bb.clean({ th: 'x' }), bt: LANG_EXT.bb.clean({ th: 1, n: 1, dt: { recog: 1, hack: 3 }, di: {} }).dt, m: LANG_EXT.bb.merge({ th: 1, n: 3 }, { th: 2, n: 9 }).th };
  });
  chk(typeof sv.th === 'number' && sv.n >= 1 && sv.junk === undefined && sv.bt.recog === 1 && !('hack' in sv.bt) && sv.m === 2, '실력·난이도 저장 · 모르는 칸·망가진 값은 버림 · 합칠 때 기록 많은 쪽');
  await ctx.close();

  console.log('=== 🧱 레슨 기억 강도: 시간이 지나면 줄고, 약해진 레슨은 홈에서 그 레슨 단어로 연습 ===');
  ({ ctx, p } = await open('es', 6, 2));
  const sg = await p.evaluate(() => {
    const l = ALL.find(x => isDone(x.id) && lessonCardKeys(x).length >= 4), ks = lessonCardKeys(l), pr = prog(), now = Date.now();
    ks.forEach(k => { pr.srs[k].hr = 3; pr.srs[k].hw = 0; pr.srs[k].ht = now; delete pr.srs[k].mastered; });
    const fresh = lessonStrength(l, now);
    ks.forEach(k => { pr.srs[k].ht = now - 40 * 864e5; }); save();
    return { id: l.id, gi: LESSON_BY_ID[l.id], unit: l.unitId, fresh, stale: lessonStrength(l, now), n: ks.length, weak: (weakestLesson() || {}).gi };
  });
  chk(sg.fresh > 0.99 && sg.stale < 0.6, '방금 연습: 강도 ' + sg.fresh.toFixed(2) + ' → 40일 뒤: ' + sg.stale.toFixed(2));
  chk(sg.weak === sg.gi, '가장 약해진 통과 레슨을 찾음');
  await p.evaluate(u => { S.openUnit = u; go('home'); }, sg.unit); await p.waitForTimeout(250);
  chk(!!(await p.$('[data-lesson="' + sg.gi + '"] .str-bars')) && /기억 강도 [0-4]\/4/.test(await p.getAttribute('[data-lesson="' + sg.gi + '"] .str-bars', 'aria-label')), '레슨 줄에 4칸 강도 막대(읽기 프로그램용 이름 포함)');
  chk(!!(await p.$('#weakBanner')), '홈에 "다시 단단하게" 안내');
  await p.click('#weakBanner'); await p.waitForTimeout(250);
  const ws = await p.evaluate(() => ({ view: S.view, keys: S.coach.q.map(x => x.key), title: S.coach.title }));
  const allowed = await p.evaluate(gi => lessonCardKeys(ALL[gi]), sg.gi);
  chk(ws.view === 'coach' && ws.keys.every(k => allowed.includes(k)) && /다시 단단하게/.test(await p.innerText('.lt-sub')), '그 레슨 단어로만 맞춤 연습(' + ws.keys.length + '문제)');
  const onlyLesson = await p.evaluate(gi => {   // 다른 레슨 카드를 훨씬 더 약하게 만들어도 그 레슨 카드로만 고르는지
    const pr = prog(), mine = lessonCardKeys(ALL[gi]), now = Date.now();
    Object.keys(pr.srs).filter(k => !mine.includes(k)).forEach(k => { pr.srs[k].ht = now - 300 * 864e5; pr.srs[k].hr = 0; });
    const q = coachBuild(mine).q.map(x => x.key), free = coachBuild().q.map(x => x.key);
    return { ok: q.every(k => mine.includes(k)), freeOther: free.some(k => !mine.includes(k)) };
  }, sg.gi);
  chk(onlyLesson.ok && onlyLesson.freeOther, '다른 카드가 더 약해도 레슨 연습은 그 레슨 카드만(제한 없는 연습은 다른 카드를 고름)');
  await p.evaluate(() => { const pr = prog(); S.coach.q.forEach(it => { hlrObserve(pr.srs[it.key], 1); }); save(); });
  const strAfter = await p.evaluate(gi => lessonStrength(ALL[gi]), sg.gi);
  chk(strAfter > 0.9 && strAfter > sg.stale + 0.4, '한 세션(최대 10장) 연습하면 강도가 다시 오름(' + sg.stale.toFixed(2) + ' → ' + strAfter.toFixed(2) + ')');
  await p.evaluate(() => coachBack()); await p.waitForTimeout(200);
  chk(await p.evaluate(() => S.view) === 'home' && await p.evaluate(gi => (weakestLesson() || {}).gi !== gi, sg.gi), '홈으로 돌아오면 그 레슨은 더 이상 약한 레슨이 아님(다른 레슨은 위에서 일부러 약하게 만듦)');
  await ctx.close();

  chk(!errors.length, 'pageerror 없음' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(bad ? 'RESULT: ' + bad + '건 실패' : 'RESULT: ALL PASS'); process.exit(bad ? 1 : 0);
})().catch(e => { console.log('CRASH', e); process.exit(2); });
