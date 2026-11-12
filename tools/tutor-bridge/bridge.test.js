'use strict';
// 다리 프로그램 시험 — Codex CLI는 가짜 프로그램으로 바꿔 끼운다(진짜 ChatGPT는 부르지 않는다).
const test = require('node:test'), assert = require('node:assert');
const fs = require('fs'), os = require('os'), path = require('path');
const { createServer, buildPrompt, askCodex, loadToken } = require('./bridge.js');

const TOKEN = 'tok_0123456789abcdefghijklmnopqrstuv', SITE = 'https://kbjshygod-afk.github.io';
const BODY = { lang: 'zh', mode: 'chat', level: 2, messages: [{ role: 'user', text: '你好' }] };
async function up(opts) {
    const s = createServer(Object.assign({ token: TOKEN }, opts)); await new Promise(r => s.listen(0, '127.0.0.1', r));
    const base = 'http://127.0.0.1:' + s.address().port;
    const call = (p, o) => fetch(base + p, Object.assign({ method: 'POST', headers: { authorization: 'Bearer ' + TOKEN, 'content-type': 'application/json', origin: SITE }, body: JSON.stringify(BODY) }, o));
    return { s, base, call, close: () => new Promise(r => s.close(r)) };
}
// 가짜 codex: 받은 인자·글을 적어 두고, -o 파일에 답을 쓴다
function fakeCodex(script) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fake-codex-')), f = path.join(dir, 'codex');
    fs.writeFileSync(f, '#!/usr/bin/env node\n' + script, { mode: 0o755 }); return { bin: f, dir };
}

test('암호 없거나 틀리면 401 · AI는 부르지 않는다', async () => {
    let n = 0; const x = await up({ ask: async () => { n++; return 'x'; } });
    for (const h of [{}, { authorization: 'Bearer wrong_wrong_wrong_wrong_wrong' }, { authorization: TOKEN }]) {
        const r = await x.call('/tutor', { headers: Object.assign({ 'content-type': 'application/json' }, h) }); assert.strictEqual(r.status, 401);
    }
    assert.strictEqual((await fetch(x.base + '/health')).status, 401);
    assert.strictEqual(n, 0); await x.close();
});

test('health · 정상 답 · 남은 횟수 · 지시문에 언어와 대화가 들어간다', async () => {
    let got = ''; const x = await up({ dailyLimit: 5, ask: async p => { got = p; return '你好！'; } });
    const h = await fetch(x.base + '/health', { headers: { authorization: 'Bearer ' + TOKEN } }); assert.deepStrictEqual(await h.json(), { ok: true, engine: 'chatgpt' });
    const r = await x.call('/tutor'); assert.strictEqual(r.status, 200);
    assert.deepStrictEqual(await r.json(), { reply: '你好！', engine: 'openai', remaining: 4 });
    assert.match(got, /중국어/); assert.match(got, /병음/); assert.match(got, /학습자: 你好\n튜터:$/); assert.match(got, /도구 사용을 하지 말고/);
    await x.close();
});

test('CORS: 내 사이트만 허용 · 남의 사이트에는 허용 헤더가 없다 · OPTIONS는 암호 없이 204', async () => {
    const x = await up({ ask: async () => 'ok' });
    const ok = await fetch(x.base + '/tutor', { method: 'OPTIONS', headers: { origin: SITE } });
    assert.strictEqual(ok.status, 204); assert.strictEqual(ok.headers.get('access-control-allow-origin'), SITE); assert.match(ok.headers.get('access-control-allow-headers'), /authorization/);
    const bad = await fetch(x.base + '/tutor', { method: 'OPTIONS', headers: { origin: 'https://evil.example' } });
    assert.strictEqual(bad.headers.get('access-control-allow-origin'), null);
    const r = await x.call('/tutor', { headers: { authorization: 'Bearer ' + TOKEN, 'content-type': 'application/json', origin: 'https://evil.example' } });
    assert.strictEqual(r.headers.get('access-control-allow-origin'), null); await x.close();
});

test('잘못된 요청은 400(세지 않음) · 없는 주소 404 · 너무 긴 글 413', async () => {
    let n = 0; const x = await up({ dailyLimit: 1, ask: async () => { n++; return 'ok'; } });
    for (const b of ['{bad', JSON.stringify({ lang: 'xx', messages: [{ role: 'user', text: 'a' }] }), JSON.stringify({ lang: 'zh', messages: [] }), '[]'])
        assert.strictEqual((await x.call('/tutor', { body: b })).status, 400);
    assert.strictEqual((await x.call('/nope')).status, 404);
    assert.strictEqual((await x.call('/tutor', { body: JSON.stringify({ lang: 'zh', messages: [{ role: 'user', text: 'a'.repeat(70000) }] }) }).catch(() => ({ status: 413 }))).status, 413);
    assert.strictEqual(n, 0);
    assert.strictEqual((await x.call('/tutor')).status, 200); await x.close();
});

test('하루 한도 · 실패는 세지 않는다 · 동시에 두 개는 받지 않는다', async () => {
    let fail = true, release; const gate = new Promise(r => { release = r; });
    const x = await up({ dailyLimit: 2, ask: async () => { if (fail) throw Object.assign(new Error('x'), { status: 502, error: '실패' }); await gate; return 'ok'; } });
    const f = await x.call('/tutor'); assert.strictEqual(f.status, 502); assert.strictEqual((await f.json()).error, '실패');
    fail = false;
    const p1 = x.call('/tutor'); await new Promise(r => setTimeout(r, 80));
    const busy = await x.call('/tutor'); assert.strictEqual(busy.status, 429); assert.match((await busy.json()).error, /기다리는 중/);
    release(); assert.strictEqual((await (await p1).json()).remaining, 1);
    assert.strictEqual((await (await x.call('/tutor')).json()).remaining, 0);
    const over = await x.call('/tutor'); assert.strictEqual(over.status, 429); assert.match((await over.json()).error, /다 썼어요/); await x.close();
});

test('askCodex: 읽기 전용·빈 폴더·stdin으로 글 전달, -o 파일의 답을 읽는다', { skip: process.platform === 'win32' }, async () => {
    const log = path.join(os.tmpdir(), 'fake-codex-log-' + process.pid + '.json');
    const fx = fakeCodex(`const fs=require('fs');let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{const a=process.argv.slice(2);fs.writeFileSync(${JSON.stringify(log)},JSON.stringify({a,s,cwd:process.cwd(),files:fs.readdirSync('.')}));fs.writeFileSync(a[a.indexOf('-o')+1],'  답이에요\\n');});`);
    const out = await askCodex('물음', { bin: fx.bin, effort: 'low', model: 'm1', timeoutMs: 5000 });
    assert.strictEqual(out, '답이에요');
    const j = JSON.parse(fs.readFileSync(log, 'utf8'));
    assert.deepStrictEqual(j.a, ['exec', '--skip-git-repo-check', '--ephemeral', '-s', 'read-only', '--color', 'never', '-c', 'model_reasoning_effort=low', '-m', 'm1', '-o', 'reply.txt', '-']);
    assert.strictEqual(j.s, '물음'); assert.deepStrictEqual(j.files, []); assert.ok(!fs.existsSync(j.cwd), '임시 폴더는 지운다');
    fs.rmSync(log); fs.rmSync(fx.dir, { recursive: true });
});

test('askCodex: 로그인 안 됨 503 · 한도 429 · 그 밖 502 · 시간 초과 504 · 프로그램 없음 503', { skip: process.platform === 'win32' }, async () => {
    const run = async (script, ms) => { const fx = fakeCodex(script); try { await askCodex('q', { bin: fx.bin, timeoutMs: ms || 5000 }); return null; } catch (e) { return e; } finally { fs.rmSync(fx.dir, { recursive: true }); } };
    let e = await run(`console.error('Not logged in');process.exit(1)`); assert.strictEqual(e.status, 503); assert.match(e.error, /로그인/);
    e = await run(`console.error("You've hit your usage limit");process.exit(1)`); assert.strictEqual(e.status, 429);
    e = await run(`console.error('boom');process.exit(2)`); assert.strictEqual(e.status, 502);
    e = await run(`process.exit(0)`); assert.strictEqual(e.status, 502, '답 파일이 없으면 실패');
    e = await run(`setTimeout(()=>{},60000)`, 300); assert.strictEqual(e.status, 504);
    e = await askCodex('q', { bin: '/no/such/codex', timeoutMs: 3000 }).catch(x => x); assert.strictEqual(e.status, 503); assert.match(e.error, /설치/);
});

test('연결 암호: 처음 만들고(본인만 읽기) 다음부터 같은 값 · 짧은 암호로는 서버를 만들지 않는다', () => {
    const f = path.join(os.tmpdir(), 'bridge-token-' + process.pid);
    const a = loadToken(f), b = loadToken(f); assert.strictEqual(a, b); assert.match(a, /^[A-Za-z0-9_-]{40,}$/);
    if (process.platform !== 'win32') assert.strictEqual(fs.statSync(f).mode & 0o777, 0o600);
    fs.rmSync(f); assert.throws(() => createServer({ token: 'short' }));
    assert.match(buildPrompt({ lang: 'ja', level: 1, mode: 'correct', messages: [{ role: 'user', text: 'a' }, { role: 'assistant', text: 'b' }, { role: 'user', text: 'c' }] }), /학습자: a\n튜터: b\n학습자: c\n튜터:$/);
});
