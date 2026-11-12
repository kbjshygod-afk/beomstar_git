# 시험 (저장소 안에 보관)

예전 시험 묶음은 저장소 밖 임시 폴더에만 있어서 사라졌어요. 새로 만드는 시험은 모두 여기에 둬요.
브라우저 시험은 Playwright가 필요해요(`NODE_PATH=/opt/node-tools/node_modules` 또는 직접 설치).

| 파일 | 무엇을 | 어떻게 돌리나 |
|---|---|---|
| `lt_smoke.js` | 5개 언어에서 모든 탭·놀이 타일을 열어 오류·가로 넘침·빈 화면이 없는지 | 저장소 맨 위에서 `python3 -m http.server 8765 --bind 127.0.0.1` 을 켜 두고 `node tools/tests/lt_smoke.js` |
| `lt_tutor.js` | 🤖 AI 튜터 화면 — 내 키 방식(키 넣기·확인·지우기, 구글로 바로 보내기, 모델·설정 대체, 오류·한도)과 중계 방식(로그인 전·후, 두 AI 고르기), HTML 주입 방어, 개인정보 문구. 구글·서버 응답은 가짜 | 위 서버를 켜 두고 `node tools/tests/lt_tutor.js` |
| `lt_tutor_fn.js` | 🤖 중계 함수 본체를 Firebase 에뮬레이터에서 실제로(로그인 토큰·하루 한도·실패 시 횟수 되돌리기·대체 AI) | 아래 참고 |
| `ai-stub.js` | 위 시험에서 Gemini·OpenAI 호출만 가짜로 바꾸는 파일 | — |
| `../tutor-bridge/bridge.test.js` | 💚 ChatGPT 다리 프로그램(암호·CORS·한도·Codex 실행 인자·오류 분류) — Codex는 가짜 | `node --test tools/tutor-bridge/bridge.test.js` |
| `../../functions/test/` | 서버 규칙 단위 시험(검증·지시문·두 AI 호출 모양·대체·CORS) | `cd functions && npm test` |

## 에뮬레이터 시험(`lt_tutor_fn.js`) 켜는 법

```bash
cd functions && npm install && cd ..
printf 'GEMINI_API_KEY=x\nOPENAI_API_KEY=y\n' > functions/.secret.local   # 가짜 값(저장소에 올라가지 않음)
printf 'TUTOR_DAILY_LIMIT=3\n' > functions/.env.local                      # 시험용 한도 3번
NODE_OPTIONS="--require $PWD/tools/tests/ai-stub.js" firebase emulators:start --only functions,auth,firestore --project demo-langstarter
# 다른 터미널에서
node tools/tests/lt_tutor_fn.js
```

⚠ Firebase 에뮬레이터는 모든 사이트의 요청을 허용하도록 만들어져 있어서, "남의 사이트 거절"은 에뮬레이터가 아니라 단위 시험(`functions/test`)에서 확인해요.
