// 구글 로그인(Auth) + 기록 저장·의견(Firestore lite). 로그인했던 기기이거나 로그인·의견 보내기를 누를 때만 불러온다.
// reauthenticateWith*: 클라우드 기록 지우기 때 계정까지 지우려면 최근 로그인 확인이 필요하다(오래된 로그인은 deleteUser가 거절됨)
export { initializeAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged, connectAuthEmulator, indexedDBLocalPersistence, browserLocalPersistence, browserPopupRedirectResolver, deleteUser, signInWithCredential, reauthenticateWithPopup, reauthenticateWithCredential } from 'firebase/auth';
export { getFirestore, doc, getDoc, deleteDoc, addDoc, collection, runTransaction, connectFirestoreEmulator, serverTimestamp } from 'firebase/firestore/lite';
