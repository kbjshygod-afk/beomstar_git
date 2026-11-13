'use strict';
// 🤖 AI 튜터 중계 함수(Firebase Cloud Functions 2세대).
//  - 앱 → 이 함수 → Gemini / ChatGPT. 키는 Secret Manager에만 있고 앱·저장소에는 없다.
//  - 구글 로그인한 사람만(ID 토큰 확인), 하루 한도(기본 30번) 안에서만. invoker 'public'은 누구나 주소를 부를 수 있다는 뜻일 뿐 — 로그인 확인은 아래 코드가 한다.
//  - 학습자 글은 저장하지 않는다. 한도 세는 칸(tutorUsage)에는 횟수만 남는다.
const { onRequest } = require('firebase-functions/v2/https');
const { defineSecret, defineString } = require('firebase-functions/params');
const admin = require('firebase-admin');
const { getFirestore, FieldValue, Timestamp } = require('firebase-admin/firestore');   // firebase-admin 13부터는 admin 객체 밑이 아니라 이 묶음에서 가져온다
const core = require('./tutor-core');

admin.initializeApp();
const db = getFirestore();

const GEMINI_API_KEY = defineSecret('GEMINI_API_KEY');
const OPENAI_API_KEY = defineSecret('OPENAI_API_KEY');
const GEMINI_MODEL = defineString('TUTOR_GEMINI_MODEL', { default: 'gemini-2.5-flash' });
const OPENAI_MODEL = defineString('TUTOR_OPENAI_MODEL', { default: 'gpt-4o-mini' });
const DAILY_LIMIT = defineString('TUTOR_DAILY_LIMIT', { default: '30' });
const ORIGINS = ['https://kbjshygod-afk.github.io', 'http://127.0.0.1:8765', 'http://localhost:8765'];

// CORS는 라이브러리 설정에 맡기지 않고 직접 정한다(규칙은 tutor-core.js의 corsHeaders — 단위 시험이 있음).
// 참고: Firebase 에뮬레이터는 개발 편의로 모든 사이트를 허용하도록 만들어져 있어, 이 제한은 에뮬레이터가 아니라 실제 배포에서 적용된다.
function cors(req, res) {
    res.set('Vary', 'Origin');
    const h = core.corsHeaders(req.get('origin'), ORIGINS);
    Object.keys(h).forEach(k => res.set(k, h[k]));
}
function send(res, code, obj) { res.status(code).json(obj); }

exports.tutor = onRequest(
    { region: 'asia-northeast3', invoker: 'public', secrets: [GEMINI_API_KEY, OPENAI_API_KEY], maxInstances: 5, timeoutSeconds: 60, memory: '256MiB' },
    async (req, res) => {
        cors(req, res);
        if (req.method === 'OPTIONS') return res.status(204).send('');
        if (req.method !== 'POST') return send(res, 405, { error: 'POST만 받아요' });

        // 1) 로그인 확인
        const m = /^Bearer (.+)$/.exec(req.get('authorization') || '');
        if (!m) return send(res, 401, { error: '로그인이 필요해요' });
        let uid;
        try { uid = (await admin.auth().verifyIdToken(m[1])).uid; }
        catch (e) { return send(res, 401, { error: '로그인이 만료됐어요. 다시 로그인해 주세요' }); }

        // 2) 입력 검증
        const v = core.validateRequest(req.body);
        if (!v.ok) return send(res, v.code, { error: v.error });

        // 3) 하루 한도: 호출 전에 1 올리고, 전부 실패하면 되돌린다
        const limit = Math.max(1, parseInt(DAILY_LIMIT.value(), 10) || 30);
        const ref = db.collection('tutorUsage').doc(uid + '_' + core.dayKey());
        let used;
        try {
            used = await db.runTransaction(async t => {
                const s = await t.get(ref), n = s.exists ? (s.data().n || 0) : 0;
                if (n >= limit) return -1;
                t.set(ref, { uid, n: n + 1, day: core.dayKey(), at: FieldValue.serverTimestamp(), expireAt: Timestamp.fromMillis(Date.now() + 60 * 86400000) }, { merge: true });   // expireAt: Firestore TTL이 약 2달 뒤 지운다(docs/tutor-setup.md 5단계)
                return n + 1;
            });
        } catch (e) { console.error('tutor usage fail', e && e.code, e && e.message); return send(res, 500, { error: '잠시 뒤 다시 해 주세요' }); }   // 글은 남기지 않고 오류 종류만
        if (used < 0) return send(res, 429, { error: '오늘 쓸 수 있는 AI 튜터 횟수(' + limit + '번)를 다 썼어요. 내일 다시 만나요!', remaining: 0 });

        // 4) AI 호출(고른 쪽이 한도·서버 오류면 키가 있는 다른 쪽으로)
        try {
            const out = await core.answer(fetch, {
                gemini: { key: GEMINI_API_KEY.value(), model: GEMINI_MODEL.value() },
                openai: { key: OPENAI_API_KEY.value(), model: OPENAI_MODEL.value() },
            }, v.value);
            return send(res, 200, { reply: out.reply, engine: out.engine, fellBack: out.fellBack, remaining: Math.max(0, limit - used) });
        } catch (e) {
            await ref.set({ n: FieldValue.increment(-1) }, { merge: true }).catch(re => console.error('tutor refund failed', re && (re.code || re.message)));   // 실패한 호출은 한도에서 빼 준다(이것마저 실패하면 기록만)
            console.error('tutor fail', e && e.status, e && e.message);   // 학습자 글은 남기지 않는다
            if (e && e.status === 503) return send(res, 503, { error: 'AI 튜터가 아직 준비되지 않았어요' });
            return send(res, 502, { error: 'AI가 지금 답하지 못해요. 잠시 뒤 다시 해 주세요' });
        }
    }
);
