import crypto from "crypto";

export const AUTH_COOKIE_NAME = "beomstar_auth";
const AUTH_PAYLOAD = "beomstar-authed";
const SESSION_MAX_AGE_MS = 1000 * 60 * 60 * 24 * 30; // 30일 (로그인 쿠키 Max-Age와 동일)

/**
 * 두 문자열을 타이밍 공격에 안전하게 비교합니다.
 * 길이가 다르면 짧은 쪽을 패딩해서 timingSafeEqual에 넣되,
 * 실제로 길이가 같았을 때만 "같다"고 판단합니다.
 */
export function timingSafeEqualStrings(a, b) {
  const bufA = Buffer.from(String(a ?? ""), "utf8");
  const bufB = Buffer.from(String(b ?? ""), "utf8");

  const maxLength = Math.max(bufA.length, bufB.length, 1);
  const paddedA = Buffer.alloc(maxLength);
  const paddedB = Buffer.alloc(maxLength);
  bufA.copy(paddedA);
  bufB.copy(paddedB);

  const buffersEqual = crypto.timingSafeEqual(paddedA, paddedB);
  return buffersEqual && bufA.length === bufB.length;
}

/**
 * SESSION_SECRET 환경 변수를 반환합니다.
 * 설정되어 있지 않으면 에러를 던져, 빈 문자열이 시크릿으로 쓰여
 * 누구나 계산 가능한 고정 쿠키 값이 되는 것을 막습니다.
 */
function getSessionSecret() {
  const secret = process.env.SESSION_SECRET;
  if (!secret) {
    throw new Error("SESSION_SECRET 환경 변수가 설정되지 않았습니다.");
  }
  return secret;
}

/**
 * APP_PASSWORD 환경 변수를 반환합니다.
 * 설정되어 있지 않으면 null을 반환해, 빈 비밀번호로 로그인이
 * 통과되는 것을 막습니다.
 */
export function getConfiguredPassword() {
  const password = process.env.APP_PASSWORD;
  return password ? password : null;
}

function signExpiry(expiresAtPart) {
  const secret = getSessionSecret();
  return crypto
    .createHmac("sha256", secret)
    .update(`${AUTH_PAYLOAD}.${expiresAtPart}`)
    .digest("hex");
}

/**
 * 로그인 성공 시 쿠키에 저장할 값을 계산합니다.
 * "만료시각.서명" 형태로 구성해, 쿠키 값 자체에 서버가 검증 가능한
 * 만료 시각을 담습니다. 이렇게 하면 쿠키가 유출되더라도(클라이언트가
 * 마음대로 무시할 수 있는 Max-Age와 달리) 서버가 매 요청마다 만료
 * 여부를 재확인하므로, 훔친 쿠키가 영구적인 자격 증명이 되지 않습니다.
 */
export function createAuthCookieValue() {
  const expiresAt = Date.now() + SESSION_MAX_AGE_MS;
  const expiresAtPart = String(expiresAt);
  const signature = signExpiry(expiresAtPart);
  return `${expiresAtPart}.${signature}`;
}

/**
 * 쿠키에 담긴 값이 우리가 서명한 값과 일치하고, 아직 만료되지 않았는지 확인합니다.
 */
export function isAuthCookieValid(cookieValue) {
  if (!cookieValue) return false;

  const separatorIndex = cookieValue.indexOf(".");
  if (separatorIndex === -1) return false;

  const expiresAtPart = cookieValue.slice(0, separatorIndex);
  const signaturePart = cookieValue.slice(separatorIndex + 1);

  const expiresAt = Number(expiresAtPart);
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) return false;

  try {
    const expectedSignature = signExpiry(expiresAtPart);
    return timingSafeEqualStrings(signaturePart, expectedSignature);
  } catch {
    // SESSION_SECRET이 설정되지 않은 등 서버 설정 오류 시에는 안전하게 실패 처리합니다.
    return false;
  }
}
