# 🤖 AI 튜터 켜기

앱 안 **놀이 탭 → 🤖 AI 튜터**는 두 가지 방식으로 움직여요. **지금 켜져 있는 것은 ①번(무료)** 이에요.

| | ① 내 키 방식 (기본 · 무료) | ② 중계 방식 (선택 · 유료 요금제 필요) |
|---|---|---|
| 준비 | 구글 AI 스튜디오의 무료 Gemini 키를 앱에 한 번 붙여 넣기 | Firebase Blaze(카드 등록) + 함수 배포 + `tutorUrl` 적기 |
| AI | Gemini | Gemini · ChatGPT 고르기 |
| 로그인 | 필요 없음 | 구글 로그인 필요(하루 30번) |
| 키가 있는 곳 | 내 기기의 브라우저 저장소 | 구글 클라우드 비밀 저장소 |

## ① 내 키 방식 (무료) — 쓰는 법

1. 앱 → 놀이 탭 → **🤖 AI 튜터** → **구글 AI 스튜디오 열기**(https://aistudio.google.com/apikey)
2. 구글 계정으로 들어가 **API 키 만들기** → 키 복사 (카드 등록 없음)
3. 앱으로 돌아와 붙여 넣고 **저장**. 앱이 구글에 키가 맞는지 확인한 뒤 저장해요.

알아 둘 것:

- **기기마다 따로** 넣어요. 키는 학습 기록과 다른 칸(`lang_starter_tutor_key`)에 있어서 구글 로그인을 해도 클라우드·백업 파일에 들어가지 않아요.
- 지우기: AI 튜터 화면의 **🔑 키 → 키 지우기**. 키가 새어 나간 것 같으면 AI 스튜디오에서 그 키를 지우고 새로 만들어요.
- 무료 한도는 구글이 정하고 바뀔 수 있어요. 넘으면 앱이 "무료 한도를 넘었어요"라고 알려 줘요.
- 무료 키로 보낸 글은 구글이 약관에 따라 서비스 개선에 쓸 수 있어요. 개인정보는 적지 마세요.
- 모델은 `gemini-flash-latest` → `gemini-2.5-flash` → `gemini-2.0-flash` 순으로 써 보고, 되는 것을 그 방문 동안 기억해요(`index.html`의 `TUTOR_MODELS`).
- (선택) 키를 더 안전하게: Google Cloud 콘솔 → API 및 서비스 → 사용자 인증 정보 → 그 키 → **웹사이트 제한**에 `https://kbjshygod-afk.github.io/*` 를 넣으면 다른 사이트에서는 그 키가 통하지 않아요.
- **ChatGPT도 쓰려면**: API 키 대신 ChatGPT 구독으로 로그인한 내 컴퓨터의 Codex CLI를 연결해요 → [`docs/tutor-bridge.md`](tutor-bridge.md)

---

# ② 중계 방식 (선택 — 유료 요금제를 쓸 때만)

`cloud-config.js`의 `tutorUrl`에 https 주소를 적으면 ①번 대신 이 방식으로 바뀌어요. 앱은 AI 키를 갖지 않고, 키는 구글 클라우드의 비밀 저장소(Secret Manager)에만 두며,
**중계 함수**(`functions/`)가 대신 AI를 불러요. 구글 로그인한 사람만 쓰고, 한 사람당 **하루 30번**(바꿀 수 있어요)까지예요.

## 미리 알아 둘 것 (비용)

| 항목 | 내용 |
|---|---|
| Firebase 요금제 | **Blaze(종량제, 카드 등록)** 가 필요해요. 클라우드 함수는 무료(Spark) 요금제에서는 배포가 안 돼요. Blaze도 무료 사용량이 넉넉해서 이 앱 규모에서는 함수 자체 비용이 거의 0원이에요. |
| AI 호출 비용 | Gemini·ChatGPT 사용량만큼 **내 계정에 청구**돼요. 한 번에 보내는 글은 짧고(최대 600자 × 12개), 답은 최대 약 400토큰이라 한 번에 대략 1원 안팎이에요(모델·요금에 따라 달라요). |
| 지출 상한 | 하루 한도(30번) × 로그인한 사람 수가 최대예요. 불안하면 **예산 알림**(아래 6단계)을 꼭 걸어 두세요. |

## 1. 준비 (한 번만)

```bash
npm install -g firebase-tools
firebase login
```

그리고 Firebase 콘솔 → ⚙️ 프로젝트 설정 → 사용량 및 결제에서 **Blaze로 업그레이드**해요.

## 2. AI 키 넣기 (키는 채팅에 붙여 넣지 마세요)

두 AI 중 쓸 것만 넣어도 돼요(하나만 넣으면 그쪽만 쓰여요). 터미널이 값을 물어보면 그때 붙여 넣어요.

```bash
firebase functions:secrets:set GEMINI_API_KEY   # Google AI Studio(aistudio.google.com)에서 만든 키
firebase functions:secrets:set OPENAI_API_KEY   # platform.openai.com 의 API 키 (ChatGPT 구독과는 별개 결제예요)
```

> ChatGPT 구독(Plus 등)으로는 API를 쓸 수 없어요. API는 platform.openai.com에서 따로 결제해요.

## 3. 배포

저장소 맨 위 폴더에서:

```bash
cd functions && npm install && npm test && cd ..
firebase deploy --only functions,firestore:rules
```

`npm test`(12개)가 모두 통과해야 해요. 배포가 끝나면 함수 주소가 나와요.

## 4. 앱에 주소 적기

`language-teacher/cloud-config.js`의 `tutorUrl`에 주소를 적어요. 예:

```js
tutorUrl: 'https://asia-northeast3-lang-starter.cloudfunctions.net/tutor'
```

(2세대 함수는 배포 로그의 `Function URL (tutor)` 값을 그대로 써도 돼요.) 저장소에 올려 배포하면 놀이 탭에 🤖 AI 튜터가 나타나고,
개인정보 안내(`privacy.html`)에도 AI 튜터 문구가 함께 나타나요.

## 5. 사용 횟수 기록 자동 삭제 (개인정보 안내의 약속)

하루 사용 횟수는 `tutorUsage` 컬렉션에 남고, 개인정보 안내는 "약 2개월 뒤 자동 삭제"라고 약속해요. 아래를 한 번 실행해요.

```bash
gcloud firestore fields ttls update expireAt --collection-group=tutorUsage --enable-ttl --project=lang-starter
```

## 6. 예산 알림 (권장)

구글 클라우드 콘솔 → 결제 → 예산 및 알림 → 월 예산(예: 5,000원)과 50%·100% 알림을 만들어요.
AI 회사 쪽에도 월 지출 한도를 걸어 두세요(Google AI Studio·OpenAI Platform의 Billing/Limits).

## 바꿀 수 있는 값

`functions/.env` 파일의 값을 고치고 다시 배포하면 돼요(비밀이 아니라서 저장소에 올라가 있어요).

| 값 | 기본 | 뜻 |
|---|---|---|
| `TUTOR_DAILY_LIMIT` | `30` | 한 사람이 하루에 쓸 수 있는 횟수(한국 시간 자정에 초기화) |
| `TUTOR_GEMINI_MODEL` | `gemini-2.5-flash` | 쓸 Gemini 모델 이름 |
| `TUTOR_OPENAI_MODEL` | `gpt-4o-mini` | 쓸 ChatGPT 모델 이름 |

모델 이름은 각 회사가 바꾸거나 없앨 수 있어요. 튜터가 "AI가 지금 답하지 못해요"만 계속 말하면 모델 이름이 맞는지 먼저 확인해 보세요.

## 어떻게 지켜지나요

- **키**: 앱·저장소에 없어요. Secret Manager에만 있고 함수만 읽어요.
- **로그인**: 구글 로그인 토큰을 함수가 확인해요. 토큰이 없거나 만료되면 거절해요.
- **하루 한도**: 서버가 세요(앱을 고쳐도 못 피해요). AI가 실패한 호출은 횟수에서 빼 줘요.
- **지시문**: AI에게 주는 규칙은 서버에서만 만들어요. 학습자가 보낸 글은 '연습 문장'으로만 취급해요.
- **글 보관**: 학습자 글과 AI 답은 서버에 저장·기록하지 않아요(오류 로그에도 글은 남기지 않아요).
- **대체**: 고른 AI가 바쁘면(한도·서버 오류) 키가 있는 다른 AI가 대신 답하고 화면에 알려요.

## 시험

```bash
cd functions && npm test          # 서버 규칙·두 AI 호출 모양·대체 동작·CORS 13개 (인터넷·키 필요 없음)
```

앱 화면과 에뮬레이터를 쓰는 시험은 `tools/tests/README.md`를 보세요.
