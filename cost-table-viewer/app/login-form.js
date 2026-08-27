"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginForm() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setLoading(true);

    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });

      if (response.ok) {
        router.refresh();
        // 서버 컴포넌트 갱신이 안 되는 경우를 대비한 안전장치
        window.location.reload();
      } else {
        setError("비밀번호가 올바르지 않습니다.");
      }
    } catch {
      setError("로그인 중 오류가 발생했습니다. 다시 시도해 주세요.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1 className="login-title">원가표 뷰어</h1>
        <p className="login-desc">비밀번호를 입력해 주세요.</p>

        <label className="login-label" htmlFor="password">
          비밀번호
        </label>
        <input
          id="password"
          type="password"
          className="login-input"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="비밀번호 입력"
          autoFocus
          autoComplete="current-password"
        />

        {error && <p className="login-error">{error}</p>}

        <button type="submit" className="login-button" disabled={loading}>
          {loading ? "확인 중..." : "입장하기"}
        </button>
      </form>
    </div>
  );
}
