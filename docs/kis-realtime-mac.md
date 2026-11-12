# 한국투자증권 실시간 체결가 — 실행 안내 (체크리스트 2.5 · 2.6)

> **2026-11-06 변경: 기본 실행 장소는 GitHub Actions 워크플로 `kis-ws`다.** 대표님 맥에서 명령을 칠 필요가 없다. 키는 저장소 Secret(`KIS_APP_KEY`·`KIS_APP_SECRET`)을 쓰고, 결과(체결 기록·요약)는 실행 아티팩트, 손절 근접 알림은 이슈 "한국장 손절 근접 알림" 댓글로 남는다. 작업 하나가 최대 6시간이라 장 전체(6시간 30분)는 두 번에 나눠 돈다. 아래 맥 안내는 Actions가 막힐 때의 예비 경로로 둔다.

**목적:** GitHub Actions는 장시간 소켓에 맞지 않아, 실시간 체결가 수신은 대표님 맥에서 돌린다. 먼저 **장중 1시간 수신 테스트**(2.5)로 연결·메시지 형식·끊김을 확인하고, 통과하면 상시 실행과 손절 근접 알림(2.6)으로 넘어간다. 주문은 어디에도 없다(듣기만 한다).

## 1. 준비 (한 번만, 10분)

```bash
# 1) 저장소 (이미 있으면 cd만)
git clone https://github.com/kbjshygod-afk/beomstar_git.git ~/beomstar_git
cd ~/beomstar_git

# 2) 파이썬 가상환경 + 의존성 (python3 3.11 이상)
#    맥 기본 python3가 3.9면(pandas==3.0.6 "No matching distribution" 오류) 먼저:
#    brew install python@3.12 && $(brew --prefix)/bin/python3.12 -m venv ~/.venvs/beomstar
python3 -m venv ~/.venvs/beomstar
source ~/.venvs/beomstar/bin/activate
pip install -r trading/requirements.txt websocket-client

# 3) 키 파일 (GitHub Secrets에 넣은 것과 같은 모의투자 앱키·시크릿). 채팅·저장소에 붙이지 않는다.
mkdir -p ~/.config/beomstar
cat > ~/.config/beomstar/kis.env <<'KEYS'
KIS_APP_KEY=여기에_앱키
KIS_APP_SECRET=여기에_시크릿
KIS_ENV=vps
KEYS
chmod 600 ~/.config/beomstar/kis.env
```

## 2. 1시간 수신 테스트 (2.5) — 장중에 실행

KRX 정규장 09:00~15:30 KST에 실행한다(NXT까지 보려면 `--venue UN`, 08:00~20:00).

```bash
cd ~/beomstar_git && source ~/.venvs/beomstar/bin/activate
python trading/tools/kis_ws_probe.py --minutes 60
```

- 종목을 주지 않으면 장부(`origin/paper-trading`)의 **한국장 보유 종목**과 손절가를 읽어 구독한다. 보유가 없으면 `--symbols 096530,425420`처럼 직접 준다.
- 5분마다 중간 요약, 끝나면 `RESULT:` 요약과 파일 두 개(`~/beomstar/kis_ws/ticks_<날짜>.jsonl`, `summary_<날짜>.json`)를 남긴다.
- **보내 줄 것:** `summary_<날짜>.json` 내용(또는 RESULT 줄). 키 파일은 절대 보내지 않는다.

**통과 기준:** approval key 발급 성공, 구독 ack `SUBSCRIBE SUCCESS`, 1시간 동안 재연결 2회 이하, 구독한 모든 종목에서 체결 수신(거래가 거의 없는 종목은 예외), PINGPONG 응답으로 끊김 없음.

**자주 막히는 것**
| 증상 | 원인·조치 |
|---|---|
| `APPROVAL FAILED: HTTP 403` | 앱키·시크릿 오타, 또는 모의투자(vps) 키인데 `KIS_ENV=prod` |
| ack `rt_cd 1 ... 등록 한도` | 종목 41개 초과. 보유 종목만 구독하므로 평소엔 해당 없음 |
| 체결이 전혀 안 옴 | 장 시간 밖이거나 휴장일. 모의투자 서버는 실시간 체결을 정규장만 전달 |
| `pip install websocket-client` 메시지 | 가상환경 활성화 뒤 다시 설치 |

## 3. 손절 근접 알림 + 상시 실행 (2.6)

> **2026-11-12 운영 시작 (Actions, 대표님 할 일 없음):** `kis-ws` 워크플로가 평일 두 번 자동으로 돈다. 08:50 KST(205분)와 12:05 KST(210분)이고, 두 번째는 첫 번째가 끝난 뒤 이어서 돈다.
> - **대상:** 장부의 한국 보유 종목과 그 손절가. 보유 종목이 없는 날은 바로 정상 종료한다.
> - **알림:** 근접(손절가 위 2% 안)과 도달(손절가 이하)을 이슈 "한국장 손절 근접 알림" 댓글로 보낸다. 오전과 오후 실행이 그날 보낸 알림을 공유해서 종목·단계마다 하루 한 번만 보낸다.
> - **휴장일:** 구독만 확인되면 정상으로 처리한다.
> - **알림을 받으려면:** 그 이슈를 GitHub에서 구독(Subscribe)하시면 휴대폰 GitHub 앱이나 메일로 받습니다.
> - 아래 맥 등록 절차는 Actions가 막힐 때 쓰는 예비 경로다.

1시간 테스트가 통과하면 같은 도구를 평일마다 자동으로 돌린다. 도구는 장부의 **보유 종목 손절가**를 알고 있어서, 장중 현재가가 손절가 위 2% 안으로 들어오면(근접) 또는 손절가 이하가 되면(도달) 종목·단계마다 하루 한 번 알린다.

- **알림 경로:** 맥 알림센터(항상) + GitHub 이슈 "한국장 손절 근접 알림" 댓글(`gh auth login`이 되어 있을 때; 없으면 건너뛰고 로그만 남김). 모든 알림은 `~/beomstar/kis_ws/alerts_<날짜>.jsonl`에 기록.
- **룰은 그대로:** 알림은 정보다. 청산은 여전히 "종가가 손절가 아래 → 다음 시가"이고 장중 가격으로 체결하지 않는다. 도구에 주문 코드는 없다.
- 근접 폭은 `--near-pct`(기본 2), 알림을 끄려면 `--no-alert`.

**등록 (한 번):**
```bash
cd ~/beomstar_git && git pull --ff-only origin claude/dazzling-ride-a0nb4k
brew install gh && gh auth login        # 이슈 댓글 알림을 원할 때만
zsh trading/tools/mac/install_launchd.sh
```
평일 08:55 KST에 시작해 15:35까지 듣고 끝난다(`--minutes 400`). 시작 전에 저장소를 최신으로 당기고, `caffeinate`로 실행 중 잠들지 않게 한다. 맥이 꺼져 있거나 덮개가 닫혀 잠든 상태면 그날은 돌지 않는다(전원 설정에서 "디스플레이가 꺼져 있을 때 자동으로 잠자기 방지" 권장).

- 바로 시험: `launchctl kickstart gui/$(id -u)/com.beomstar.kis-ws`
- 로그: `~/beomstar/kis_ws/launchd.log`, 요약: `summary_<날짜>.json`
- 해제: `launchctl bootout gui/$(id -u)/com.beomstar.kis-ws`

## 4. 알려진 한계
- 모의투자 서버(vps)의 실시간은 정규장(KRX) 체결 기준으로 알려져 있고 NXT 포함 여부는 확인 대상이다(체크리스트 2.2). `--venue NX`/`UN`으로 비교해 본다.
- 실시간 체결가는 **알림용**이다. 룰(손절 −7/−10%, 다음 시가 체결)은 그대로이고, 장중 가격으로 체결하지 않는다.
