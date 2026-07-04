import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import Papa from "papaparse";
import { AUTH_COOKIE_NAME, isAuthCookieValid } from "../../../lib/auth";

export async function GET() {
  const cookieStore = await cookies();
  const authCookie = cookieStore.get(AUTH_COOKIE_NAME)?.value;

  if (!isAuthCookieValid(authCookie)) {
    return NextResponse.json({ ok: false }, { status: 401 });
  }

  const sheetUrl = process.env.SHEET_CSV_URL;
  if (!sheetUrl) {
    return NextResponse.json(
      { ok: false, error: "SHEET_CSV_URL 환경 변수가 설정되지 않았습니다." },
      { status: 500 }
    );
  }

  let csvText;
  try {
    const csvResponse = await fetch(sheetUrl, { cache: "no-store" });
    if (!csvResponse.ok) {
      throw new Error(`시트 응답 오류: ${csvResponse.status}`);
    }
    csvText = await csvResponse.text();
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: "구글 시트를 불러오지 못했습니다." },
      { status: 502 }
    );
  }

  let parsed;
  try {
    parsed = Papa.parse(csvText, {
      header: true,
      skipEmptyLines: true,
    });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: "시트 데이터를 해석하지 못했습니다." },
      { status: 502 }
    );
  }

  const headers = parsed.meta?.fields || [];
  const rows = parsed.data || [];

  return NextResponse.json({
    headers,
    rows,
    fetchedAt: new Date().toISOString(),
  });
}
