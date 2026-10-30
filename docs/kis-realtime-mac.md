# 한국투자증권 실시간 체결가 — 맥 상시 실행 안내 (체크리스트 2.5 → 2.6)

**목적:** GitHub Actions는 장시간 소켓에 맞지 않아, 실시간 체결가 수신은 대표님 맥에서 돌린다. 먼저 **장중 1시간 수신 테스트**(2.5)로 연결·메시지 형식·끊김을 확인하고, 통과하면 상시 실행과 손절 근접 알림(2.6)으로 넘어간다. 주문은 어디에도 없다(듣기만 한다).

## 1. 준비 (한 번만, 10분)

```bash
# 1) 저장소 (이미 있으면 cd만)
git clone https://github.com/kbjshygod-afk/beomstar_git.git ~/beomstar_git
cd ~/beomstar_git

# 2) 파이썬 가상환경 + 의존성 (python3 3.11 이상)
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

## 3. 상시 실행 (2.6에서 사용, 지금은 참고)

테스트가 통과하면 launchd로 평일 08:50 KST 시작·15:40 종료를 등록한다. 아래는 초안이며 2.6 PR에서 손절 근접 알림과 함께 확정한다.

```xml
<!-- ~/Library/LaunchAgents/com.beomstar.kis-ws.plist (초안) -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.beomstar.kis-ws</string>
  <key>ProgramArguments</key><array>
    <string>/bin/zsh</string><string>-lc</string>
    <string>cd ~/beomstar_git && source ~/.venvs/beomstar/bin/activate && python trading/tools/kis_ws_probe.py --minutes 400</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>50</integer><key>Weekday</key><integer>1</integer></dict>
  <key>StandardOutPath</key><string>/tmp/beomstar-kis-ws.log</string>
  <key>StandardErrorPath</key><string>/tmp/beomstar-kis-ws.err</string>
</dict></plist>
```

(평일 다섯 요일은 `StartCalendarInterval`을 배열로 5개 넣는다. 맥이 잠들면 실행되지 않으므로 전원 설정에서 잠자기 방지 또는 `caffeinate` 사용.)

## 4. 알려진 한계
- 모의투자 서버(vps)의 실시간은 정규장(KRX) 체결 기준으로 알려져 있고 NXT 포함 여부는 확인 대상이다(체크리스트 2.2). `--venue NX`/`UN`으로 비교해 본다.
- 실시간 체결가는 **알림용**이다. 룰(손절 −7/−10%, 다음 시가 체결)은 그대로이고, 장중 가격으로 체결하지 않는다.
