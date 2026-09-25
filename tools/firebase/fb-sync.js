// 구글 로그인(Auth) + 기록 저장·의견(Firestore lite). 로그인했던 기기이거나 로그인·의견 보내기를 누를 때만 불러온다.
export { initializeAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged, connectAuthEmulator, indexedDBLocalPersistence, browserLocalPersistence, browserPopupRedirectResolver, deleteUser, signInWithCredential } from 'firebase/auth';
export { getFirestore, doc, getDoc, deleteDoc, addDoc, collection, runTransaction, connectFirestoreEmulator, serverTimestamp } from 'firebase/firestore/lite';
