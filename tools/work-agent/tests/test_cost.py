#!/usr/bin/env python3
"""Regression tests for cost_check.py on small synthetic MASTER-format workbooks (no company data).

Run: python3 tests/test_cost.py      Python 3.9 compatible.
"""
import io
import os
import re
import sys
import unittest
import zipfile
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import cost_check  # noqa: E402

DB_HEAD = {"A": "재료코드", "B": "업체명", "C": "재료명", "D": "면세\n(Y=면세)", "E": "순수 매입가\n(업체 VAT별도,원)",
           "F": "공급가(매출가)\n(VAT별도,원)", "G": "규격\n(g/ml/ea)", "H": "VAT포함\n순수매입가", "Q": "원재료상태"}


def col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class Formula(object):
    """A formula cell saved without a cached value, as script-written workbooks are."""


def xlsx(sheets):
    """{sheet name: {"B5": value}} -> xlsx bytes. Strings starting with '~' are written inline, others shared."""
    shared, idx = [], {}
    parts = {}
    for n, (name, cells) in enumerate(sheets.items(), 1):
        rows = {}
        for ref, v in cells.items():
            rows.setdefault(int(ref.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")), []).append((ref, v))
        xml = []
        for r in sorted(rows):
            cs = []
            for ref, v in sorted(rows[r], key=lambda x: (len(x[0]), x[0])):
                if isinstance(v, Formula):
                    cs.append('<c r="%s"><f>1+1</f></c>' % ref)
                elif isinstance(v, str) and v.startswith("~"):
                    cs.append('<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, escape(v[1:])))
                elif isinstance(v, str):
                    if v not in idx:
                        idx[v] = len(shared)
                        shared.append(v)
                    cs.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, idx[v]))
                else:
                    cs.append('<c r="%s"><v>%s</v></c>' % (ref, v))
            xml.append('<row r="%d">%s</row>' % (r, "".join(cs)))
        parts["xl/worksheets/sheet%d.xml" % n] = (
            '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData>%s</sheetData></worksheet>' % "".join(xml))
    names = list(sheets)
    parts["xl/workbook.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>%s</sheets></workbook>'
        % "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(nm), i, i) for i, nm in enumerate(names, 1)))
    parts["xl/_rels/workbook.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s'
        '</Relationships>' % "".join('<Relationship Id="rId%d" Type="worksheet" Target="worksheets/sheet%d.xml"/>' % (i, i)
                                     for i in range(1, len(names) + 1)))
    parts["xl/sharedStrings.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">%s</sst>'
        % "".join('<si><t xml:space="preserve">%s</t></si>' % escape(s) for s in shared))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in parts.items():
            z.writestr(k, v)
    return buf.getvalue()


DB = [("우유", 2000, 2500, 1000, "사용중"), ("바닐라 시럽", 9000, 12000, 1000, "사용중"), ("정수", 0, 0, 1000, "사용중"),
      ("초코 소스", 8000, 11000, 2000, "사용중")]


def master(menus, db=DB, bases=(), basis="매출가 기준", sizes=("HOT / M", "ICE / M"), extra=None):
    """menus: [(메뉴명, 구분, 판매가, [(재료명, g), ...])]; bases: [(베이스명, [(재료명, g)], 총중량)]."""
    db_cells = {"B1": "원재료 단가표"}
    db_cells.update({k + "5": v for k, v in DB_HEAD.items()})
    for i, (name, buy, sell, spec, status) in enumerate(db, 6):
        db_cells.update({"A%d" % i: "TR-%04d" % i, "B%d" % i: "업체", "C%d" % i: name, "D%d" % i: "N", "Q%d" % i: status,
                         "H%d" % i: Formula()})
        for c, v in (("E", buy), ("F", sell), ("G", spec)):
            if v is not None:
                db_cells["%s%d" % (c, i)] = v
    base_cells = {"A5": "베이스코드", "B5": "베이스명\n(대괄호 형태)", "S5": "총중량\n(g)\n※직접입력"}
    for k in range(8):
        base_cells["%s5" % col(3 + 2 * k)] = "재료%d" % (k + 1)
        base_cells["%s5" % col(4 + 2 * k)] = "g%d" % (k + 1)
    for i, (name, parts, total) in enumerate(bases, 6):
        base_cells["B%d" % i] = name
        if total is not None:
            base_cells["S%d" % i] = total
        for k, (pn, pg) in enumerate(parts):
            if pn:
                base_cells["%s%d" % (col(3 + 2 * k), i)] = pn
            if pg is not None:
                base_cells["%s%d" % (col(4 + 2 * k), i)] = pg
    cup = {"A5": "컵 코드", "E5": "구분 표시값\n(드롭다운 키)"}
    cup.update({"E%d" % i: s for i, s in enumerate(sizes, 6)})
    menu = {"B2": "신메뉴 원가표", "B5": "카테고리", "C5": "메뉴명", "D5": "구  분\n(드롭다운 선택)", "E5": "판매가\n(원)",
            "AD5": "재료원가\n합계(원)", "AF5": "물류비\n(원가포함)", "AJ5": "판정"}
    for k in range(8):
        menu["%s5" % col(6 + 3 * k)] = "재료%d" % (k + 1)
        menu["%s5" % col(7 + 3 * k)] = "g%d" % (k + 1)
        menu["%s5" % col(8 + 3 * k)] = "원가%d\n(원)" % (k + 1)
    for i, (name, size, price, slots) in enumerate(menus, 6):
        menu.update({"B%d" % i: "테스트시즌", "C%d" % i: name, "AJ%d" % i: Formula()})
        if size:
            menu["D%d" % i] = size
        if price is not None:
            menu["E%d" % i] = price
        for k, (sn, sg) in enumerate(slots):
            if sn:
                menu["%s%d" % (col(6 + 3 * k), i)] = sn
            if sg is not None:
                menu["%s%d" % (col(7 + 3 * k), i)] = sg
            menu["%s%d" % (col(8 + 3 * k), i)] = Formula()
    sheets = {"원재료DB": db_cells, "컵·부자재원가": cup, "물류수수료": {"B3": "▶ 계산 기준 선택", "C3": basis},
              "베이스·크림원가": base_cells, "신메뉴_원가표": menu}
    sheets.update(extra or {})
    return xlsx(sheets)


def found(data):
    return [(f["check"], f["row"], f["detail"]) for f in cost_check.check(data)["findings"]]


class CostCheckTests(unittest.TestCase):
    def test_clean_rows_have_no_findings(self):
        r = cost_check.check(master([("라떼", "HOT / M", 3900, [("우유", 200), ("바닐라 시럽", 20), ("정수", 30)])]))
        self.assertEqual((r["rows_checked"], r["findings"], r["basis"]), (1, [], "매출가 기준"), "정수: 0 in both prices = free")

    def test_row_without_materials_is_the_silent_pass(self):
        self.assertEqual(found(master([("라떼", "HOT / M", 3900, [("우유", 200)]), ("빈 메뉴", "ICE / M", 3900, [])])),
                         [("no_material", 7, "")])

    def test_names_must_match_the_db_exactly_but_not_by_case(self):
        rows = [("a", "HOT / M", 3900, [("~우유 ", 200)]),       # trailing space (inline string)
                ("b", "HOT / M", 3900, [("바닐라시럽", 20)]),     # spacing differs
                ("c", "HOT / M", 3900, [("없는 재료", 5)]),
                ("d", "HOT / M", 3900, [("초코 소스", 10)])]
        db = DB + [("Mex Syrup", 1, 1, 1, "사용중")]
        rows.append(("e", "HOT / M", 3900, [("MEX syrup", 10)]))   # MATCH ignores case
        self.assertEqual(found(master(rows, db=db)), [
            ("unregistered", 6, "'우유' (앞뒤 공백) (DB 표기: '우유')"),
            ("unregistered", 7, "'바닐라시럽' (DB 표기: '바닐라 시럽')"),
            ("unregistered", 8, "'없는 재료'")])

    def test_quantity_and_name_pairs(self):
        self.assertEqual(found(master([("a", "HOT / M", 3900, [("우유", None), (None, 12)])])),
                         [("qty_missing", 6, "'우유'"), ("name_missing", 6, "정량 12만 있음")])

    def test_missing_price_or_spec_but_free_by_design_is_fine(self):
        db = [("우유", 2000, None, 1000, "사용중"), ("시럽", 9000, 0, 1000, "사용중"), ("얼음", 0, 0, None, "사용중"), ("정수", 0, 0, 1000, "사용중")]
        self.assertEqual(found(master([("a", "HOT / M", 3900, [("우유", 1), ("시럽", 1), ("얼음", 1), ("정수", 1)])], db=db)), [
            ("price_missing", 6, "'우유' (원재료DB 6행: 공급가 없음)"),
            ("price_missing", 6, "'시럽' (원재료DB 7행: 공급가 없음)"),
            ("price_missing", 6, "'얼음' (원재료DB 8행: 규격 없음)")])

    def test_basis_toggle_picks_the_price_column(self):
        db = [("우유", None, 2500, 1000, "사용중")]
        self.assertEqual(found(master([("a", "HOT / M", 3900, [("우유", 1)])], db=db)), [])
        self.assertEqual(found(master([("a", "HOT / M", 3900, [("우유", 1)])], db=db, basis="매입가 기준")),
                         [("price_missing", 6, "'우유' (원재료DB 6행: 매입가 없음)")])

    def test_bases_are_followed_one_level(self):
        bases = [("[크림]", [("우유", 50), ("없는 재료", 5), ("바닐라 시럽", None)], 60), ("[빈 베이스]", [("우유", 10)], None),
                 ("[DB에도 있음]", [], None)]
        db = DB + [("[DB에도 있음]", 1, 1, 1, "사용중")]  # the sheet looks in 원재료DB first, so this base row is never used
        self.assertEqual(found(master([("a", "HOT / M", 3900, [("[크림]", 30)]), ("b", "HOT / M", 3900, [("[빈 베이스]", 30)]),
                                       ("c", "HOT / M", 3900, [("[DB에도 있음]", 30)])], db=db, bases=bases)), [
            ("unregistered", 6, "[크림] 구성 '없는 재료'"),
            ("base_broken", 6, "'[크림]' 구성 '바닐라 시럽' 정량 없음 (베이스·크림원가 6행)"),
            ("base_broken", 7, "'[빈 베이스]' 총중량 없음 (베이스·크림원가 7행)")])

    def test_material_status_and_duplicates(self):
        db = DB + [("단종 소스", 1, 1, 1, "단종"), ("새 베이스", 1, 1, 1, "검토중"), ("우유", 1, 1, 1, "사용중")]
        self.assertEqual(found(master([("a", "HOT / M", 3900, [("단종 소스", 1), ("새 베이스", 1), ("우유", 1)])], db=db)), [
            ("discontinued", 6, "'단종 소스' 단종"), ("unconfirmed", 6, "'새 베이스' 검토중"),
            ("dup_name", 6, "'우유' 원재료DB 6·12행 — 6행 단가 사용")])

    def test_price_and_size(self):
        self.assertEqual(found(master([("a", None, 3900, [("우유", 1)]), ("b", "HOT / XL", 3900, [("우유", 1)]),
                                       ("c", "ICE / M", None, [("우유", 1)])])),
                         [("size_unknown", 6, "구분 비어 있음"), ("size_unknown", 7, "'HOT / XL'"), ("no_price", 8, "")])

    def test_not_a_master_workbook(self):
        with self.assertRaises(ValueError):
            cost_check.check(xlsx({"Sheet1": {"A1": "x"}}))
        with self.assertRaises(ValueError):
            cost_check.check(master([], extra={"신메뉴_원가표": {"A1": "머리글 없음"}}))
        with self.assertRaises(Exception):
            cost_check.check(b"not a zip")

    def test_every_check_has_a_name(self):
        names = {c for c, _, _ in cost_check.CHECKS}
        with open(os.path.join(os.path.dirname(HERE), "cost_check.py")) as f:
            src = f.read()
        self.assertEqual(set(re.findall(r'add\("([a-z_]+)"', src)), names)


if __name__ == "__main__":
    unittest.main(verbosity=1)
