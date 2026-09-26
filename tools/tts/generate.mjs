// 랭귀지 스타터 — Google Cloud Text-to-Speech로 음성 클립(MP3)을 한 번 미리 녹음한다 (의존성 없음, node 18+)
//
//   node tools/tts/generate.mjs --dry-run                  네트워크 없이 개수·글자 수·예상 요금·용량만 계산
//   node tools/tts/generate.mjs --list-voices --lang zh    쓸 수 있는 목소리 이름 확인(API 키 필요)
//   node tools/tts/generate.mjs                            전체 녹음(이미 있는 파일은 건너뜀 = 이어 하기)
//
// 옵션: --lang zh[,ja]  언어만 골라서 · --limit N  언어마다 새로 만들 클립 수 제한(시험용) · --prune  더 이상 안 쓰는 mp3 삭제
//       --redo  이미 있는 파일도 다시 녹음(rev가 바뀌어 앱이 새로 받음) · --concurrency N (기본 4) · --out DIR (시험용 출력 폴더)
// API 키: 환경 변수 GOOGLE_TTS_API_KEY (화면·로그에 절대 찍지 않는다. 요청 헤더 X-Goog-Api-Key 로만 보낸다)
// 결과: language-teacher/audio/{lang}/{id}.mp3 + index.json = { v: 1, voices: {a, b}, rate, rates: {a, b}(목소리 칸별 녹음 속도),
//       norate: [speakingRate를 거부한 목소리](있을 때만), gen: 다시 녹음한 횟수, rev: 앱 주소의 ?v=, ids: [디스크에 있는 클립 id, 정렬] }
import { mkdirSync, readdirSync, statSync, writeFileSync, renameSync, unlinkSync, readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { collectLang, LANG_CODES, APP_DIR } from './clips.mjs';

/* ═══════════════════ 설정: 언어별 목소리 · 속도 ═══════════════════
   a = 기본 목소리(여성) — 단어·문장·해설·대화 A/C/E/N 전부
   b = 대화 상대 목소리(남성) — 대화 speaker 'B'·'D' (앱 tuneFor()가 두 번째 목소리를 쓰는 화자)
   후보를 앞에서부터 확인해 실제로 있고 성별이 맞는 첫 목소리를 쓴다. 전부 없으면 같은 성별에서 가장 좋은 등급을 자동으로 고른다.
   이름 확인: node tools/tts/generate.mjs --list-voices --lang xx
   ⚠ zh: Chirp 3 HD가 다음자(多音字, 예: 还·行·得·了)를 틀리게 읽는 경우가 있을 수 있음 — 이번 범위 밖, 들어 보고 따로 고친다. */
const VOICES = {
    en: { languageCode: 'en-US', speakingRate: 0.95,
        a: ['en-US-Chirp3-HD-Kore', 'en-US-Chirp3-HD-Aoede', 'en-US-Neural2-F', 'en-US-Wavenet-F'],
        b: ['en-US-Chirp3-HD-Charon', 'en-US-Chirp3-HD-Puck', 'en-US-Neural2-J', 'en-US-Wavenet-D'] },
    zh: { languageCode: 'cmn-CN', speakingRate: 0.9,
        a: ['cmn-CN-Chirp3-HD-Kore', 'cmn-CN-Chirp3-HD-Aoede', 'cmn-CN-Wavenet-A', 'cmn-CN-Wavenet-D'],
        b: ['cmn-CN-Chirp3-HD-Charon', 'cmn-CN-Chirp3-HD-Puck', 'cmn-CN-Wavenet-B', 'cmn-CN-Wavenet-C'] },
    es: { languageCode: 'es-ES', speakingRate: 0.95,
        a: ['es-ES-Chirp3-HD-Kore', 'es-ES-Chirp3-HD-Aoede', 'es-ES-Neural2-A', 'es-ES-Wavenet-C'],
        b: ['es-ES-Chirp3-HD-Charon', 'es-ES-Chirp3-HD-Puck', 'es-ES-Neural2-F', 'es-ES-Wavenet-B'] },
    ja: { languageCode: 'ja-JP', speakingRate: 0.95,
        a: ['ja-JP-Chirp3-HD-Kore', 'ja-JP-Chirp3-HD-Aoede', 'ja-JP-Neural2-B', 'ja-JP-Wavenet-A'],
        b: ['ja-JP-Chirp3-HD-Charon', 'ja-JP-Chirp3-HD-Puck', 'ja-JP-Neural2-C', 'ja-JP-Wavenet-C'] },
    fr: { languageCode: 'fr-FR', speakingRate: 0.95,
        a: ['fr-FR-Chirp3-HD-Kore', 'fr-FR-Chirp3-HD-Aoede', 'fr-FR-Neural2-F', 'fr-FR-Wavenet-F'],
        b: ['fr-FR-Chirp3-HD-Charon', 'fr-FR-Chirp3-HD-Puck', 'fr-FR-Neural2-G', 'fr-FR-Wavenet-G'] },
};
const WANT_GENDER = { a: 'FEMALE', b: 'MALE' };
const AUDIO = { audioEncoding: 'MP3', sampleRateHertz: 24000 };   // Google MP3 = 32 kbps

// 요금(https://cloud.google.com/text-to-speech/pricing, 2026-09 확인): 글자 수(공백 포함) 기준, 무료 한도는 매달·결제 계정 단위.
// WaveNet과 Standard는 같은 SKU라 무료 400만 자를 함께 쓴다. 실제 요금은 반드시 가격 페이지에서 다시 확인.
const TIERS = [
    { id: 'chirp3hd', label: 'Chirp 3 HD', re: /-Chirp3-HD-/i, sku: 'F977-2280-6F1B', free: 1e6, usdPer1M: 30 },
    { id: 'neural2', label: 'Neural2', re: /-Neural2-/i, sku: 'FEBD-04B6-769B', free: 1e6, usdPer1M: 16 },
    { id: 'wavenet', label: 'WaveNet', re: /-Wavenet-/i, sku: '9D01-5995-B545', free: 4e6, usdPer1M: 4 },
    { id: 'standard', label: 'Standard', re: /-Standard-/i, sku: '9D01-5995-B545', free: 4e6, usdPer1M: 4 },
    { id: 'studio', label: 'Studio', re: /-Studio-/i, sku: '84AB-48C0-F9C3', free: 1e6, usdPer1M: 160 },
];
const AUTO_PICK_ORDER = ['chirp3hd', 'neural2', 'wavenet', 'standard'];
const tierOf = name => TIERS.find(t => t.re.test(name)) || { id: 'other', label: '기타', sku: '?', free: 0, usdPer1M: 0 };
// 용량 추정용 말하기 속도(초당 글자 수, 속도 1.0 기준)와 클립마다 붙는 앞뒤 무음
const CHARS_PER_SEC = { en: 14, es: 14, fr: 14, ja: 8, zh: 4.5 };
const PAD_SEC = 0.35, BYTES_PER_SEC = 32000 / 8;

const API = 'https://texttospeech.googleapis.com/v1';

/* ═══════════════════ 명령줄 ═══════════════════ */
const argv = process.argv.slice(2);
const flag = n => argv.includes(n);
const opt = n => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : undefined; };
if (flag('--help') || flag('-h')) { console.log(readFileSync(new URL(import.meta.url), 'utf8').split('\n').filter(l => l.startsWith('//')).slice(0, 11).join('\n')); process.exit(0); }
const DRY = flag('--dry-run');
const LIST_VOICES = flag('--list-voices');
const PRUNE = flag('--prune');
const REDO = flag('--redo');
const LIMIT = opt('--limit') !== undefined ? Math.max(0, parseInt(opt('--limit'), 10) || 0) : Infinity;
const CONC = Math.max(1, Math.min(16, parseInt(opt('--concurrency') || '4', 10) || 4));
const LANGS = opt('--lang') ? opt('--lang').split(',').map(s => s.trim()).filter(Boolean) : LANG_CODES;
for (const l of LANGS) if (!VOICES[l]) { console.error('모르는 언어: ' + l + ' (가능: ' + LANG_CODES.join(', ') + ')'); process.exit(2); }
const AUDIO_DIR = opt('--out') ? pathToFileURL(resolve(opt('--out')) + '/') : new URL('audio/', APP_DIR);   // --out 은 시험용(기본: language-teacher/audio/)
const KEY = process.env.GOOGLE_TTS_API_KEY || '';
const redact = s => (KEY ? String(s).split(KEY).join('***') : String(s));

/* ═══════════════════ 네트워크(드라이런에서는 절대 부르지 않음) ═══════════════════ */
class Fatal extends Error { }
async function api(method, path, body) {
    if (DRY) throw new Fatal('BUG: --dry-run 에서 네트워크를 부르려 했어요');
    if (!KEY) throw new Fatal('GOOGLE_TTS_API_KEY 환경 변수가 없어요. docs/voice-setup.md 를 보고 키를 넣은 뒤 새 세션에서 다시 실행하세요.');
    const res = await fetch(API + path, {
        method,
        headers: Object.assign({ 'X-Goog-Api-Key': KEY }, body ? { 'Content-Type': 'application/json; charset=utf-8' } : {}),
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(60000),
    });
    const text = await res.text();
    let json = null; try { json = JSON.parse(text); } catch (e) { json = null; }
    if (!res.ok) {
        const msg = redact((json && json.error && json.error.message) || text.slice(0, 300) || res.statusText);
        const err = new Error('HTTP ' + res.status + ': ' + msg);
        err.status = res.status; err.retryAfter = Number(res.headers.get('retry-after')) || 0;
        throw err;
    }
    return json;
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
const RETRY_STATUS = new Set([408, 429, 500, 502, 503, 504]);
async function withRetry(fn, label) {
    for (let attempt = 0; ; attempt++) {
        try { return await fn(); } catch (e) {
            if (e instanceof Fatal) throw e;
            if (e.status === 401 || e.status === 403 || (e.status === 400 && /API key/i.test(e.message || ''))) throw new Fatal(authHelp(e));
            const retryable = !e.status || RETRY_STATUS.has(e.status);   // status 없음 = 연결 끊김·시간 초과
            if (!retryable || attempt >= 6) throw e;
            const wait = e.retryAfter ? e.retryAfter * 1000 : Math.min(60000, 1000 * 2 ** attempt) + Math.random() * 500;
            console.log('  ↻ ' + label + ' — ' + redact(e.message || e) + ' → ' + Math.round(wait / 1000) + '초 뒤 다시 (' + (attempt + 1) + '/6)');
            await sleep(wait);
        }
    }
}
function authHelp(e) {
    return redact(e.message) + '\n  → 키가 틀렸거나, Cloud Text-to-Speech API가 꺼져 있거나, 키 제한에 이 API가 없거나, 결제 계정이 연결되지 않았어요. docs/voice-setup.md 1~5단계를 확인하세요.';
}
async function listVoices(languageCode) {
    const j = await withRetry(() => api('GET', '/voices?languageCode=' + encodeURIComponent(languageCode)), 'voices ' + languageCode);
    return ((j && j.voices) || []).filter(v => (v.languageCodes || []).includes(languageCode));
}
// speakingRate를 거부한 목소리(속도 없이 녹음). index.json의 norate로 다음 실행에 이어 준다
// — 새로 녹음할 것이 없는 실행(이어 하기·--prune·다른 언어와 함께)에서도 rates가 설정값으로 되돌아가지 않게
const noRateVoices = new Set();
async function synthesize(text, cfg, voiceName) {
    const audioConfig = Object.assign({}, AUDIO, noRateVoices.has(voiceName) ? {} : { speakingRate: cfg.speakingRate });
    try {
        const j = await api('POST', '/text:synthesize', { input: { text }, voice: { languageCode: cfg.languageCode, name: voiceName }, audioConfig });
        if (!j || !j.audioContent) throw new Error('응답에 audioContent가 없어요');
        return Buffer.from(j.audioContent, 'base64');
    } catch (e) {
        if (e.status === 400 && /speaking.?rate/i.test(e.message || '') && 'speakingRate' in audioConfig) {   // 동시에 여러 요청이 거절돼도 각자 다시 보낸다
            if (!noRateVoices.has(voiceName)) console.log('  ⚠ ' + voiceName + ' 이(가) speakingRate를 받지 않아 기본 속도로 녹음해요 (앱에서 재생 속도로 조절)');
            noRateVoices.add(voiceName);
            return synthesize(text, cfg, voiceName);
        }
        throw e;
    }
}

/* ═══════════════════ 목소리 고르기 ═══════════════════ */
function resolveVoices(lang, available) {
    const cfg = VOICES[lang], byName = new Map(available.map(v => [v.name, v])), picked = {}, notes = [];
    for (const slot of ['a', 'b']) {
        const want = WANT_GENDER[slot];
        let name = null;
        for (const n of cfg[slot]) {   // 앞 후보가 왜 빠졌는지만 알려 준다
            const v = byName.get(n);
            if (!v) notes.push(slot + ': ' + n + ' 없음');
            else if (v.ssmlGender && v.ssmlGender !== want) notes.push(slot + ': ' + n + ' 성별이 ' + v.ssmlGender);
            else if (n === picked.a) notes.push(slot + ': ' + n + ' 는 a와 같아서 건너뜀');
            else { name = n; break; }
        }
        if (!name) {
            const cands = available.filter(v => v.ssmlGender === want && v.name !== picked.a && AUTO_PICK_ORDER.includes(tierOf(v.name).id))
                .sort((x, y) => AUTO_PICK_ORDER.indexOf(tierOf(x.name).id) - AUTO_PICK_ORDER.indexOf(tierOf(y.name).id) || x.name.localeCompare(y.name));
            if (!cands.length) throw new Fatal(lang + ' ' + slot + ' 목소리를 찾지 못했어요(' + cfg.languageCode + ', ' + want + '). --list-voices 로 이름을 확인해 VOICES 설정을 고치세요.');
            name = cands[0].name;
            notes.push(slot + ': 후보가 없어 자동 선택 → ' + name);
        }
        picked[slot] = name;
    }
    return { voices: picked, notes };
}

/* ═══════════════════ 파일 ═══════════════════ */
const langDir = lang => new URL(lang + '/', AUDIO_DIR);
const mp3Path = (lang, id) => new URL(lang + '/' + id + '.mp3', AUDIO_DIR);
function hasFile(lang, id) { try { return statSync(mp3Path(lang, id)).size > 0; } catch (e) { return false; } }
function diskIds(lang) {
    try { return readdirSync(langDir(lang)).filter(f => /^[0-9a-f]{12}\.mp3$/.test(f)).map(f => f.slice(0, 12)); } catch (e) { return []; }
}
function readIndex(lang) { try { const j = JSON.parse(readFileSync(new URL('index.json', langDir(lang)), 'utf8')); return j && typeof j === 'object' ? j : null; } catch (e) { return null; } }
// 목소리 칸별 녹음 속도(앱은 재생 속도를 이 값 기준으로 맞춘다). speakingRate를 거부한 목소리는 기본 속도 1로 녹음됨
const ratesFor = (lang, voices) => ({ a: noRateVoices.has(voices.a) ? 1 : VOICES[lang].speakingRate, b: noRateVoices.has(voices.b) ? 1 : VOICES[lang].speakingRate });
// rev: 앱이 녹음 주소에 붙이는 ?v= — 목소리·속도가 바뀌거나 이미 있던 파일을 다시 녹음하면(gen) 바뀌어, 한 번 들은 사용자도 새 파일을 받는다
const revFor = (voices, rates, gen) => createHash('sha1').update(JSON.stringify([voices.a, voices.b, rates.a, rates.b, gen])).digest('hex').slice(0, 10);
function writeIndex(lang, voices, clips, gen) {
    const ids = [...new Set(clips.filter(c => hasFile(lang, c.id)).map(c => c.id))].sort();
    mkdirSync(langDir(lang), { recursive: true });
    const f = new URL('index.json', langDir(lang));
    const rates = ratesFor(lang, voices), norate = [...new Set([voices.a, voices.b].filter(v => noRateVoices.has(v)))];
    // rate: 예전 형식(칸 하나)과 맞추려고 a 칸 속도를 함께 적는다
    const out = Object.assign({ v: 1, voices, rate: rates.a, rates }, norate.length ? { norate } : {}, { gen, rev: revFor(voices, rates, gen), ids });
    writeFileSync(new URL('index.json.tmp', langDir(lang)), JSON.stringify(out) + '\n');
    renameSync(new URL('index.json.tmp', langDir(lang)), f);
    return ids.length;
}
function prune(lang, clips, really) {
    const keep = new Set(clips.map(c => c.id));
    let n = 0, bytes = 0;
    let files = []; try { files = readdirSync(langDir(lang)); } catch (e) { return { n, bytes }; }
    for (const f of files) {
        const orphan = (/^[0-9a-f]{12}\.mp3$/.test(f) && !keep.has(f.slice(0, 12))) || /\.tmp$/.test(f);
        if (!orphan) continue;
        const p = new URL(f, langDir(lang));
        n++; try { bytes += statSync(p).size; } catch (e) { }
        if (really) unlinkSync(p);
    }
    return { n, bytes };
}
const dirBytes = lang => diskIds(lang).reduce((s, id) => { try { return s + statSync(mp3Path(lang, id)).size; } catch (e) { return s; } }, 0);

/* ═══════════════════ 숫자 표시 ═══════════════════ */
const fmt = n => Math.round(n).toLocaleString('en-US');
const mb = b => (b / 1048576).toFixed(1) + ' MB';
const usd = n => '$' + n.toFixed(2);
const pad = (s, w, right) => { s = String(s); const len = [...s].length; return right ? ' '.repeat(Math.max(0, w - len)) + s : s + ' '.repeat(Math.max(0, w - len)); };
const estSec = (lang, text, rate) => [...text].length / CHARS_PER_SEC[lang] / (rate || 1) + PAD_SEC;
function costTable(charsByTier, title) {
    // 같은 SKU(WaveNet+Standard)는 무료 한도를 함께 쓴다
    const bySku = {};
    for (const [tid, chars] of Object.entries(charsByTier)) {
        const t = TIERS.find(x => x.id === tid) || tierOf('');
        const s = bySku[t.sku] || (bySku[t.sku] = { labels: [], chars: 0, free: t.free, usdPer1M: t.usdPer1M });
        s.labels.push(t.label); s.chars += chars;
    }
    let total = 0;
    console.log('\n' + title);
    console.log('  ' + pad('tier', 20) + pad('chars', 12, true) + pad('free/month', 14, true) + pad('est. cost', 14, true));
    for (const s of Object.values(bySku)) {
        const cost = Math.max(0, s.chars - s.free) * s.usdPer1M / 1e6; total += cost;
        console.log('  ' + pad(s.labels.join('+'), 20) + pad(fmt(s.chars), 12, true) + pad(fmt(s.free), 14, true) + pad(usd(cost), 14, true) + (s.chars > s.free ? '  ⚠ 무료 한도 초과' : '  (무료 한도 안)'));
    }
    console.log('  예상 요금 합계 ' + usd(total) + ' — 이번 달 다른 사용량이 없을 때. 요금·한도는 https://cloud.google.com/text-to-speech/pricing 에서 다시 확인');
}

/* ═══════════════════ 모드: 목소리 목록 ═══════════════════ */
async function runListVoices() {
    for (const lang of LANGS) {
        const cfg = VOICES[lang];
        const vs = await listVoices(cfg.languageCode);
        const rank = v => { const i = AUTO_PICK_ORDER.indexOf(tierOf(v.name).id); return i < 0 ? 99 : i; };
        vs.sort((x, y) => rank(x) - rank(y) || x.name.localeCompare(y.name));
        console.log('\n[' + lang + '] ' + cfg.languageCode + ' — 목소리 ' + vs.length + '개');
        for (const v of vs) {
            const mark = ['a', 'b'].map(s => { const i = cfg[s].indexOf(v.name); return i >= 0 ? s + '후보' + (i + 1) : ''; }).filter(Boolean).join(',');
            console.log('  ' + pad(v.name, 34) + pad(v.ssmlGender || '', 8) + pad(tierOf(v.name).label, 12) + (mark ? '← ' + mark : ''));
        }
        const r = resolveVoices(lang, vs);
        console.log('  ▶ 실제로 쓸 목소리: a = ' + r.voices.a + ' · b = ' + r.voices.b);
        r.notes.forEach(n => console.log('    · ' + n));
    }
}

/* ═══════════════════ 모드: 드라이런(네트워크 없음) ═══════════════════ */
function runDry(plan) {
    console.log('🔎 --dry-run: 네트워크 호출 없이 계산만 해요. 목소리는 설정의 1순위 후보 기준(실제 실행 때 목록으로 확인).\n');
    console.log('(clips=클립 수 · chars=과금 글자 수 · bytes=UTF-8 바이트 · have=이미 있는 파일 · todo=이번에 만들 클립)');
    console.log(pad('lang', 5) + pad('slot', 5) + pad('voice (1st choice)', 28) + pad('tier', 11) + pad('clips', 7, true) + pad('chars', 9, true) + pad('bytes', 10, true) + pad('have', 7, true) + pad('todo', 7, true) + pad('todo chars', 11, true));
    const fullByTier = {}, runByTier = {};
    let totClips = 0, totChars = 0, totBytes = 0, totSec = 0, runClips = 0, runSec = 0;
    for (const p of plan) {
        const cfg = VOICES[p.lang];
        for (const slot of ['a', 'b']) {
            const cs = p.clips.filter(c => c.slot === slot), todo = p.todo.filter(c => c.slot === slot);
            const voice = cfg[slot][0], tier = tierOf(voice);
            const chars = cs.reduce((s, c) => s + [...c.text].length, 0), bytes = cs.reduce((s, c) => s + Buffer.byteLength(c.text), 0);
            const tchars = todo.reduce((s, c) => s + [...c.text].length, 0);
            fullByTier[tier.id] = (fullByTier[tier.id] || 0) + chars; runByTier[tier.id] = (runByTier[tier.id] || 0) + tchars;
            totClips += cs.length; totChars += chars; totBytes += bytes; runClips += todo.length;
            totSec += cs.reduce((s, c) => s + estSec(p.lang, c.text, cfg.speakingRate), 0);
            runSec += todo.reduce((s, c) => s + estSec(p.lang, c.text, cfg.speakingRate), 0);
            console.log(pad(p.lang, 5) + pad(slot, 5) + pad(voice, 28) + pad(tier.label, 11) + pad(fmt(cs.length), 7, true) + pad(fmt(chars), 9, true) + pad(fmt(bytes), 10, true) + pad(fmt(cs.filter(c => hasFile(p.lang, c.id)).length), 7, true) + pad(fmt(todo.length), 7, true) + pad(fmt(tchars), 11, true));
        }
        const est = p.clips.reduce((s, c) => s + estSec(p.lang, c.text, cfg.speakingRate), 0);
        console.log(pad('', 10) + '→ ' + p.lang + ' 예상 길이 ' + (est / 60).toFixed(0) + '분 · 예상 용량 ' + mb(est * BYTES_PER_SEC) + (p.warnings.length ? ' · 참고 ' + p.warnings.length + '건: ' + p.warnings.join(' / ') : ''));
    }
    console.log('\n합계: 클립 ' + fmt(totClips) + '개 · 글자 ' + fmt(totChars) + ' · UTF-8 ' + fmt(totBytes) + '바이트 · 예상 ' + (totSec / 3600).toFixed(1) + '시간 분량 ≈ ' + mb(totSec * BYTES_PER_SEC) + ' (MP3 32 kbps)');
    console.log('이번 실행(이어 하기·--limit 반영): 새로 만들 클립 ' + fmt(runClips) + '개 ≈ ' + mb(runSec * BYTES_PER_SEC));
    costTable(fullByTier, '💰 전체 한 번 녹음할 때(1순위 목소리 기준)');
    if (runClips !== totClips) costTable(runByTier, '💰 이번 실행분');
    if (PRUNE) for (const p of plan) { const r = prune(p.lang, p.clips, false); if (r.n) console.log('--prune: ' + p.lang + ' 안 쓰는 파일 ' + r.n + '개(' + mb(r.bytes) + ')를 지울 예정 — 드라이런이라 지우지 않음'); }
}

/* ═══════════════════ 모드: 녹음 ═══════════════════ */
async function runGenerate(plan) {
    let fatal = null, anyFail = false;
    for (const p of plan) {
        if (fatal) break;
        const cfg = VOICES[p.lang];
        const avail = await listVoices(cfg.languageCode);
        const { voices, notes } = resolveVoices(p.lang, avail);
        // Chirp 3 HD는 speakingRate를 받으면 끝(예: "And you?", "¿Y tú?")을 자르거나 빠뜨리는 경우가 잦다(2026-09 시험, 같은 두 문장: 0.95일 때 20번 중 11번, 속도 없이 20번 중 0번).
        // 그래서 속도 없이(1) 녹음하고 앱이 재생 속도로 맞춘다 — index.json의 rates·norate에 1로 적힌다
        for (const slot of ['a', 'b']) if (tierOf(voices[slot]).id === 'chirp3hd') noRateVoices.add(voices[slot]);
        { const r0 = ratesFor(p.lang, voices); console.log('\n[' + p.lang + '] 목소리 a = ' + voices.a + ' · b = ' + voices.b + ' · 속도 a ' + r0.a + ' · b ' + r0.b); }
        notes.forEach(n => console.log('    · ' + n));
        const prev = readIndex(p.lang), existing = diskIds(p.lang);
        const pv = prev && prev.voices && typeof prev.voices === 'object' ? prev.voices : null;
        // 지난번에 speakingRate를 거부한 목소리는 이번에도 속도 없이 녹음하고, index.json의 속도도 그대로 둔다
        if (pv && Array.isArray(prev.norate)) for (const slot of ['a', 'b']) if (pv[slot] === voices[slot] && prev.norate.includes(voices[slot])) noRateVoices.add(voices[slot]);
        let gen = prev && Number.isInteger(prev.gen) && prev.gen >= 0 ? prev.gen : 0;
        const rates = ratesFor(p.lang, voices), pr = prev && prev.rates && typeof prev.rates === 'object' ? prev.rates : null;
        const voiceChanged = !!pv && (pv.a !== voices.a || pv.b !== voices.b);
        const rateChanged = !!pr && (pr.a !== rates.a || pr.b !== rates.b);   // 같은 목소리인데 VOICES의 speakingRate를 바꾼 경우
        if (existing.length && (voiceChanged || rateChanged)) {
            if (!REDO) {
                console.log('  ✋ 목소리나 속도가 지난번과 달라요(지난번 a=' + (pv && pv.a) + ', b=' + (pv && pv.b) + (pr ? ', 속도 a=' + pr.a + ' b=' + pr.b : '') + '). 섞이지 않게 이 언어는 건너뜀.\n     전부 새로: --redo --lang ' + p.lang + '  /  예전 것 유지: VOICES 설정을 되돌리기');
                anyFail = true; continue;
            }
            // --redo + 목소리·속도 변경: 예전 파일을 먼저 지워서, --limit 으로 일부만 다시 만들어도 두 목소리가 섞이지 않게 한다
            existing.forEach(id => unlinkSync(mp3Path(p.lang, id)));
            writeIndex(p.lang, voices, p.clips, ++gen);
            console.log('  🔁 목소리나 속도가 바뀌어 예전 파일 ' + existing.length + '개를 지우고 새로 녹음해요');
        }
        const todo = p.todo;
        // --redo 로 이미 있는 파일을 덮어쓸 때: 먼저 버전(gen → rev)을 올려 둔다. 같은 목소리로 다시 녹음해도 한 번 들은 사용자가
        // 새 파일을 받고, 중간에 끊겨도 옛 주소의 캐시가 남지 않게
        if (REDO && todo.some(c => hasFile(p.lang, c.id))) { writeIndex(p.lang, voices, p.clips, ++gen); console.log('  🔁 다시 녹음 → 녹음 버전 gen ' + gen); }
        console.log('  클립 ' + p.clips.length + '개 중 새로 만들 것 ' + todo.length + '개' + (REDO ? ' (--redo)' : '') + (LIMIT !== Infinity ? ' (--limit ' + LIMIT + ')' : ''));
        mkdirSync(langDir(p.lang), { recursive: true });
        let done = 0, failed = 0, chars = 0, bytes = 0, next = 0, consecutiveFail = 0, lastLog = 0;
        const t0 = Date.now(), failures = [];
        let lastCount = -1;
        const progress = force => {
            const now = Date.now();
            if ((!force && now - lastLog < 3000) || done + failed === lastCount) return;
            lastLog = now; lastCount = done + failed;
            const rate = done / Math.max(1, (now - t0) / 1000), left = todo.length - done - failed;
            console.log('  [' + p.lang + '] ' + (done + failed) + '/' + todo.length + ' (' + Math.floor((done + failed) / Math.max(1, todo.length) * 100) + '%) · 실패 ' + failed + ' · ' + rate.toFixed(1) + '개/초' + (left > 0 && rate > 0 ? ' · 남은 시간 약 ' + Math.ceil(left / rate / 60) + '분' : ''));
        };
        const worker = async () => {
            while (!fatal && next < todo.length) {
                const c = todo[next++];
                const voice = voices[c.slot];
                try {
                    const buf = await withRetry(() => synthesize(c.text, cfg, voice), p.lang + ' ' + c.id);
                    const tmp = new URL(p.lang + '/' + c.id + '.mp3.tmp', AUDIO_DIR);
                    writeFileSync(tmp, buf); renameSync(tmp, mp3Path(p.lang, c.id));
                    done++; chars += [...c.text].length; bytes += buf.length; consecutiveFail = 0;
                } catch (e) {
                    if (e instanceof Fatal) { fatal = e; return; }
                    failed++; consecutiveFail++; failures.push(c);
                    console.log('  ✗ ' + p.lang + ' ' + c.slot + ' ' + c.id + ' ' + JSON.stringify(c.text.slice(0, 60)) + ' — ' + redact(e.message || e));
                    if (consecutiveFail >= 10) fatal = new Fatal('연속 10번 실패해서 멈췄어요. 위 오류 메시지를 확인하세요.');
                }
                progress(false);
            }
        };
        await Promise.all(Array.from({ length: CONC }, worker));
        progress(true);
        const n = writeIndex(p.lang, voices, p.clips, gen);
        console.log('  ✔ ' + p.lang + ': 이번에 ' + done + '개 녹음(' + fmt(chars) + '자, ' + mb(bytes) + ')' + (failed ? ' · 실패 ' + failed + '개(다시 실행하면 이어서 시도)' : '') + ' · index.json ' + n + '/' + p.clips.length + '개 · 폴더 ' + mb(dirBytes(p.lang)));
        if (failed) anyFail = true;
        if (PRUNE && !fatal) { const r = prune(p.lang, p.clips, true); console.log('  🧹 --prune: 안 쓰는 파일 ' + r.n + '개 삭제(' + mb(r.bytes) + ')'); }
    }
    if (fatal) { console.error('\n⛔ ' + redact(fatal.message)); process.exit(1); }
    console.log(anyFail ? '\n일부가 끝나지 않았어요. 같은 명령을 다시 실행하면 없는 파일만 이어서 만들어요.' : '\n🎉 끝! ' + fileURLToPath(AUDIO_DIR) + ' 를 확인하세요.');
    if (anyFail) process.exitCode = 1;
}

/* ═══════════════════ 시작 ═══════════════════ */
async function main() {
    if (LIST_VOICES) { if (DRY) { console.error('--list-voices 는 네트워크가 필요해서 --dry-run 과 함께 쓸 수 없어요'); process.exit(2); } return runListVoices(); }
    if (!DRY && !KEY) { console.error('GOOGLE_TTS_API_KEY 환경 변수가 없어요. docs/voice-setup.md 를 보고 키를 넣은 뒤 새 세션에서 다시 실행하세요.\n(네트워크 없이 계산만: node tools/tts/generate.mjs --dry-run)'); process.exit(2); }
    const plan = LANGS.map(lang => {
        const { clips, warnings } = collectLang(lang);
        const todoAll = REDO ? clips.slice() : clips.filter(c => !hasFile(lang, c.id));
        return { lang, clips, warnings, todoAll, todo: todoAll.slice(0, LIMIT) };
    });
    if (DRY) return runDry(plan);
    return runGenerate(plan);
}
main().catch(e => { console.error('⛔ ' + redact(e && e.message || e)); process.exit(1); });
