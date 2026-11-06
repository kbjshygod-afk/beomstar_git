#!/usr/bin/env python3
"""원가 담당(cost) checks on a MASTER-format workbook (★MASTER 원가관리표 or a season copy of it).

신메뉴_원가표 prices each slot with MATCH(재료명, 원재료DB!C:C, 0), then 베이스·크림원가!B:B, and IFERROR(...,0):
a name that is not there, an empty 정량, a material with no price or 규격, a 구분 the cup table does not know all
become 0원 without any error, and a row with no materials at all shows only the cup cost and 판정 ✓. These checks
find those inputs. They also flag 단종/검토중 materials and duplicate DB names (MATCH takes the first row).

Only typed inputs are read, never computed cells: workbooks saved by scripts carry no cached formula values.
Stdlib only, Python 3.9 (the Mac mini has no openpyxl).

    cost_check.py <workbook.xlsx>     # print the findings as JSON
"""
import io
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
SLOTS = 8
BASIS_TOGGLE = ("물류수수료", "C3")  # [매출가 기준] / [매입가 기준] / [본사부담 기준]


# ---------------------------------------------------------------- minimal xlsx reader

def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


class Book(object):
    def __init__(self, data):
        self.z = zipfile.ZipFile(io.BytesIO(data))
        self.strings = self._shared_strings()
        rels = ET.fromstring(self.z.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels.findall("pr:Relationship", NS)}
        wb = ET.fromstring(self.z.read("xl/workbook.xml"))
        self.paths = {}
        for s in wb.findall("m:sheets/m:sheet", NS):
            t = target.get(s.get("{%s}id" % NS["r"]), "")
            self.paths[s.get("name")] = t.lstrip("/") if t.startswith("/") else "xl/" + t
        self._cache = {}

    def _shared_strings(self):
        try:
            root = ET.fromstring(self.z.read("xl/sharedStrings.xml"))
        except KeyError:
            return []
        return ["".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])) for si in root.findall("m:si", NS)]

    def sheet(self, name):
        """{row: {col: value}} of typed and cached values; a formula cell without a cached value is absent."""
        if name not in self._cache:
            rows = {}
            if name in self.paths:
                for _, el in ET.iterparse(self.z.open(self.paths[name])):
                    if el.tag != "{%s}c" % NS["m"]:
                        continue
                    m = re.match(r"([A-Z]+)(\d+)$", el.get("r", ""))
                    v = self._value(el)
                    if m and v is not None:
                        rows.setdefault(int(m.group(2)), {})[col_index(m.group(1))] = v
                    el.clear()
            self._cache[name] = rows
        return self._cache[name]

    def _value(self, c):
        t = c.get("t")
        if t == "inlineStr":
            return "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
        v = c.find("m:v", NS)
        if v is None or v.text is None:
            return None
        if t == "s":
            return self.strings[int(v.text)]
        if t in ("str", "e"):
            return v.text
        if t == "b":
            return v.text == "1"
        try:
            f = float(v.text)
            return int(f) if f.is_integer() else f
        except ValueError:
            return v.text


def ref(book, sheet, a1):
    m = re.match(r"([A-Z]+)(\d+)$", a1)
    return book.sheet(sheet).get(int(m.group(2)), {}).get(col_index(m.group(1)))


# ---------------------------------------------------------------- helpers

def label(s):
    """Header text without spaces/line breaks: '판매가\\n(원)' -> '판매가(원)'."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", str(s or "")))


def loose(s):
    return label(unicodedata.normalize("NFKC", str(s or ""))).casefold()


def text(v):
    return "" if v is None else str(v).strip()


def raw(v):
    """A lookup key as MATCH sees it: spaces kept (a trailing space is a different name)."""
    return v if isinstance(v, str) else text(v)


def num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def find_header(rows, wanted, max_row=40):
    """(header row, {label: col}) of the first row that has every label in `wanted` (prefix match)."""
    for r in sorted(rows)[:max_row]:
        cells = [(label(v), c) for c, v in rows[r].items() if isinstance(v, str)]
        found = {}
        for w in wanted:
            hit = [c for lab, c in cells if lab.startswith(w)]
            if hit:
                found[w] = min(hit)
        if len(found) == len(wanted):
            return r, found
    return None, {}


# ---------------------------------------------------------------- the checks

def load_db(book):
    rows = book.sheet("원재료DB")
    hr, cols = find_header(rows, ["재료명", "순수매입가", "공급가(매출가)", "규격", "원재료상태"])
    if not hr:
        raise ValueError("원재료DB 머리글(재료명·순수 매입가·공급가·규격·원재료상태)을 찾지 못함")
    db = {}
    for r in sorted(rows):
        if r <= hr:
            continue
        name = rows[r].get(cols["재료명"])
        if not isinstance(name, str) or not name.strip():
            continue
        db.setdefault(name.casefold(), []).append({
            "row": r, "name": name, "buy": num(rows[r].get(cols["순수매입가"])), "sell": num(rows[r].get(cols["공급가(매출가)"])),
            "spec": num(rows[r].get(cols["규격"])), "status": text(rows[r].get(cols["원재료상태"]))})
    return db


def load_bases(book):
    rows = book.sheet("베이스·크림원가")
    hr, cols = find_header(rows, ["베이스명", "재료1", "g1", "총중량"])
    bases = {}
    if not hr:
        return bases
    for r in sorted(rows):
        name = rows[r].get(cols["베이스명"])
        if r <= hr or not isinstance(name, str) or not name.strip():
            continue
        parts = []
        for k in range(SLOTS):
            n, g = rows[r].get(cols["재료1"] + 2 * k), rows[r].get(cols["재료1"] + 2 * k + 1)
            if text(n) or num(g):
                parts.append((raw(n) if text(n) else "", num(g)))
        bases.setdefault(name.casefold(), {"row": r, "name": name, "parts": parts, "total": num(rows[r].get(cols["총중량"]))})
    return bases


def size_keys(book):
    keys = set()
    for sheet in ("컵·부자재원가", "디저트_포장원가"):
        rows = book.sheet(sheet)
        hr, cols = find_header(rows, ["구분표시값"])
        if hr:
            keys |= {text(rows[r].get(cols["구분표시값"])).casefold() for r in rows if r > hr and text(rows[r].get(cols["구분표시값"]))}
    return keys


def check(data):
    """xlsx bytes -> {"sheet", "basis", "rows_checked", "findings": [...]}. Raises ValueError if the layout is not MASTER's."""
    book = Book(data)
    for need in ("신메뉴_원가표", "원재료DB"):
        if need not in book.paths:
            raise ValueError("시트 없음: %s" % need)
    basis = text(ref(book, *BASIS_TOGGLE)) or "매출가 기준"
    price_key = "buy" if basis.startswith("매입가") else "sell"
    db, bases, sizes = load_db(book), load_bases(book), size_keys(book)
    rows = book.sheet("신메뉴_원가표")
    hr, cols = find_header(rows, ["메뉴명", "구분", "판매가", "재료1", "g1"])
    if not hr:
        raise ValueError("신메뉴_원가표 머리글(메뉴명·구분·판매가·재료1·g1)을 찾지 못함")
    findings, checked = [], 0

    def add(chk, sev, r, menu, size, detail=""):
        findings.append({"check": chk, "sev": sev, "row": r, "menu": menu, "size": size, "detail": detail})

    def material(name, r, menu, size, where):
        """A slot name that is not a base: registered, priced, live."""
        hits = db.get(name.casefold())
        if not hits:
            near = [d[0]["name"] for k, d in db.items() if loose(k) == loose(name)]
            near += [b["name"] for k, b in bases.items() if loose(k) == loose(name)]
            add("unregistered", "high", r, menu, size, "%s'%s'%s%s" % (
                where, name.strip(), " (앞뒤 공백)" if name != name.strip() else "", (" (DB 표기: '%s')" % near[0].strip()) if near else ""))
            return
        d = hits[0]
        if len(hits) > 1:
            add("dup_name", "medium", r, menu, size, "'%s' 원재료DB %s행 — %d행 단가 사용" % (name.strip(), "·".join(str(h["row"]) for h in hits), d["row"]))
        other = d["sell" if price_key == "buy" else "buy"]
        free = d[price_key] == 0 and other == 0  # 0 typed in both price columns = free by design (정수)
        if (not d[price_key] and not free) or not d["spec"]:
            add("price_missing", "high", r, menu, size, "%s'%s' (원재료DB %d행: %s)" % (
                where, name.strip(), d["row"], "규격 없음" if d[price_key] or free else ("%s 없음" % ("매입가" if price_key == "buy" else "공급가"))))
        if d["status"] in ("단종", "폐기"):
            add("discontinued", "high", r, menu, size, "%s'%s' %s" % (where, name.strip(), d["status"]))
        elif d["status"] in ("검토중", "테스트중"):
            add("unconfirmed", "medium", r, menu, size, "%s'%s' %s" % (where, name.strip(), d["status"]))

    for r in sorted(rows):
        menu = text(rows[r].get(cols["메뉴명"]))
        if r <= hr or not menu:
            continue
        checked += 1
        size = text(rows[r].get(cols["구분"]))
        slots = [(raw(rows[r].get(cols["재료1"] + 3 * k)), num(rows[r].get(cols["g1"] + 3 * k))) for k in range(SLOTS)]
        used = [(n if n.strip() else "", g) for n, g in slots if n.strip() or g]
        price = num(rows[r].get(cols["판매가"]))
        if not used:
            add("no_material", "high", r, menu, size)
            continue
        if not price:
            add("no_price", "medium", r, menu, size)
        if not size:
            add("size_unknown", "medium", r, menu, size, "구분 비어 있음")
        elif sizes and size.casefold() not in sizes:
            add("size_unknown", "medium", r, menu, size, "'%s'" % size)
        for n, g in used:
            if not n:
                add("name_missing", "medium", r, menu, size, "정량 %s만 있음" % g)
                continue
            if not g:
                add("qty_missing", "high", r, menu, size, "'%s'" % n.strip())
            b = bases.get(n.casefold())
            if n.casefold() in db or not b:
                material(n, r, menu, size, "")
                continue
            if not b["total"]:
                add("base_broken", "high", r, menu, size, "'%s' 총중량 없음 (베이스·크림원가 %d행)" % (n, b["row"]))
            for pn, pg in b["parts"]:
                if not pn or not pg:
                    add("base_broken", "high", r, menu, size, "'%s' 구성 %s (베이스·크림원가 %d행)" % (n, "재료명 없음" if not pn else "'%s' 정량 없음" % pn, b["row"]))
                elif pn.casefold() in db or pn.casefold() not in bases:  # a base inside a base is not followed
                    material(pn, r, menu, size, "%s 구성 " % n)
    return {"sheet": "신메뉴_원가표", "basis": basis, "rows_checked": checked, "findings": findings}


CHECKS = [  # (check, 짧은 이름, 뜻) in report order
    ("no_material", "재료 미입력", "원가가 컵원가만 잡혀 판정 ✓로 보임(검증값 아님)"),
    ("unregistered", "미등록 재료명", "원재료DB·베이스 표와 글자가 달라 원가 0원"),
    ("qty_missing", "정량 없음", "원가 0원"),
    ("price_missing", "단가·규격 없음", "원재료DB 값이 비어 원가 0원"),
    ("base_broken", "베이스 구성 오류", "베이스 단가 0원 또는 과소"),
    ("discontinued", "단종·폐기 재료", "출시 전 대체 필요"),
    ("size_unknown", "구분 오류", "컵 표에 없어 컵원가 0원"),
    ("no_price", "판매가 없음", "원가율 0%로 표시"),
    ("name_missing", "재료명 없음", "정량만 입력됨"),
    ("unconfirmed", "검토중·테스트중 재료", "SCM 미확정 단가"),
    ("dup_name", "원재료DB 중복 이름", "첫 행 단가 사용"),
]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.stderr.write(__doc__)
        sys.exit(64)
    with open(sys.argv[1], "rb") as f:
        print(json.dumps(check(f.read()), ensure_ascii=False, indent=1))
