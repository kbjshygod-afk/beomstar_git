import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import krx_probe as K  # noqa: E402


def test_number_and_code_parsing():
    assert K.num("1,234.5") == 1234.5 and K.num("-") is None and K.num("") is None and K.num("x") is None
    assert K.short_code("KR7005930003") == "005930"
    assert K.short_code("096530") == "096530"


def test_fetch_sends_key_in_header_only(monkeypatch):
    seen = {}

    class R(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        seen["auth"] = req.get_header("Auth_key")
        return R(json.dumps({"OutBlock_1": [{"BAS_DD": "20261029", "ISU_CD": "096530", "TDD_CLSPRC": "36,250"}]}).encode())

    monkeypatch.setattr(K.urllib.request, "urlopen", fake_urlopen)
    rows, note = K.fetch("KOSDAQ_STOCKS", "20261029", "SECRET ")
    assert rows and rows[0]["ISU_CD"] == "096530" and note == "HTTP 200"
    assert seen["url"] == "https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd?basDd=20261029"
    assert seen["auth"] == "SECRET" and "SECRET" not in seen["url"]


def test_fetch_query_form_puts_key_in_url_and_not_in_header(monkeypatch):
    seen = {}

    class R(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        seen["url"], seen["auth"] = req.full_url, req.get_header("Auth_key")
        return R(b'{"OutBlock_1": []}')

    monkeypatch.setattr(K.urllib.request, "urlopen", fake_urlopen)
    rows, note = K.fetch("KOSPI_INDEX", "20261029", "a b", auth="query")
    assert rows == [] and "via query" not in note
    assert seen["url"].endswith("?basDd=20261029&AUTH_KEY=a%20b") and seen["auth"] is None


def test_fetch_reports_non_json_as_unapproved(monkeypatch):
    class R(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(K.urllib.request, "urlopen", lambda req, timeout=0: R(b"<html>login</html>"))
    rows, note = K.fetch("KOSPI_INDEX", "20261029", "k")
    assert rows is None and "not approved" in note


def test_main_without_key_exits_2(monkeypatch, capsys):
    monkeypatch.delenv("KRX_API_KEY", raising=False)
    assert K.main(["--date", "20261029"]) == 2
