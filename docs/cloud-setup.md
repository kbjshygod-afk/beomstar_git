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
  storageBucket: "...", messagingSenderId: "...", appId: "1:...:web:...", measurementId: "G-XXXXXXX"
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
| 로그인한 사용자 수 | Authentication → 사용자 |
| 한 사람의 기록 | Firestore → `users/{uid}` (앱이 쓰는 형식 그대로라 직접 고치지 마세요) |

## 자주 묻는 것
- **카카오톡에서 연 링크로는 로그인이 안 돼요.** 구글이 앱 안 브라우저(카톡·인스타 등)에서 로그인을 막아 두었습니다. 앱이 "기본 브라우저로 열기" 안내를 띄웁니다.
- **로그인 창이 안 떠요.** 브라우저가 팝업을 막았을 수 있습니다. 한 번 더 누르거나 팝업을 허용해 주세요.
- **`unauthorized-domain` 오류**가 나면 3-3의 승인된 도메인을 확인하세요.
- **`operation-not-allowed` 오류**가 나면 3-2의 Google 사용 설정을 확인하세요.
- **요금이 나올까 걱정돼요.** Spark(무료) 요금제는 한도를 넘으면 그날만 멈추고 요금이 청구되지 않습니다.
- **Firebase SDK 버전 올리기**: `tools/firebase`에서 `npm install && npm run build`를 실행하고, `language-teacher/index.html`의 `FB_VER`를 맞춥니다.
