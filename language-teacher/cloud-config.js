// ☁️ 랭귀지 스타터 클라우드 설정 (Firebase 웹 앱 설정 — 공개돼도 되는 값)
// 비어 있으면(null) 구글 로그인·익명 통계·의견 보내기가 숨겨지고, 앱은 지금처럼 이 기기에만 기록을 저장합니다.
// 설정 방법: 저장소의 docs/cloud-setup.md 참고
// 켤 때는 firebaseConfig 값에 since(켠 날짜, 'YYYY-MM-DD')도 함께 적어 주세요. 개인정보 안내(privacy.html)의
// 적용일과 변경 이력에 이 날짜가 나타납니다. measurementId를 빼면 사용 통계만 꺼지고, 안내에서도 통계 문구가 숨겨져요.
// 예: window.CLOUD_CONFIG = { apiKey: 'AIza…', authDomain: '…', projectId: '…', appId: '…', measurementId: 'G-…', since: '2026-10-01' };
window.CLOUD_CONFIG = {
  apiKey: 'AIzaSyCKtJo056qhBK39A6FT6zX_E_J_-fkobcQ',
  authDomain: 'lang-starter.firebaseapp.com',
  projectId: 'lang-starter',
  storageBucket: 'lang-starter.firebasestorage.app',
  messagingSenderId: '994570010930',
  appId: '1:994570010930:web:8f1fa6324c4cc2fead172b',
  measurementId: 'G-6D5SSPTV6X',
  since: '2026-09-26'   // 구글 로그인·클라우드 저장·사용 통계·의견 보내기를 켠 날
};

// 문의·오류 제보 링크(https만). 넣으면 허브·설정·도움말·개인정보 안내에 한꺼번에 나타나요.
// 비어 있으면 개인정보 안내에는 저장소의 GitHub 이슈 페이지가 문의처로 나타나요.
// 예: window.SITE_CONTACT = { label: '구글 설문지로 문의', url: 'https://forms.gle/…' };  (카카오톡 오픈채팅 주소도 가능)
window.SITE_CONTACT = null;
