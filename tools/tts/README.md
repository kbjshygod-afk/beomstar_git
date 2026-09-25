# 음성 클립 미리 녹음하기 (Google Cloud Text-to-Speech)

앱은 지금 외국어 문장을 기기의 음성 합성(`speechSynthesis`)으로 읽어 줘서, 기기마다 목소리 품질이 달라요.
이 도구는 앱이 읽어 주는 **모든 외국어 문장을 한 번만** Google Cloud TTS로 녹음해 MP3로 저장해요.
그러면 어떤 기기에서든 같은 자연스러운 목소리로 들을 수 있어요.

| 파일 | 하는 일 |
|---|---|
| `tools/tts/clips.mjs` | 데이터(`language-teacher/data-*.js`, `stories-*.js`)와 `index.html`의 훈련소 상수를 읽어 **녹음할 문장 목록**을 만들고, 파일 이름(`clipId`)을 정해요 |
| `tools/tts/generate.mjs` | 목록을 Google Cloud TTS로 녹음해 `language-teacher/audio/{언어}/{id}.mp3`와 `index.json`을 만들어요 |
| `docs/voice-setup.md` | Google Cloud 쪽 준비(프로젝트·결제·API 키) — 개발자가 아니어도 따라 할 수 있게 |

외부 패키지는 필요 없어요(node 18 이상).

## 준비

API 키를 환경 변수 `GOOGLE_TTS_API_KEY`로 넣어 주세요. 방법은 [`docs/voice-setup.md`](../../docs/voice-setup.md)에 있어요.

- 키는 화면·로그에 찍지 않고, 요청 헤더(`X-Goog-Api-Key`)로만 보내요(주소에 `?key=`를 붙이지 않아 로그에 남지 않아요).
- 키를 채팅이나 커밋에 붙여 넣지 마세요.

## 순서

```bash
# 0) (선택) 파일 이름 규칙 확인 — node 버전과 브라우저용 코드가 같은 값을 내는지
node tools/tts/clips.mjs --test

# 1) 계산만 해 보기 — 네트워크를 전혀 쓰지 않아요(키 없어도 됨)
node tools/tts/generate.mjs --dry-run

# 2) 목소리 이름 확인 — 언어마다 한 번씩(설정한 후보가 실제로 있는지, 성별이 맞는지)
node tools/tts/generate.mjs --list-voices --lang zh
node tools/tts/generate.mjs --list-voices --lang en,es,ja,fr

# 3) 시험 녹음 — 언어마다 몇 개만 만들어 직접 들어 보기
node tools/tts/generate.mjs --lang zh --limit 5

# 4) 전체 녹음 — 이미 있는 파일은 건너뛰어요(중간에 끊겨도 같은 명령으로 이어 하기)
node tools/tts/generate.mjs
```

끝나면 `language-teacher/audio/`를 커밋하면 돼요.

### 옵션

| 옵션 | 뜻 |
|---|---|
| `--dry-run` | 네트워크 없이 클립 수, 글자 수(과금 기준), UTF-8 바이트, 등급별 예상 요금(월 무료 한도와 비교), 예상 용량만 보여 줘요 |
| `--list-voices` | `GET /v1/voices?languageCode=…`로 쓸 수 있는 목소리와 실제로 고를 목소리를 보여 줘요 |
| `--lang zh` / `--lang zh,ja` | 고른 언어만 |
| `--limit N` | 언어마다 **새로** 만들 클립을 N개까지만(시험용) |
| `--prune` | 지금 목록에 없는 mp3(데이터에서 지워지거나 바뀐 문장)와 남은 `.tmp`를 지워요. `--dry-run`과 함께 쓰면 지울 개수만 보여 줘요 |
| `--redo` | 이미 있는 파일도 다시 녹음해요. 목소리를 바꿨다면 예전 파일을 먼저 지워서 두 목소리가 섞이지 않게 해요 |
| `--concurrency N` | 동시에 보내는 요청 수(기본 4) |
| `--out DIR` | 다른 폴더에 쓰기(시험용) |

- 429(요청 한도)·5xx·연결 끊김은 잠시 기다렸다가 자동으로 다시 시도해요(최대 6번, `Retry-After`를 따름).
- 키 오류(400 API key / 401 / 403)는 곧바로 멈추고 무엇을 확인할지 알려 줘요. 같은 오류가 10번 연달아 나도 멈춰요.
- 끝나면 언어마다 `index.json`을 새로 써요: `{ "v": 1, "voices": { "a": "…", "b": "…" }, "ids": [ … ] }` — `ids`는 **지금 목록에 있고 디스크에도 있는** 클립만, 정렬해서.
- 지난번 `index.json`과 목소리가 다르면(설정을 바꿨거나 후보가 없어져 다른 목소리가 골라졌을 때) 그 언어는 건너뛰어요. 새 목소리로 전부 바꾸려면 `--redo --lang xx`.

## 데이터를 고친 뒤 다시 녹음하기

파일 이름은 **문장 글자 그대로의 해시**라서, 문장이 한 글자만 바뀌어도 새 파일이 필요해요. 이미 있는 건 그대로 두고 새 문장만 녹음하면 돼요.

```bash
node tools/tts/generate.mjs --dry-run            # todo 열에 새로 만들 개수가 나와요
node tools/tts/generate.mjs --prune              # 새 문장만 녹음 + 안 쓰게 된 파일 정리 + index.json 갱신
```

`index.html`의 훈련소 상수(`TONE_BANK`, `VERB_BANK`, `KANA_*`, `FR_*`, `EAR_*`)나 `LANGS`의 `sampleWord`를 바꿨을 때도 똑같이 하면 돼요(`clips.mjs`가 `index.html`을 읽기만 해요).

## 목소리

`generate.mjs` 맨 위 `VOICES`에서 언어마다 고쳐요. 후보를 앞에서부터 확인해서 **실제로 있고 성별이 맞는** 첫 목소리를 써요.
후보가 하나도 없으면 같은 성별에서 가장 좋은 등급(Chirp 3 HD → Neural2 → WaveNet → Standard)을 자동으로 골라요.

| slot | 누구 목소리 | 기본 후보 |
|---|---|---|
| `a` | 단어·문장·예문·동화·훈련소, 대화의 A·C·E·N(해설) — 앱의 기본 목소리 | 여성: `xx-XX-Chirp3-HD-Kore` → `Aoede` → Neural2/WaveNet |
| `b` | 대화의 **B·D** — 앱 `tuneFor()`가 두 번째 목소리를 쓰는 화자 | 남성: `xx-XX-Chirp3-HD-Charon` → `Puck` → Neural2/WaveNet |

- 언어 코드: en `en-US`, zh `cmn-CN`, es `es-ES`, ja `ja-JP`, fr `fr-FR`
- 속도(`speakingRate`): zh 0.9, 나머지 0.95. 목소리가 속도 설정을 거부하면 기본 속도로 녹음하고 알려 줘요(앱에서 재생 속도로 조절).
- 오디오: `MP3`, 24000 Hz(Google MP3는 32 kbps)
- ⚠ **중국어**: Chirp 3 HD가 다음자(多音字, 예: 还·行·得·了·长)를 문맥과 다르게 읽을 수 있어요. 이번 작업 범위 밖이라 그대로 두었어요 — 들어 보고 틀린 문장은 따로 처리해야 해요.

## 예상 규모 (2026-09-25 데이터 기준, `--dry-run` 결과)

| 언어 | a 클립 | b 클립 | 글자 수(과금) | 예상 용량 |
|---|---:|---:|---:|---:|
| en | 2,376 | 444 | 50,619 | 약 18 MB |
| zh | 857 | 107 | 6,554 | 약 7.5 MB |
| es | 1,133 | 113 | 24,337 | 약 8.6 MB |
| ja | 955 | 109 | 10,679 | 약 6.8 MB |
| fr | 1,179 | 124 | 30,975 | 약 10.6 MB |
| **합계** | **6,500** | **897** | **123,164** | **약 50 MB** |

- 용량은 MP3 32 kbps(초당 약 4 KB)에 언어별 말하기 속도와 클립마다 앞뒤 무음 약 0.35초를 더해 **추정**한 값이에요(±30% 정도). 실제 값은 녹음이 끝나면 화면에 나와요.
- 요금: 전부 Chirp 3 HD로 녹음해도 약 12만 자라서 **월 무료 한도(100만 자) 안** → 한 번 전체 녹음은 약 0원이에요.
  (2026-09 기준 가격표: Chirp 3 HD 월 100만 자 무료·이후 100만 자당 $30, Neural2 월 100만 자 무료·$16, WaveNet+Standard 합쳐 월 400만 자 무료·$4.
  같은 달에 다른 곳에서 쓴 양과 합쳐서 세요. 반드시 <https://cloud.google.com/text-to-speech/pricing>에서 다시 확인하세요.)
- 시간: 요청 7,400개 정도라서 동시 4개면 대략 15~40분(요청 한도에 따라 달라요).

## 어떤 문장을 녹음하나요 (`clips.mjs`)

`index.html`의 `speak(` / `speakSeq(` 호출부를 그대로 따라가요. 문자열은 **앱이 넘기는 것과 글자 하나까지 똑같이**(공백·문장부호 포함) 써요.

| 출처 | 앱에서 들리는 곳 |
|---|---|
| `words[]` 원문 + `tts` | 단어 목록 ▶/🐢(`w.tts \|\| 원문`), 복습 카드(▶는 `c.tts \|\| c.native`, 자동 재생·뒤집기는 `c.native`), 짝 맞추기 |
| `keySentences[]` | ▶/🐢, 🎤 따라 말하기 창, 보스 문장, 오늘의 한 문장, 결과 화면, 문장 복습 카드 |
| `dialogue.turns[]` | 말풍선·전체 듣기·파트 듣기·역할극 — speaker B·D는 `b`, 나머지는 `a` |
| `grammar[].examples[]` | ▶/🐢, ✋ 확인 문제 정답 |
| `quiz[]` | 듣기·성조 문제, 배열 문제의 **토큰 하나하나**와 **정답 문장(`tokens.join(joiner)`)**, 선택 문제 정답 보기(한글 없는 것만) |
| `deq.key[]`/`deq.repeat[]` (en) | Daily English Quest 가져오기로 생기는 문장 복습 카드 |
| `stories[].sentences[]` | 동화 문장 탭·전체 듣기(문장 통째로, 쪼개지 않음) |
| `LANGS.sampleWord` | 설정의 속도·목소리 미리 듣기 |
| 훈련소 상수(`index.html`) | 성조(`TONE_BANK`), 동사 비교 듣기(`SOUND_SETS`)와 **"대명사 + 활용형"**(예: `él habla`), 가나 표·게임(히라가나·가타카나)·헷갈리는 글자, 프랑스어 모음 예(쉼표로 나눔)·연음·읽기 게임, 영어 최소대립쌍·연음(`say`와 `en` 둘 다) |

녹음하지 **않는** 것(앱은 파일이 없으면 기기 음성으로 대체해야 해요):
- 🎤 채점 결과의 ✗ 칩(`data-unit`) — 소문자·악센트 제거·축약 풀기 등으로 가공된 조각이라 녹음할 문장이 아니에요.
- 예전 앱/예전 데이터 버전에서 넘어온 복습 카드 문장(지금 데이터와 글자가 다르면).
- 한글이 섞인 문자열 — 선택 문제 보기 `ㅃ`(zh), `ㅅ`(fr). 앱의 `/[가-힣]/` 검사는 완성형만 걸러서 자모 보기는 지금 외국어 목소리로 읽혀요.

## 앱에서 어떻게 쓰이나 (language-teacher/index.html)

1. 언어를 열 때 `audio/{lang}/index.json`을 받아(`loadClips`) `ids`를 `Set`으로 들고 있어요. 파일이 없으면(404) 그 언어는 지금처럼 기기 음성만 써요.
2. `speak(text, rate, speaker)`·`speakSeq()`는 `slot = (speaker === 'B' || speaker === 'D') ? 'b' : 'a'`, `id = clipId(slot, text)`로 찾아요(`clipUrl`). `b`가 없으면 `a`를 써요.
3. 있으면 `fetch`로 받아 한 개의 `<audio>`로 재생(`playClip`), 없거나 못 받거나 재생이 막히면 **같은 문장을 기기 음성(`speechSynthesis`)으로** 읽어요.
4. 속도: `playbackRate = 요청 속도 ÷ index.json의 rate(녹음 속도) × 사용자 속도`, 음높이 유지(`preservesPitch`).
5. 주소는 `audio/{lang}/{id}.mp3?v=…` — `v`는 index.json의 목소리·속도로 정해져서, 목소리를 바꿔 다시 녹음하면 캐시가 저절로 바뀌어요.
6. 서비스 워커: index.json은 네트워크 우선(오프라인이면 저장본), mp3는 한 번 들은 것만 `lt-audio` 캐시에 담겨 오프라인에서도 들려요.
7. 설정 → 🎙️ 자연 음성 스위치로 끌 수 있어요(`settings.voiceMode = 'device'`). 녹음이 있는 언어에서만 보여요.
8. 아이폰·아이패드는 첫 터치 때 같은 `<audio>`를 소리 없이 한 번 재생해 두어(`unlockClip`), 대화 이어 읽기도 막히지 않아요.

대화의 C·E 화자는 기기 음성에서는 음높이로 구분하지만, 녹음은 `a` 목소리 그대로예요.

`clipId`: `slot + '|' + text`의 UTF-8 바이트에 FNV-1a 64비트 → 16자리 16진수(0 채움)의 **앞 12자리**.
브라우저용 코드(BigInt 없이 32비트 두 조각, `clips.mjs`의 `BROWSER_CLIP_ID`와 같음):

```js
// 음성 클립 이름: FNV-1a 64비트(UTF-8) 앞 12자리 — tools/tts/clips.mjs 의 clipId()와 같은 값
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
}
```

테스트 벡터(`node tools/tts/clips.mjs --test`가 node 버전·브라우저 코드 둘 다 확인):

| 입력 | 결과 |
|---|---|
| `fnv1a64("")` / `("a")` / `("foobar")` | `cbf29ce484222325` / `af63dc4c8601ec8c` / `85944171f73967e8` |
| `clipId('a', 'Hello')` | `c390128b4c43` |
| `clipId('b', 'Hello')` | `078dda0e3f4a` |
| `clipId('a', '你好')` | `2c2d098e331a` |
| `clipId('a', 'こんにちは')` | `aecd692d3447` |
| `clipId('a', "C'est un ami ? Oui — très « bien » !")` | `820965b8d4f5` |
| `clipId('b', '¿Cómo estás? 😀')` | `3e3c7b25cdbd` |
| `clipId('a', '')` | `089c4607b545` |

## 문제 해결

| 증상 | 할 일 |
|---|---|
| `GOOGLE_TTS_API_KEY 환경 변수가 없어요` | `docs/voice-setup.md` 6단계 — 키를 넣은 뒤 **새 세션**에서 실행 |
| `HTTP 400: API key not valid` / `403` | 키 값, API 사용 설정, 키 제한(Cloud Text-to-Speech API 포함), 결제 계정 연결을 확인 |
| `목소리를 찾지 못했어요` / 다른 목소리가 골라짐 | `--list-voices --lang xx`로 이름을 보고 `VOICES`를 고치기 |
| `✋ 목소리가 지난번과 달라요` | 예전 목소리 유지: `VOICES` 되돌리기 · 새 목소리로 전부: `--redo --lang xx` |
| `fetch failed`(프록시 뒤에서) | node 22.21+/24+라면 `NODE_USE_ENV_PROXY=1 node tools/tts/generate.mjs …` |
| 일부 실패 | 같은 명령을 다시 실행하면 없는 파일만 이어서 만들어요 |
