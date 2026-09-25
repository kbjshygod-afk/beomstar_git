# ☁️ 구글 로그인·클라우드 저장 켜기 (Firebase 설정 안내)

랭귀지 스타터에 **구글 로그인 + 기록 클라우드 저장 + 익명 사용 통계 + 의견 보내기**가 들어가 있습니다.
Firebase 프로젝트를 만들고 설정값을 `language-teacher/cloud-config.js`에 넣으면 켜집니다.
설정값이 없으면(`null`) 이 기능들은 화면에 나타나지 않고, 앱은 예전처럼 기기에만 저장합니다.

무료 요금제(Spark)로 충분합니다. 카드 등록이 필요 없습니다.
하루 무료 한도는 읽기 5만 번, 쓰기 2만 번입니다. 한 사람이 하루 공부하면 읽기·쓰기가 수십 번 정도라 수백 명까지 넉넉합니다.

---

## 1. 프로젝트 만들기 (3분)
1. https://console.firebase.google.com 에 구글 계정으로 들어갑니다.
2. **프로젝트 만들기** → 이름 `lang-starter`(아무거나 괜찮음)를 입력합니다.
3. **Google 애널리틱스 사용 설정**은 켜 둔 채로 진행합니다(방문자 통계용). 애널리틱스 계정은 "Default Account for Firebase"를 고르면 됩니다.
4. 프로젝트가 만들어지면 **계속**을 누릅니다.

## 2. 웹 앱 등록 → 설정값 복사
1. 프로젝트 개요 화면에서 **</> (웹)** 아이콘을 누릅니다.
2. 앱 닉네임 `랭귀지 스타터`를 입력합니다. "Firebase 호스팅"은 **체크하지 않습니다**.
3. **앱 등록**을 누르면 아래와 같은 `firebaseConfig`가 나옵니다. **이 부분 전체를 복사해서 보내 주세요.**
   ```js
   const firebaseConfig = {
     apiKey: "AIza...",
     authDomain: "lang-starter-xxxx.firebaseapp.com",
     projectId: "lang-starter-xxxx",
     storageBucket: "...",
     messagingSenderId: "...",
     appId: "1:...:web:...",
     measurementId: "G-XXXXXXX"
   };
   ```
   이 값들은 웹페이지에 공개되어도 괜찮은 값입니다. 비밀번호가 아닙니다.
   보안은 5번의 규칙이 지킵니다.

## 3. 구글 로그인 켜기
1. 왼쪽 메뉴 **빌드 → Authentication → 시작하기**를 누릅니다.
2. **로그인 방법** 탭에서 **Google**을 고르고 **사용 설정**을 켭니다. 프로젝트 지원 이메일은 내 이메일을 고릅니다. 그다음 **저장**을 누릅니다.
3. **설정** 탭 → **승인된 도메인** → **도메인 추가**로 `kbjshygod-afk.github.io`를 넣습니다.
4. (권장) ⚙️ **프로젝트 설정 → 일반 → 공개용 이름**을 `랭귀지 스타터`로 바꿉니다. 구글 로그인 창에 이 이름이 보입니다.

## 4. 기록 저장소(Firestore) 만들기
1. 왼쪽 메뉴 **빌드 → Firestore Database → 데이터베이스 만들기**를 누릅니다.
2. 버전(에디션)을 물으면 **Standard**를 고릅니다. 위치는 **asia-northeast3 (서울)**을 고릅니다. 위치는 나중에 바꿀 수 없습니다.
3. **프로덕션 모드에서 시작**을 고르고 만들기를 누릅니다.

## 5. 보안 규칙 붙여넣기 (중요)
1. Firestore Database → **규칙** 탭을 엽니다.
2. 원래 있던 내용을 모두 지웁니다. 그 자리에 저장소의 [`tools/firebase/firestore.rules`](../tools/firebase/firestore.rules) 내용을 그대로 붙여넣고 **게시**를 누릅니다.
   - 학습 기록은 로그인한 본인만 읽고 쓸 수 있습니다.
   - 의견은 누구나 보낼 수만 있고, 읽기는 콘솔에서 주인만 할 수 있습니다.

## 6. 설정값 보내기 → 배포
2번에서 복사한 `firebaseConfig`를 알려 주시면 `language-teacher/cloud-config.js`에 넣어 배포합니다.
직접 하려면 파일 안의 `window.CLOUD_CONFIG = null;`을 아래처럼 바꾸면 됩니다.
```js
window.CLOUD_CONFIG = {
  apiKey: "AIza...", authDomain: "lang-starter-xxxx.firebaseapp.com", projectId: "lang-starter-xxxx",
  storageBucket: "...", messagingSenderId: "...", appId: "1:...:web:...", measurementId: "G-XXXXXXX",
  since: "2026-10-01"   // 켠 날짜 — 개인정보 안내의 적용일·변경 이력에 쓰여요(Firebase에는 보내지 않음)
};
```

---

## 운영하면서 보는 곳
| 보고 싶은 것 | 위치 |
|---|---|
| 사용자 의견 | Firestore Database → 데이터 → `feedback` 컬렉션 (글·만족도·언어·연락처) |
| 방문자·사용 통계 | Firebase 콘솔 → **Analytics 대시보드** 또는 analytics.google.com (하루쯤 지나야 쌓임). 실시간은 "실시간" 보고서 |
| 주요 이벤트 | `select_language` 언어 선택 · `lesson_complete` 레슨 완료 · `boss_clear` · `review_done` · `story_read` · `level_up` · `streak_milestone` · `share`(추천·자랑) · `sign_up`/`login` · `feedback_sent` · `rating` |
| 친구 추천으로 온 사람 | Analytics → 획득 → 트래픽 획득 (소스 `settings`/`brag_*`, 매체 `friend`) |
| 브라우저를 옮겨 온 방문(추천 아님) | 소스 `inapp`·`inapp_copy`·`kakao_inapp`은 카카오톡 같은 앱 안 브라우저에서 본인이 **기본 브라우저로 옮겨 연 것**이에요(‘기본 브라우저로 열기’·‘주소 복사’·로그인 도움 창). 매체는 `browser_switch`로 따로 잡히니 추천 수에서 빼고 보세요 |
| 로그인한 사용자 수 | Authentication → 사용자 |
| 한 사람의 기록 | Firestore → `users/{uid}` (앱이 쓰는 형식 그대로라 직접 고치지 마세요) |
| 삭제 요청 처리 | 사용자가 앱에서 못 지울 때: Firestore → `users/{uid}` 문서 삭제 **+** Authentication → 사용자 → 그 계정 ⋮ → **계정 삭제**(이름·이메일까지 지워짐). `uid`는 Authentication 사용자 목록에서 이메일로 찾아요. 의견 삭제 요청은 `feedback`에서 글·보낸 날(`at`)·`uid`로 찾아 문서를 지워요 |
| 의견 1년 보관 지키기 | 분기마다 한 번 Firestore → `feedback`에서 `at`이 1년 넘은 문서를 지워요(`at` 기준으로 필터·정렬 → 문서 ⋮ → 문서 삭제). ⚠️ Firestore TTL 정책은 칸의 시각이 **지나면** 지우는 방식이라 `at`(보낸 시각)에 걸면 곧바로 지워져요. TTL로 자동화하려면 앱이 `expireAt`(보낸 시각 + 1년)을 함께 저장하도록 바꾸고 `firestore.rules`의 `feedback` 허용 칸에도 더한 뒤, 그 칸에 TTL을 거세요 |

## 자주 묻는 것
- **카카오톡에서 연 링크로는 로그인이 안 돼요.** 구글이 앱 안 브라우저(카톡·인스타 등)에서 로그인을 막아 두었습니다. 앱이 "기본 브라우저로 열기" 안내를 띄웁니다.
- **로그인 창이 안 떠요.** 브라우저가 팝업을 막았을 수 있습니다. 한 번 더 누르거나 팝업을 허용해 주세요.
- **`unauthorized-domain` 오류**가 나면 3-3의 승인된 도메인을 확인하세요.
- **`operation-not-allowed` 오류**가 나면 3-2의 Google 사용 설정을 확인하세요.
- **요금이 나올까 걱정돼요.** Spark(무료) 요금제는 한도를 넘으면 그날만 멈추고 요금이 청구되지 않습니다.
- **Firebase SDK 버전 올리기**: `tools/firebase/package.json`은 `firebase` 버전을 정확히 고정해 두었어요(예: `12.19.0`). 그래서 `npm install`만으로는 버전이 오르지 않아요. `tools/firebase`에서 `npm install firebase@<새 버전> -D -E`(또는 package.json의 숫자를 바꾼 뒤 `npm install`) → `npm run build`를 실행하세요. 묶음이 `language-teacher/vendor/firebase/`에 다시 만들어지고, `language-teacher/index.html`의 `FB_VER`(묶음 내용 해시)도 자동으로 바뀝니다. 버전이 같아도 `fb-core.js`·`fb-sync.js`의 내보내기를 바꿔 다시 묶으면 `FB_VER`가 바뀌어, 옛 묶음과 새 묶음이 섞이지 않아요. 확인만 하려면 `node tools/firebase/build.mjs --check`.

## 켜기 전 문구 확인 (체크리스트)
- [ ] `language-teacher/cloud-config.js`의 `SITE_CONTACT`에 문의 링크(구글 설문지나 오픈채팅, https)를 넣었나요? 허브·설정·도움말·개인정보 안내에 함께 나타나요. 넣지 않으면 개인정보 안내에는 저장소의 GitHub 이슈 페이지가 문의처로 나와요(공개 게시판이라 삭제 요청 같은 개인정보 문의에는 설문지·오픈채팅이 더 알맞아요).
- [ ] `privacy.html` 6절 운영자 이름(닉네임 가능)을 확인했나요?
- [ ] 통계를 켜 둘지(기본 켜짐, 사용자가 설정에서 끔) 정했나요? `measurementId`를 빼면 통계만 꺼져요.
- [ ] `CLOUD_CONFIG`에 `since: 'YYYY-MM-DD'`(켠 날짜)를 적었나요? 개인정보 안내의 적용일과 변경 이력(‘… 구글 로그인·클라우드 저장·의견 보내기·사용 통계 도입’)이 이 날짜로 나와요. 적지 않으면 처음 만든 날(2026-09-25)로 보여요.
- [ ] 허브(index.html)와 개인정보 안내는 `CLOUD_CONFIG`가 있으면 '구글 로그인'·의견 보내기 문구가 저절로 나타나고, `measurementId`가 있을 때만 사용 통계·쿠키 문구가 나타나요. 문구를 따로 고칠 필요는 없어요.
