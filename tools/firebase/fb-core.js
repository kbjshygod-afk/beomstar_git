// 앱 + 사용 통계(Analytics). 설정에 measurementId가 있고 통계를 끄지 않았을 때 불러온다.
export { initializeApp, getApps, getApp } from 'firebase/app';
export { initializeAnalytics, logEvent, setAnalyticsCollectionEnabled, isSupported as analyticsSupported } from 'firebase/analytics';
