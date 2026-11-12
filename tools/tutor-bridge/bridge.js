#!/usr/bin/env node
'use strict';
// 💚 AI 튜터 '다리' 프로그램 — 내 컴퓨터에서 켜 두면, 앱(휴대폰)이 보낸 글을 Codex CLI(ChatGPT 구독 로그인)에 물어 답을 돌려준다.
// API 키가 필요 없다(구독 한도에서 차감). 혼자 쓰는 용도 — 연결 주소(암호 포함)를 남에게 주지 않는다.
// 쓰는 법: docs/tutor-bridge.md   ·   시험: node --test tools/tutor-bridge/
const http = require('http'), fs = require('fs'), os = require('os'), path = require('path'), crypto = require('crypto');
const { spawn } = require('child_process');
const core = require('../../functions/tutor-core.js');   // 입력 검증·지시문은 중계 함수와 같은 규칙을 쓴다

const DEFAULT_ORIGINS = ['https://kbjshygod-afk.github.io', 'http://127.0.0.1:8765', 'http://localhost:8765'];
const MAX_BODY = 64 * 1024;

// 지시문 + 대화 기록을 한 덩어리 글로 만든다(Codex는 한 번에 글 하나를 받는다).
function buildPrompt(req) {
    const who = { user: '학습자', assistant: '튜터' };
    return [
        '아래는 언어 학습 앱의 튜터 역할 지시와 지금까지의 대화다.',
        '명령 실행·파일 읽기·도구 사용을 하지 말고, 코드나 작업 설명 없이 튜터의 다음 답만 그대로 출력하라.',
        '', '[역할 지시]', core.buildSystemPrompt(req.lang, req.level, req.mode),
        '', '[대화]', req.messages.map(m => who[m.role] + ': ' + m.text).join('\n'), '튜터:',
    ].join('\n');
}

// Codex CLI를 한 번 실행해 마지막 답만 받는다. 빈 폴더에서 읽기 전용으로 돈다.
function askCodex(prompt, o) {
    return new Promise((resolve, reject) => {
        const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tutor-bridge-'));
        const args = ['exec', '--skip-git-repo-check', '--ephemeral', '-s', 'read-only', '--color', 'never'];
        if (o.effort) args.push('-c', 'model_reasoning_effort=' + o.effort);
        if (o.model) args.push('-m', o.model);
        args.push('-o', 'reply.txt', '-');
        let err = '', done = false, child;
        const finish = (e, v) => { if (done) return; done = true; clearTimeout(timer); try { fs.rmSync(dir, { recursive: true, force: true }); } catch (x) { } e ? reject(e) : resolve(v); };
        const fail = (status, error, detail) => finish(Object.assign(new Error(detail || error), { status, error }));
        const timer = setTimeout(() => { try { child.kill('SIGKILL'); } catch (x) { } fail(504, '답이 너무 늦어요. 잠시 뒤 다시 해 주세요', 'timeout'); }, o.timeoutMs);
        try { child = spawn(o.bin, args, { cwd: dir, stdio: ['pipe', 'ignore', 'pipe'], shell: process.platform === 'win32' }); }
        catch (e) { return fail(503, 'Codex CLI를 실행하지 못했어요. 컴퓨터에 설치돼 있는지 확인해 주세요', String(e && e.message)); }
        child.on('error', e => fail(503, 'Codex CLI를 실행하지 못했어요. 컴퓨터에 설치돼 있는지 확인해 주세요', String(e && e.message)));
        child.stderr.on('data', d => { err = (err + d).slice(-4000); });
        child.stdin.on('error', () => { });
        child.stdin.end(prompt);
        child.on('close', code => {
            let text = ''; try { text = fs.readFileSync(path.join(dir, 'reply.txt'), 'utf8').trim(); } catch (x) { }
            if (code === 0 && text) return finish(null, text.slice(0, 4000));
            if (/not logged in|login required|401|unauthorized/i.test(err)) return fail(503, '컴퓨터의 Codex가 로그인돼 있지 않아요. 컴퓨터에서 codex login 을 해 주세요', err);
            if (/usage limit|rate limit|429|quota/i.test(err)) return fail(429, 'ChatGPT 구독 한도를 넘었어요. 나중에 다시 해 주세요', err);
            fail(502, 'ChatGPT가 지금 답하지 못해요. 잠시 뒤 다시 해 주세요', 'exit ' + code + ' ' + err);
        });
    });
}

function tokenOk(header, token) {
    const m = /^Bearer (.+)$/.exec(header || ''); if (!m) return false;
    const a = crypto.createHash('sha256').update(m[1]).digest(), b = crypto.createHash('sha256').update(token).digest();
    return crypto.timingSafeEqual(a, b);
}

// opts: { token, origins, bin, model, effort, timeoutMs, dailyLimit, ask(시험용), log }
function createServer(opts) {
    const o = Object.assign({ origins: DEFAULT_ORIGINS, bin: 'codex', model: '', effort: 'low', timeoutMs: 120000, dailyLimit: 200, log: () => { } }, opts);
    if (!o.token || o.token.length < 20) throw new Error('token이 필요해요(20자 이상)');
    const ask = o.ask || (p => askCodex(p, o));
    const st = { busy: false, day: '', n: 0 };
    return http.createServer((req, res) => {
        const cors = core.corsHeaders(req.headers.origin, o.origins);
        if (cors['Access-Control-Allow-Origin']) cors['Access-Control-Allow-Private-Network'] = 'true';   // 같은 컴퓨터의 브라우저에서 바로 쓸 때(크롬)
        const send = (status, obj) => { res.writeHead(status, Object.assign({ 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', vary: 'Origin' }, cors)); res.end(obj ? JSON.stringify(obj) : ''); };
        const url = (req.url || '').split('?')[0];
        if (req.method === 'OPTIONS') return send(204);
        if (!tokenOk(req.headers.authorization, o.token)) return send(401, { error: '연결 암호가 맞지 않아요' });
        if (req.method === 'GET' && url === '/health') return send(200, { ok: true, engine: 'chatgpt' });
        if (!(req.method === 'POST' && url === '/tutor')) return send(404, { error: '없는 주소예요' });
        let size = 0; const chunks = [];
        req.on('data', c => { size += c.length; if (size > MAX_BODY) { send(413, { error: '글이 너무 길어요' }); req.destroy(); } else chunks.push(c); });
        req.on('end', async () => {
            if (size > MAX_BODY) return;
            let body = null; try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch (e) { body = null; }
            const v = core.validateRequest(body && typeof body === 'object' && !Array.isArray(body) ? Object.assign({}, body, { engine: 'openai' }) : body);
            if (!v.ok) return send(v.code, { error: v.error });
            const day = core.dayKey(); if (st.day !== day) { st.day = day; st.n = 0; }
            if (st.busy) return send(429, { error: '앞의 답을 기다리는 중이에요. 잠시만요' });
            if (st.n >= o.dailyLimit) return send(429, { error: '오늘 쓸 수 있는 횟수(' + o.dailyLimit + '번)를 다 썼어요' });
            st.busy = true; st.n++;
            const t0 = Date.now();
            try {
                const reply = await ask(buildPrompt(v.value));
                o.log('답함 ' + ((Date.now() - t0) / 1000).toFixed(1) + '초 (' + st.n + '/' + o.dailyLimit + ')');   // 글 내용은 기록하지 않는다
                send(200, { reply, engine: 'openai', remaining: o.dailyLimit - st.n });
            } catch (e) {
                st.n--;   // 실패한 요청은 세지 않는다
                o.log('실패: ' + String(e && e.message || e).slice(0, 300));
                send(e && e.status || 502, { error: e && e.error || 'ChatGPT가 지금 답하지 못해요' });
            } finally { st.busy = false; }
        });
    });
}

// 연결 암호: 처음 한 번 만들어 내 홈 폴더에 둔다(저장소 밖, 본인만 읽기).
function loadToken(file) {
    try { const t = fs.readFileSync(file, 'utf8').trim(); if (/^[A-Za-z0-9_-]{32,100}$/.test(t)) return t; } catch (e) { }
    const t = crypto.randomBytes(32).toString('base64url');
    fs.writeFileSync(file, t + '\n', { mode: 0o600 });
    return t;
}

// Cloudflare 임시 터널(무료, 가입 없음)을 켜고 https 주소를 받는다. cloudflared가 없으면 null.
function startTunnel(port, onUrl, log) {
    let child;
    try { child = spawn('cloudflared', ['tunnel', '--no-autoupdate', '--url', 'http://127.0.0.1:' + port], { stdio: ['ignore', 'pipe', 'pipe'], shell: process.platform === 'win32' }); } catch (e) { return null; }
    let buf = '', found = false;
    const scan = d => { if (found) return; buf = (buf + d).slice(-8000); const m = /https:\/\/[a-z0-9-]+\.trycloudflare\.com/.exec(buf); if (m) { found = true; onUrl(m[0]); } };
    child.stdout.on('data', scan); child.stderr.on('data', scan);
    child.on('error', () => { if (!found) onUrl(null); });
    child.on('close', code => { if (!found) onUrl(null); else log('⚠ 터널이 꺼졌어요(코드 ' + code + '). 다리 프로그램을 다시 켜 주세요 — 주소가 바뀌어요.'); });
    return child;
}

if (require.main === module) {
    const port = Number(process.env.TUTOR_BRIDGE_PORT) || 8787;
    const token = loadToken(process.env.TUTOR_BRIDGE_TOKEN_FILE || path.join(os.homedir(), '.lang-starter-bridge-token'));
    const log = m => console.log(new Date().toLocaleTimeString() + '  ' + m);
    const server = createServer({
        token, log,
        bin: process.env.CODEX_BIN || 'codex', model: process.env.TUTOR_CODEX_MODEL || '',
        effort: process.env.TUTOR_CODEX_EFFORT === undefined ? 'low' : process.env.TUTOR_CODEX_EFFORT,
        dailyLimit: Number(process.env.TUTOR_BRIDGE_DAILY) || 200,
        origins: process.env.TUTOR_BRIDGE_ORIGINS ? process.env.TUTOR_BRIDGE_ORIGINS.split(',').map(s => s.trim()).filter(Boolean) : DEFAULT_ORIGINS,
    });
    const show = base => console.log('\n  앱의 🤖 AI 튜터 → 🔑 키 → "ChatGPT 연결"에 아래 한 줄을 붙여 넣으세요 (남에게 보여 주지 마세요):\n\n    ' + base + '#' + token + '\n');
    server.listen(port, '127.0.0.1', () => {
        log('다리 프로그램이 켜졌어요 (이 컴퓨터 안: http://127.0.0.1:' + port + ')');
        if (process.argv.includes('--local')) { show('http://127.0.0.1:' + port); return; }
        log('휴대폰에서 닿도록 Cloudflare 임시 터널을 켜는 중…');
        const t = startTunnel(port, url => {
            if (url) { show(url); log('이 창을 닫으면 연결이 끊겨요. 다시 켜면 주소가 바뀌니 앱에 새로 붙여 넣어야 해요.'); }
            else { log('cloudflared를 찾지 못했거나 터널이 켜지지 않았어요. 이 컴퓨터의 브라우저에서만 쓸 수 있어요. (설치: docs/tutor-bridge.md)'); show('http://127.0.0.1:' + port); }
        }, log);
        const stop = () => { try { t && t.kill(); } catch (e) { } process.exit(0); };
        process.on('SIGINT', stop); process.on('SIGTERM', stop);
    });
    server.on('error', e => { console.error('켜지 못했어요: ' + e.message + (e.code === 'EADDRINUSE' ? ' — 이미 켜져 있거나 다른 프로그램이 ' + port + '번을 쓰고 있어요' : '')); process.exit(1); });
}

module.exports = { createServer, buildPrompt, askCodex, loadToken, DEFAULT_ORIGINS };
