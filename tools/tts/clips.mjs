// 랭귀지 스타터 — 미리 녹음할 음성 클립 목록 만들기 (의존성 없음, node 18+)
//
//   node tools/tts/clips.mjs              언어·목소리(slot)·출처별 클립 개수 요약
//   node tools/tts/clips.mjs --list zh    zh 클립을 "id<TAB>slot<TAB>text" 로 전부 출력(검수용)
//   node tools/tts/clips.mjs --test       clipId 테스트 벡터 확인(node 버전 = 브라우저 조각)
//
// 클립 = { lang, slot: 'a'|'b', text, id, from: [출처...] }
//   slot 'b' = 대화의 두 번째 목소리(index.html tuneFor()에서 speaker 'B'·'D'가 voiceCache.b 를 씀), 나머지는 전부 'a'.
//   text 는 앱이 speak()/speakSeq()에 넘기는 문자열과 글자 하나까지 똑같아야 한다(공백·문장부호 포함, 다듬지 않음).
//
// 어떤 문자열을 모으는지는 language-teacher/index.html 의 speak(/speakSeq( 호출부를 그대로 따라간다:
//   word        words[] — 단어 목록(▶/🐢/뜻 가리기 탭: w.tts || 원문), 복습 카드(c.tts || c.native, 자동 재생·뒤집기: c.native), 짝 맞추기
//   sentence    keySentences[] — ▶/🐢, 🎤 말하기 창(openSpeak), 보스 문장, 오늘의 한 문장, 결과 화면 떠올리기, 문장 복습 카드
//   dialogue    dialogue.turns[] — 말풍선 탭·전체 듣기·파트 듣기·역할극(상대 대사 speakSeq, 내 대사 openSpeak)
//   grammar     grammar[].examples[] — ▶/🐢, ✋ 확인 문제 정답 읽기
//   quiz.*      quiz[] — listen/tone 문제 소리(listen), 배열 문제 토큰 탭(token)·정답 문장(tokens.join(joiner)),
//               선택 문제 정답 보기(한글이 없을 때만 choices[answer])
//   deq         (en) deq.key[]/deq.repeat[] — Daily English Quest 가져오기로 생기는 문장 복습 카드
//   story       stories[].sentences[] — 문장 탭·전체 듣기
//   sample      LANGS[code].sampleWord — 설정의 말하기 속도·목소리 미리 듣기
//   trainer     훈련소 탭(index.html 상수): 성조 TONE_BANK, 동사 SOUND_SETS + "대명사 + 활용형", 가나 표·게임·헷갈리는 글자,
//               프랑스어 FR_VOWELS 예(쉼표로 나눔)·FR_LIAISON·FR_SOUND_POOL, 영어 EAR_SETS 단어·EAR_LINKS(say, en)
// 모으지 않는 것(실행 중 사용자 상태에 따라 달라짐 → 앱은 기기 음성으로 대체해야 함):
//   🎤 채점 결과의 ✗ 칩(data-unit: 소문자·악센트 제거·축약 풀기 등으로 가공된 조각), 예전 앱/옛 데이터에서 넘어온 복습 카드 문장,
//   한글(자모 포함)이 섞인 문자열(예: 선택 문제 보기 'ㅃ'·'ㅅ' — 앱의 /[가-힣]/ 검사가 자모는 거르지 못해 지금은 외국어 목소리로 읽힘).
import { readFileSync, existsSync, realpathSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import vm from 'node:vm';

export const ROOT = new URL('../../', import.meta.url);
export const APP_DIR = new URL('language-teacher/', ROOT);
export const LANG_CODES = ['en', 'zh', 'es', 'ja', 'fr'];

// index.html 의 LANGS 에서 읽지 못할 때 쓰는 기본값(같은 내용)
const LANG_DEFAULTS = {
    en: { nativeField: 'en', joiner: ' ', sampleWord: 'Hello', trainerTab: 'ear' },
    zh: { nativeField: 'hanzi', joiner: '', sampleWord: '你好', trainerTab: 'tone' },
    es: { nativeField: 'es', joiner: ' ', sampleWord: 'Hola', trainerTab: 'verb' },
    ja: { nativeField: 'ja', joiner: '', sampleWord: 'こんにちは', trainerTab: 'kana' },
    fr: { nativeField: 'fr', joiner: ' ', sampleWord: 'Bonjour', trainerTab: 'sound' },
};

/* ───────────── clipId: FNV-1a 64비트(UTF-8 바이트) → 앞 12자리 16진수 ─────────────
   clipId(slot, text) = fnv1a64(utf8(slot + '|' + text)) 를 16자리 16진수(0 채움)로 쓴 것의 앞 12자리(상위 48비트).
   브라우저에서는 아래 BROWSER_CLIP_ID(BigInt 없이 32비트 두 조각)를 그대로 붙여 쓰면 같은 값이 나온다. */
const FNV_OFFSET = 0xcbf29ce484222325n, FNV_PRIME = 0x100000001b3n, MASK64 = 0xffffffffffffffffn;
export function fnv1a64Hex(str) {
    let h = FNV_OFFSET;
    for (const b of new TextEncoder().encode(str)) h = ((h ^ BigInt(b)) * FNV_PRIME) & MASK64;
    return h.toString(16).padStart(16, '0');
}
export function clipId(slot, text) { return fnv1a64Hex(slot + '|' + text).slice(0, 12); }

// 브라우저용(ES5, BigInt 불필요). 이 문자열을 앱 <script>에 그대로 붙여 넣는다.
export const BROWSER_CLIP_ID = `// 음성 클립 이름: FNV-1a 64비트(UTF-8) 앞 12자리 — tools/tts/clips.mjs 의 clipId()와 같은 값
function clipId(slot, text) {
    var bytes = new TextEncoder().encode(slot + '|' + text);
    var hi = 0xcbf29ce4, lo = 0x84222325;              // 64비트 offset basis를 32비트 두 조각으로
    for (var i = 0; i < bytes.length; i++) {
        lo = (lo ^ bytes[i]) >>> 0;
        // h * 0x100000001b3 = h * 0x1b3 + (h << 40)  (mod 2^64)
        var l = lo * 0x1b3;                             // < 2^41, 정확한 정수
        var carry = Math.floor(l / 4294967296);
        hi = (Math.imul(hi, 0x1b3) + carry + ((lo << 8) >>> 0)) >>> 0;
        lo = l >>> 0;
    }
    return ('00000000' + hi.toString(16)).slice(-8) + ('0000' + (lo >>> 16).toString(16)).slice(-4);
}`;

// 테스트 벡터: fnv1a64 표준값 + clipId 값(브라우저 조각과 node 모두 이 값이 나와야 함)
export const TEST_VECTORS = {
    fnv1a64: [['', 'cbf29ce484222325'], ['a', 'af63dc4c8601ec8c'], ['foobar', '85944171f73967e8']],
    clipId: [
        ['a', 'Hello', 'c390128b4c43'],
        ['b', 'Hello', '078dda0e3f4a'],
        ['a', '你好', '2c2d098e331a'],
        ['a', 'こんにちは', 'aecd692d3447'],
        ['a', "C'est un ami ? Oui — très « bien » !", '820965b8d4f5'],
        ['b', '¿Cómo estás? 😀', '3e3c7b25cdbd'],
        ['a', '', '089c4607b545'],
    ],
};

/* ───────────── 데이터 읽기 ───────────── */
function runScript(file, win) {
    const ctx = vm.createContext({ window: win });
    vm.runInContext(readFileSync(file, 'utf8'), ctx, { filename: file.pathname || String(file) });
}
// data-xx.js / stories-xx.js 는 window.XX_DATA = {...} 를 정의한다. 이름이 바뀌어도 되도록 새로 생긴 전역을 집는다.
function loadGlobal(fileName, preferName) {
    const file = new URL(fileName, APP_DIR);
    if (!existsSync(file)) throw new Error('파일이 없어요: language-teacher/' + fileName);
    const win = {};
    runScript(file, win);
    if (preferName && win[preferName]) return win[preferName];
    const keys = Object.keys(win);
    if (keys.length !== 1) throw new Error(fileName + ': 전역 변수를 하나로 정하지 못했어요 (' + keys.join(', ') + ')');
    return win[keys[0]];
}

// index.html 에서 `const NAME = <리터럴>;` 을 찾아 값으로 돌려준다(없으면 undefined). 파일은 읽기만 한다.
let HTML_CACHE = null;
function indexHtml() {
    if (HTML_CACHE === null) {
        const f = new URL('index.html', APP_DIR);
        HTML_CACHE = existsSync(f) ? readFileSync(f, 'utf8') : '';
    }
    return HTML_CACHE;
}
export function readConst(name, extraCtx) {
    const src = indexHtml();
    const m = new RegExp('(^|\\n)\\s*const ' + name + ' = ').exec(src);
    if (!m) return undefined;
    let i = m.index + m[0].length;
    const open = src[i], close = open === '[' ? ']' : open === '{' ? '}' : null;
    if (!close) return undefined;
    let depth = 0, q = null;
    for (let j = i; j < src.length; j++) {
        const c = src[j];
        if (q) { if (c === '\\') j++; else if (c === q) q = null; continue; }
        if (c === '"' || c === "'" || c === '`') { q = c; continue; }
        if (c === '/' && src[j + 1] === '/') { j = src.indexOf('\n', j); if (j < 0) break; continue; }
        if (c === '/' && src[j + 1] === '*') { j = src.indexOf('*/', j + 2) + 1; if (j <= 0) break; continue; }
        if (c === open) depth++;
        else if (c === close && --depth === 0) {
            try { return vm.runInNewContext('(' + src.slice(i, j + 1) + ')', Object.assign({}, extraCtx || {})); }
            catch (e) { return undefined; }
        }
    }
    return undefined;
}

export function langInfo(code) {
    const L = readConst('LANGS', { DATA_VER: '' });
    const fromHtml = L && L[code] ? L[code] : null;
    const d = LANG_DEFAULTS[code];
    if (!d) throw new Error('모르는 언어 코드: ' + code);
    if (!fromHtml) return Object.assign({ code, dataGlobal: null, storyGlobal: null, fromHtml: false }, d);
    return {
        code, fromHtml: true,
        nativeField: fromHtml.nativeField || d.nativeField,
        joiner: typeof fromHtml.joiner === 'string' ? fromHtml.joiner : d.joiner,
        sampleWord: fromHtml.sampleWord || d.sampleWord,
        trainerTab: fromHtml.trainerTab || d.trainerTab,
        dataGlobal: fromHtml.dataGlobal || null, storyGlobal: fromHtml.storyGlobal || null,
    };
}

/* ───────────── 클립 모으기 ───────────── */
const HANGUL = /[가-힣]/;                                         // index.html 과 같은 조건(정답 보기 읽기)
const HANGUL_ANY = /[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff]/;   // 완성형 + 자모
const SLOT_B_SPEAKERS = new Set(['B', 'D']);   // tuneFor(): B·D → 두 번째 목소리(b), A·C·E·N → 기본 목소리(a)

export function collectLang(code) {
    const L = langInfo(code);
    const data = loadGlobal('data-' + code + '.js', L.dataGlobal);
    let stories = null;
    try { stories = loadGlobal('stories-' + code + '.js', L.storyGlobal); } catch (e) { stories = null; }
    const nt = item => (item && item[L.nativeField] != null ? String(item[L.nativeField]) : '');   // index.html nativeText()
    const map = new Map();
    const warnings = [];
    const skipped = new Set();
    const add = (slot, text, from) => {
        if (typeof text !== 'string' || !text) return;   // speak()/speakSeq()는 빈 문자열을 읽지 않는다
        // 한글이 섞인 문자열은 외국어 목소리로 읽을 수 없어 뺀다. 앱의 정답 읽기 조건 /[가-힣]/ 는 완성형만 걸러서
        // 'ㅃ'·'ㅅ' 같은 자모 보기는 그대로 speak()에 넘어간다 → 이런 건 녹음하지 않고 앱이 기기 음성으로 대체(또는 건너뛰기).
        if (HANGUL_ANY.test(text)) { if (!skipped.has(text)) { skipped.add(text); warnings.push('한글 포함이라 녹음 안 함(' + from + '): ' + JSON.stringify(text)); } return; }
        const key = slot + '\u0000' + text;
        let c = map.get(key);
        if (!c) { c = { lang: code, slot, text, id: clipId(slot, text), from: [] }; map.set(key, c); }
        if (!c.from.includes(from)) c.from.push(from);
    };

    for (const u of data.units || []) for (const l of u.lessons || []) {
        for (const w of l.words || []) { add('a', nt(w), 'word'); if (w.tts) add('a', String(w.tts), 'word.tts'); }
        for (const s of l.keySentences || []) add('a', nt(s), 'sentence');
        for (const t of (l.dialogue && l.dialogue.turns) || []) add(SLOT_B_SPEAKERS.has(t.speaker) ? 'b' : 'a', nt(t), 'dialogue');
        for (const g of l.grammar || []) for (const ex of g.examples || []) add('a', nt(ex), 'grammar');
        for (const q of l.quiz || []) {
            const itemText = nt(q);
            if (q.type === 'arrange') {
                const toks = Array.isArray(q.tokens) ? q.tokens.map(String) : [];
                toks.forEach(t => add('a', t, 'quiz.token'));
                if (toks.length) add('a', toks.join(L.joiner), 'quiz.arrange');
                continue;
            }
            if ((q.type === 'listen' || q.type === 'tone') && itemText) { add('a', itemText, 'quiz.listen'); continue; }
            const ans = Array.isArray(q.choices) ? q.choices[q.answer] : undefined;
            if (typeof ans === 'string' && !HANGUL.test(ans)) add('a', ans, 'quiz.answer');
        }
        if (l.deq) for (const s of [].concat(l.deq.key || [], l.deq.repeat || [])) add('a', s && s.en ? String(s.en) : '', 'deq');
    }
    for (const s of (stories && stories.stories) || []) for (const x of s.sentences || []) add('a', nt(x), 'story');
    add('a', L.sampleWord, 'sample');
    addTrainer(L.trainerTab, add, warnings);

    const clips = [...map.values()];
    const ids = new Map();
    for (const c of clips) {
        const k = c.slot + ':' + c.id;
        if (ids.has(k)) throw new Error('clipId 충돌(' + code + '): ' + JSON.stringify(ids.get(k)) + ' vs ' + JSON.stringify(c.text));
        ids.set(k, c.text);
        if (c.text !== c.text.trim()) warnings.push('앞뒤 공백: ' + JSON.stringify(c.text));
        if (/[\r\n]/.test(c.text)) warnings.push('줄바꿈 포함: ' + JSON.stringify(c.text));
        if (Buffer.byteLength(c.text, 'utf8') > 4800) warnings.push('너무 긴 문장(5000바이트 제한): ' + c.text.slice(0, 40));
    }
    return { lang: code, clips, warnings, fromHtml: L.fromHtml };
}

function addTrainer(tab, add, warnings) {
    const need = (name, v) => { if (v === undefined) warnings.push('index.html 에서 ' + name + ' 를 찾지 못해 훈련소 클립 일부를 뺐어요'); return v; };
    if (tab === 'tone') {
        const bank = need('TONE_BANK', readConst('TONE_BANK')) || [];
        bank.forEach(set => set.forEach(x => add('a', x.h, 'trainer')));
    } else if (tab === 'verb') {
        const sets = need('SOUND_SETS', readConst('SOUND_SETS')) || [];
        sets.forEach(s => (s.words || []).forEach(w => add('a', w, 'trainer')));
        const P = need('PRONOUNS', readConst('PRONOUNS')), V = need('VERB_BANK', readConst('VERB_BANK'));
        // renderVerbTrainer(): spoken = (pi === 2 ? 'él ' : pi === 5 ? 'ellos ' : PRONOUNS[pi] + ' ') + forms[pi]
        if (P && V) V.forEach(v => (v.forms || []).forEach((f, pi) => add('a', (pi === 2 ? 'él ' : pi === 5 ? 'ellos ' : P[pi] + ' ') + f, 'trainer')));
    } else if (tab === 'kana') {
        const rows = [].concat(need('KANA_SEION', readConst('KANA_SEION')) || [], need('KANA_DAKUON', readConst('KANA_DAKUON')) || []);
        rows.forEach(r => (r.cells || []).forEach(c => { if (c) { add('a', c.h, 'trainer'); add('a', c.k, 'trainer'); } }));
        (need('KANA_CONFUSE_SETS', readConst('KANA_CONFUSE_SETS')) || []).forEach(s => (s.chars || []).forEach(ch => add('a', ch, 'trainer')));
    } else if (tab === 'sound') {
        // FR_VOWELS: speakSeq(v.ex.split(',').map(x => x.trim()))
        (need('FR_VOWELS', readConst('FR_VOWELS')) || []).forEach(v => String(v.ex || '').split(',').map(x => x.trim()).forEach(x => add('a', x, 'trainer')));
        (need('FR_LIAISON', readConst('FR_LIAISON')) || []).forEach(x => add('a', x.fr, 'trainer'));
        (need('FR_SOUND_POOL', readConst('FR_SOUND_POOL')) || []).forEach(x => add('a', x.fr, 'trainer'));
    } else if (tab === 'ear') {
        (need('EAR_SETS', readConst('EAR_SETS')) || []).forEach(s => (s.pairs || []).forEach(p => { add('a', p[0], 'trainer'); add('a', p[2], 'trainer'); }));
        // 🔊 speak(x.say || x.en, 1) · 🐢 speak(x.en, 0.6)
        (need('EAR_LINKS', readConst('EAR_LINKS')) || []).forEach(x => { add('a', x.say || x.en, 'trainer'); add('a', x.en, 'trainer'); });
    }
}

// 언어별 클립 목록: { en: [...], zh: [...] } (langs 생략 시 5개 언어 전부)
export function collectClips(langs) {
    const out = {};
    for (const code of langs || LANG_CODES) out[code] = collectLang(code).clips;
    return out;
}

/* ───────────── 명령줄 ───────────── */
function runTests() {
    let bad = 0;
    const ctx = vm.createContext({ TextEncoder, Math });
    vm.runInContext(BROWSER_CLIP_ID, ctx);
    const browserClipId = ctx.clipId;
    for (const [s, want] of TEST_VECTORS.fnv1a64) {
        const got = fnv1a64Hex(s); const ok = got === want; if (!ok) bad++;
        console.log((ok ? 'ok  ' : 'FAIL') + ' fnv1a64(' + JSON.stringify(s) + ') = ' + got + (ok ? '' : ' (기대 ' + want + ')'));
    }
    for (const [slot, text, want] of TEST_VECTORS.clipId) {
        const n = clipId(slot, text), b = browserClipId(slot, text);
        const ok = n === want && b === want; if (!ok) bad++;
        console.log((ok ? 'ok  ' : 'FAIL') + ' clipId(' + JSON.stringify(slot) + ', ' + JSON.stringify(text) + ') node=' + n + ' browser=' + b + (ok ? '' : ' (기대 ' + want + ')'));
    }
    // 실제 클립 전부에서 node 버전과 브라우저 조각이 같은지
    let n = 0;
    for (const code of LANG_CODES) for (const c of collectLang(code).clips) { n++; if (browserClipId(c.slot, c.text) !== c.id) { bad++; console.log('FAIL 불일치', code, c.slot, JSON.stringify(c.text)); } }
    console.log((bad ? 'FAIL ' : 'ok   ') + '실제 클립 ' + n + '개 전부 node = 브라우저 조각' + (bad ? ' — 실패 ' + bad + '개' : ''));
    process.exit(bad ? 1 : 0);
}

function summary() {
    let total = 0;
    for (const code of LANG_CODES) {
        const { clips, warnings, fromHtml } = collectLang(code);
        const by = {};
        for (const c of clips) for (const f of c.from) by[f] = (by[f] || 0) + 1;
        const a = clips.filter(c => c.slot === 'a').length, b = clips.length - a;
        total += clips.length;
        console.log(code + ': ' + clips.length + '개 (a ' + a + ' · b ' + b + ')' + (fromHtml ? '' : ' [index.html LANGS를 못 읽어 기본값 사용]'));
        console.log('    출처(겹치면 중복 집계): ' + Object.entries(by).map(([k, v]) => k + ' ' + v).join(' · '));
        warnings.forEach(w => console.log('    ⚠ ' + w));
    }
    console.log('합계 ' + total + '개');
}

if (process.argv[1] && import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href) {
    const args = process.argv.slice(2);
    if (args.includes('--test')) runTests();
    else if (args.includes('--list')) {
        const code = args[args.indexOf('--list') + 1];
        if (!LANG_CODES.includes(code)) { console.error('사용법: node tools/tts/clips.mjs --list <' + LANG_CODES.join('|') + '>'); process.exit(2); }
        for (const c of collectLang(code).clips) console.log(c.id + '\t' + c.slot + '\t' + c.text);
    } else summary();
}
