# 팀이 쓰는 시트·웹앱을 고칠 때의 안전 규칙

여러 사람이 동시에 쓰는 구글 시트나 Apps Script 웹앱(`doGet`/`doPost`/`google.script.run`)을 만들거나 고칠 때 따른다.
아이디어 출처: [kpcrmv4/gas-best-practices](https://github.com/kpcrmv4/gas-best-practices) (MIT). 한국어로 요약하고 코드를 새로 작성했다.

## 1. 변경 전 승인

- 시트 구조(열 추가·삭제, 시트 이름, 다른 시트가 참조하는 수식), 데이터 덮어쓰기, 행 삭제, 배포된 웹앱 변경은 **실행 전에 무엇이 깨질 수 있는지 설명하고 승인을 받는다.**
- 작업 전에 파일 → 버전 기록 → **현재 버전 이름 지정**으로 되돌릴 지점을 만든다.
- 처음 실행은 **사본**에서 한다.

## 2. 동시 저장은 잠금(LockService)으로 감싼다

두 사람이 같은 순간에 저장하면 같은 행을 덮어쓰거나 중복 행이 생긴다.

```javascript
function saveRecord(record) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) {            // 10초 대기. 0초나 5분 이상은 쓰지 않는다
    return { ok: false, error: '다른 저장이 진행 중입니다. 잠시 후 다시 시도해 주세요.' };
  }
  try {
    // 읽기 → 검증 → 쓰기를 이 안에서 한 번에 처리
    SpreadsheetApp.flush();
    return { ok: true };
  } finally {
    lock.releaseLock();                  // 오류가 나도 반드시 해제
  }
}
```

- 외부 호출(`UrlFetchApp`)이나 오래 걸리는 작업은 잠금 **밖**에서 한다. 잠금 안에서는 시트 읽기·쓰기만 한다.
- 범위: 여러 사람 사이의 충돌은 `getScriptLock()`, 한 사람의 연타 방지는 `getUserLock()`을 쓴다.

## 3. 서버 함수는 결과 봉투를 돌려준다

클라이언트가 부르는 함수는 예외를 그대로 던지지 않고 `{ ok, data, error }`를 돌려준다. 화면에는 한국어 메시지를 보여 주고, 개발용 로그는 `console.log`로 남긴다.

```javascript
const SHEET_ITEMS = 'Items';

function getItems() {
  try {
    const rows = SpreadsheetApp.getActive().getSheetByName(SHEET_ITEMS)
      .getDataRange().getValues();
    return { ok: true, data: rows };
  } catch (e) {
    console.error('getItems failed', e);
    return { ok: false, error: '목록을 불러오지 못했습니다. 담당자에게 알려 주세요.' };
  }
}
```

## 4. 덮어쓰기·대량 삭제 차단

- **버전 확인:** 화면이 전체 데이터를 다시 저장하는 구조라면 읽을 때 받은 버전 번호(`rev`)를 저장 때 함께 보내게 한다. 서버의 현재 번호와 다르면 저장을 거부한다. 다른 사람이 먼저 고친 내용을 옛 화면이 덮어쓰는 것을 막는다.
- **대량 삭제 차단:** 한 번 저장에서 평소보다 많은 행(예: 5행 초과)이 삭제되면 저장을 멈추고 이유를 돌려준다. 정말 지워야 하면 웹 화면 버튼이 아니라 시트의 사용자 메뉴에서 따로 실행한다.
- **서버 소유 값 보호:** 생성일, 작성자, 자동 판정 결과처럼 서버가 계산하는 칸은 클라이언트가 보낸 값으로 덮어쓰지 않는다.
- **저장 후 작업 분리:** 저장이 끝난 뒤의 메일 발송·로그 기록은 따로 `try/catch`로 감싸, 부수 작업이 실패해도 저장 성공이 오류로 바뀌지 않게 한다.

## 5. 배포: 팀이 쓰는 주소를 바꾸지 않는다

| 주소 | 실행되는 코드 | 누가 쓰나 |
|---|---|---|
| `.../dev` | 마지막으로 저장한 코드 | 편집 권한이 있는 사람만 (테스트용) |
| `.../exec` | 배포된 **버전** | 팀 전체 |

- 코드를 저장해도 `/exec`는 바뀌지 않는다. `/dev`에서 테스트한 뒤 배포한다.
- 배포는 **배포 → 배포 관리 → 기존 배포 ✏️ 편집 → 버전: 새 버전 → 배포**로 한다. **새 배포**를 만들면 URL이 바뀌어 팀이 가진 링크가 옛 코드를 계속 실행한다.
- clasp를 쓰면 `clasp deploy -i <기존 배포 ID> -d "v13 변경 요약"`처럼 항상 기존 ID를 지정한다.
- 배포 설명에 버전·날짜·변경 요약을 적고, 코드 안에도 `const APP_VERSION = 'v13';`을 둬서 화면에 표시한다. 문제가 생기면 이전 버전으로 되돌릴 수 있다.
- 가능하면 테스트용 배포와 운영용 배포를 따로 둔다.

## 6. 6분 제한

한 번 실행은 6분까지다. 큰 작업은 나눠서 처리하고, 진행 위치를 `PropertiesService`에 저장한 뒤 시간 트리거로 이어서 실행한다. 끝나면 그 트리거를 지운다.
