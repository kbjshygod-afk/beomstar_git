# 💚 AI 튜터에 ChatGPT 연결하기 (Codex CLI · 내 컴퓨터)

ChatGPT **구독**(API 키 아님)으로 AI 튜터를 쓰는 방법이에요. 내 컴퓨터에서 **다리 프로그램**(`tools/tutor-bridge/bridge.js`)을 켜 두면,
앱이 보낸 글을 컴퓨터의 **Codex CLI**가 ChatGPT에 물어 답을 돌려줘요.

```
휴대폰 앱 ──https──▶ Cloudflare 임시 터널 ──▶ 내 컴퓨터의 다리 프로그램 ──▶ codex exec ──▶ ChatGPT
```

| 알아 둘 것 | 내용 |
|---|---|
| 비용 | 추가 요금 없음. ChatGPT 구독의 Codex 사용 한도에서 차감돼요. |
| 조건 | **컴퓨터와 다리 프로그램이 켜져 있을 때만** 돼요. 끄면 앱에서 "내 컴퓨터에 닿지 않아요"라고 나와요. |
| 속도 | Codex는 코딩용 도구라 Gemini보다 답이 늦어요. |
| 용도 | **혼자 쓰는 용도**예요. 연결 주소(암호 포함)를 남에게 주면 내 구독으로 남이 쓰게 되고, 구독 약관에도 어긋날 수 있어요. |
| 주소 | 임시 터널은 켤 때마다 주소가 바뀌어요. 다시 켜면 앱에 새 줄을 붙여 넣어요. |

## 1. 준비 (한 번만, 컴퓨터에서)

1. [Node.js](https://nodejs.org) 18 이상을 설치해요.
2. Codex CLI를 설치하고 ChatGPT 계정으로 로그인해요.
   ```bash
   npm install -g @openai/codex
   codex login            # 브라우저가 열려요. 안 열리면: codex login --device-auth
   ```
3. cloudflared(무료, 가입 없음)를 설치해요. 휴대폰이 컴퓨터에 닿게 해 주는 터널이에요.
   - 맥: `brew install cloudflared`
   - 윈도우: `winget install --id Cloudflare.cloudflared`
4. 이 저장소를 컴퓨터에 받아요(이미 있으면 `git pull`).

## 2. 켜기 (쓸 때마다)

저장소 폴더에서:

```bash
node tools/tutor-bridge/bridge.js
```

화면에 이런 한 줄이 나와요. **이 줄 전체**를 복사해요(남에게 보여 주지 마세요).

```
https://무작위-이름.trycloudflare.com#긴암호
```

## 3. 앱에 붙여 넣기

앱 → 놀이 탭 → 🤖 AI 튜터 → (Gemini 키가 있으면 **🔑 키**) → **💚 ChatGPT 연결** → 붙여 넣고 **연결**.
Gemini 키도 있으면 대화 화면 위에서 ✨ Gemini / 💚 ChatGPT를 고를 수 있어요.

컴퓨터로 옮기기 번거로우면 그 줄을 나에게 보내는 메모(카카오톡 '나와의 채팅' 등)로 옮겨요.

## 끄기 · 끊기

- 컴퓨터: 다리 프로그램 창에서 `Ctrl+C`.
- 앱: 🔑 키 → 💚 ChatGPT 연결 → **연결 끊기**.
- 암호를 새로 만들려면 홈 폴더의 `.lang-starter-bridge-token` 파일을 지우고 다시 켜요.

## 안전장치

- 다리 프로그램은 **이 컴퓨터 안(127.0.0.1)** 에서만 듣고, 밖에서는 터널로만 들어와요.
- 모든 요청은 **연결 암호**(무작위 43자)가 맞아야 해요. 암호는 홈 폴더에 본인만 읽을 수 있게 저장돼요(저장소 밖).
- 브라우저에서는 이 앱의 사이트(`https://kbjshygod-afk.github.io`)에서 온 요청만 받아요.
- Codex는 **빈 임시 폴더에서 읽기 전용**(`-s read-only`)으로 돌고, "명령·파일·도구를 쓰지 말고 답만 하라"는 지시를 받아요.
  다만 Codex는 원래 컴퓨터를 다루는 도구라, **연결 주소가 새면 남이 내 컴퓨터의 Codex에 글을 보낼 수 있어요.** 주소를 비밀번호처럼 다뤄 주세요.
- 한 번에 하나씩만 답하고, 하루 200번(바꿀 수 있어요)까지예요. 글 내용은 화면·파일에 기록하지 않아요(걸린 시간과 횟수만).

## 설정 (환경 변수, 선택)

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `TUTOR_BRIDGE_PORT` | `8787` | 이 컴퓨터 안에서 쓰는 번호 |
| `TUTOR_BRIDGE_DAILY` | `200` | 하루 횟수 |
| `TUTOR_CODEX_MODEL` | (Codex 기본) | 쓸 모델 이름 |
| `TUTOR_CODEX_EFFORT` | `low` | 생각 깊이(낮을수록 빠름). 빈 값이면 Codex 기본 |
| `CODEX_BIN` | `codex` | Codex CLI 실행 파일 |

`node tools/tutor-bridge/bridge.js --local` 은 터널 없이 켜요(이 컴퓨터의 브라우저에서만 쓸 때).

## 시험

```bash
node --test tools/tutor-bridge/bridge.test.js     # 가짜 Codex로 다리 프로그램만
node tools/tests/lt_tutor.js                        # 앱 ↔ 다리 프로그램(진짜 서버, Codex만 가짜)
```
