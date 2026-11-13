// 🤖 중계 함수 시험 — Firebase 에뮬레이터(함수·로그인·DB)에서 실제 코드를 돌린다. Gemini/OpenAI 호출은 가짜로 끼운 환경에서 돈다.
// 켜는 법(저장소 맨 위 폴더):
//   printf 'GEMINI_API_KEY=x\nOPENAI_API_KEY=y\n' > functions/.secret.local ; printf 'TUTOR_DAILY_LIMIT=3\n' > functions/.env.local
//   NODE_OPTIONS="--require $PWD/tools/tests/ai-stub.js" firebase emulators:start --only functions,auth,firestore --project demo-langstarter
//   node tools/tests/lt_tutor_fn.js
// (tools/tests/ai-stub.js: 함수 프로세스에서 Gemini·OpenAI 호출만 가짜 응답으로 바꾼다. 글에 'FAILGEMINI'가 있으면 Gemini 429, 'BADKEY'면 403, 'FAILOPENAI'면 OpenAI 500)
'use strict';
const FN = 'http://127.0.0.1:5001/demo-langstarter/asia-northeast3/tutor', AUTH = 'http://127.0.0.1:9099', FS = 'http://127.0.0.1:8080';
let bad = 0; const chk = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ FAIL ') + m); if (!c) bad++; };
const post = (body, tok, extra) => fetch(FN, { method: 'POST', headers: Object.assign({ 'content-type': 'application/json' }, tok ? { authorization: 'Bearer ' + tok } : {}, extra || {}), body: JSON.stringify(body) }).then(async r => ({ status: r.status, json: await r.json().catch(() => ({})) }));
const msg = t => ({ lang: 'zh', engine: 'gemini', mode: 'chat', level: 1, messages: [{ role: 'user', text: t }] });
const newUser = async n => { const r = await fetch(AUTH + '/identitytoolkit.googleapis.com/v1/accounts:signUp?key=x', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ email: n + '@test.dev', password: 'pw123456' }) }); const j = await r.json(); return { tok: j.idToken, uid: j.localId }; };
const usage = async uid => {   // 에뮬레이터 관리자 권한으로 한도 칸을 읽는다
  const day = new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10);
  const r = await fetch(FS + '/v1/projects/demo-langstarter/databases/(default)/documents/tutorUsage/' + uid + '_' + day, { headers: { authorization: 'Bearer owner' } });
  if (r.status === 404) return null; const j = await r.json(); return { n: Number(j.fields.n.integerValue), f: j.fields };
};
const seed = async (uid, n) => {
  const day = new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10);
  await fetch(FS + '/v1/projects/demo-langstarter/databases/(default)/documents/tutorUsage/' + uid + '_' + day, { method: 'PATCH', headers: { authorization: 'Bearer owner', 'content-type': 'application/json' }, body: JSON.stringify({ fields: { n: { integerValue: String(n) } } }) });
};
(async () => {
  console.log('=== 로그인·요청 형식 ===');
  let r = await fetch(FN); chk(r.status === 405, 'GET은 405');
  r = await post(msg('hi')); chk(r.status === 401, '토큰 없으면 401');
  r = await post(msg('hi'), 'not-a-token'); chk(r.status === 401, '엉터리 토큰이면 401');
  const A = await newUser('a' + Date.now());
  r = await post({ lang: 'xx', messages: [] }, A.tok); chk(r.status === 400, '잘못된 요청은 400: ' + JSON.stringify(r.json));
  chk(await usage(A.uid) === null, '잘못된 요청은 한도를 쓰지 않는다');

  console.log('=== 정상 호출: 답·남은 횟수·기록 칸(만료 시각 포함) ===');
  r = await post(msg('你好'), A.tok);
  chk(r.status === 200 && r.json.reply === '[gemini] 你好' && r.json.engine === 'gemini' && r.json.fellBack === false, 'Gemini 답: ' + JSON.stringify(r.json));
  chk(r.json.remaining === 2, '남은 횟수 2 (한도 3)');
  const u1 = await usage(A.uid); chk(u1 && u1.n === 1, '한도 칸 n=1'); chk(u1 && u1.f.expireAt && u1.f.expireAt.timestampValue, 'expireAt 기록(자동 삭제용)'); chk(u1 && !JSON.stringify(u1.f).includes('你好'), '학습자 글은 DB에 저장되지 않는다');
  r = await post(Object.assign(msg('hola'), { engine: 'openai' }), A.tok); chk(r.status === 200 && r.json.reply === '[openai] hola' && r.json.engine === 'openai', 'ChatGPT 답');

  console.log('=== 대체: 고른 AI가 429면 다른 AI가 답하고 fellBack ===');
  r = await post(msg('FAILGEMINI 안녕'), A.tok); chk(r.status === 200 && r.json.engine === 'openai' && r.json.fellBack === true, '대체: ' + JSON.stringify(r.json));
  console.log('=== 하루 한도: 3번 뒤 4번째는 429 ===');
  r = await post(msg('again'), A.tok); chk(r.status === 429 && r.json.remaining === 0, '한도 초과 429: ' + JSON.stringify(r.json));
  chk((await usage(A.uid)).n === 3, '거절된 호출은 횟수를 올리지 않는다');

  console.log('=== 실패하면 횟수를 돌려준다(키 오류 403 · 두 AI 모두 실패) ===');
  const B = await newUser('b' + Date.now());
  r = await post(msg('BADKEY'), B.tok); chk(r.status === 502, '키 오류는 502: ' + r.status);
  chk((await usage(B.uid)).n === 0, '실패한 호출은 한도에서 빠진다');
  r = await post(msg('FAILGEMINI FAILOPENAI'), B.tok); chk(r.status === 502 && (await usage(B.uid)).n === 0, '둘 다 실패해도 502 + 횟수 그대로');
  chk(!JSON.stringify(r.json).includes('FAIL'), '오류 응답에 글이 되돌아오지 않는다');

  console.log('=== 사람마다 따로 센다 ===');
  const C = await newUser('c' + Date.now()); r = await post(msg('x'), C.tok); chk(r.status === 200 && r.json.remaining === 2, '다른 사람은 새로 시작');

  console.log('=== CORS: 우리 사이트는 허용(남의 사이트 거절은 단위 시험) ===');
  let o = await fetch(FN, { method: 'OPTIONS', headers: { origin: 'https://kbjshygod-afk.github.io', 'access-control-request-method': 'POST', 'access-control-request-headers': 'authorization,content-type' } });
  chk(o.headers.get('access-control-allow-origin') === 'https://kbjshygod-afk.github.io', '내 사이트 허용');
  // 남의 사이트 거절은 여기서 확인할 수 없다: Firebase 에뮬레이터는 모든 사이트를 허용하도록 만들어져 있다(실제 배포에는 없는 기능). 그 규칙은 단위 시험(functions/test)에서 확인한다.
  console.log(bad ? 'RESULT: ' + bad + '건 실패' : 'RESULT: ALL PASS'); process.exit(bad ? 1 : 0);
})().catch(e => { console.log('CRASH', e); process.exit(2); });
