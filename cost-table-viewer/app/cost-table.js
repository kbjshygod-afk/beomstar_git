"use client";

import { useEffect, useMemo, useState } from "react";
import LoginForm from "./login-form";

export default function CostTable() {
  const [headers, setHeaders] = useState([]);
  const [rows, setRows] = useState([]);
  const [fetchedAt, setFetchedAt] = useState(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [needsLogin, setNeedsLogin] = useState(false);

  async function loadData() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/sheet-data", { cache: "no-store" });

      if (response.status === 401) {
        setNeedsLogin(true);
        return;
      }

      if (!response.ok) {
        setError("데이터를 불러오는 중 문제가 발생했습니다.");
        return;
      }

      const data = await response.json();
      setHeaders(data.headers || []);
      setRows(data.rows || []);
      setFetchedAt(data.fetchedAt || null);
    } catch {
      setError("네트워크 오류로 데이터를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filteredRows = useMemo(() => {
    if (!search.trim()) return rows;
    const keyword = search.trim().toLowerCase();
    return rows.filter((row) =>
      Object.values(row).some((value) =>
        String(value ?? "").toLowerCase().includes(keyword)
      )
    );
  }, [rows, search]);

  if (needsLogin) {
    return <LoginForm />;
  }

  const lastUpdatedText = fetchedAt
    ? new Date(fetchedAt).toLocaleString("ko-KR")
    : "-";

  return (
    <div className="table-page">
      <header className="table-header">
        <h1 className="table-title">원가표 뷰어</h1>
        <div className="table-toolbar">
          <input
            type="text"
            className="search-input"
            placeholder="검색어 입력 (품목명, 규격 등)"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <button
            type="button"
            className="refresh-button"
            onClick={loadData}
            disabled={loading}
          >
            {loading ? "불러오는 중..." : "새로고침"}
          </button>
        </div>
        <p className="last-updated">마지막 업데이트: {lastUpdatedText}</p>
      </header>

      {error && <p className="table-error">{error}</p>}

      <div className="table-scroll">
        <table className="cost-table">
          <thead>
            <tr>
              {headers.map((header) => (
                <th key={header}>{header}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredRows.length === 0 && !loading ? (
              <tr>
                <td className="empty-cell" colSpan={Math.max(headers.length, 1)}>
                  표시할 데이터가 없습니다.
                </td>
              </tr>
            ) : (
              filteredRows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {headers.map((header) => (
                    <td key={header}>{row[header]}</td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
