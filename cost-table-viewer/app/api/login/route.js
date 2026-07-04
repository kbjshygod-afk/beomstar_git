import { NextResponse } from "next/server";
import {
  AUTH_COOKIE_NAME,
  createAuthCookieValue,
  getConfiguredPassword,
  timingSafeEqualStrings,
} from "../../../lib/auth";

// 아주 단순한 IP별 고정 윈도우 레이트 리밋입니다.
// (동일 서버 프로세스 내에서만 유효하지만, 무제한 자동화된 비밀번호
// 대입 시도를 막는 최소한의 안전장치로 충분합니다.)
const RATE_LIMIT_WINDOW_MS = 15 * 60 * 1000; // 15분
const RATE_LIMIT_MAX_ATTEMPTS = 10;
const attemptsByIp = new Map();

function isRateLimited(ip) {
  const now = Date.now();
  const entry = attemptsByIp.get(ip);

  if (!entry || now - entry.windowStart > RATE_LIMIT_WINDOW_MS) {
    attemptsByIp.set(ip, { windowStart: now, count: 1 });
    return false;
  }

  entry.count += 1;
  return entry.count > RATE_LIMIT_MAX_ATTEMPTS;
}

function getClientIp(request) {
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) {
    return forwardedFor.split(",")[0].trim();
  }
  return request.headers.get("x-real-ip") || "unknown";
}

export async function POST(request) {
  const ip = getClientIp(request);
  if (isRateLimited(ip)) {
    return NextResponse.json(
      { ok: false, error: "로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요." },
      { status: 429 }
    );
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false }, { status: 400 });
  }

  const password = typeof body?.password === "string" ? body.password : "";
  const correctPassword = getConfiguredPassword();

  if (correctPassword === null) {
    return NextResponse.json(
      { ok: false, error: "서버에 APP_PASSWORD가 설정되지 않았습니다." },
      { status: 500 }
    );
  }

  const passwordMatches = timingSafeEqualStrings(password, correctPassword);

  if (!passwordMatches) {
    return NextResponse.json({ ok: false }, { status: 401 });
  }

  let cookieValue;
  try {
    cookieValue = createAuthCookieValue();
  } catch {
    return NextResponse.json(
      { ok: false, error: "서버에 SESSION_SECRET이 설정되지 않았습니다." },
      { status: 500 }
    );
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set(AUTH_COOKIE_NAME, cookieValue, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30, // 30일
  });

  return response;
}
