#!/usr/bin/env python3
"""Build pixel/layout-office.json: the Pixel Agents default office with one painted Area per desk.

Usage: python3 pixel/make_layout.py [base-layout.json] [out.json]
Base = Pixel Agents' bundled default layout (dist/assets/default-layout-1.json, MIT). Its six seats:
benches (3,14) (7,14) at the two front desks, chairs (3,16) (3,18) (7,16) (7,18) at the side tables.
Areas are painted on floor tiles only (never void 255 or wall 0). Python 3.9 compatible.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VOID, WALL = 255, 0

# label, color (#rrggbb), seat tile, painted block (col0, row0, col1, row1 inclusive)
AREAS = [
    ("요청 비서", "#d8b38a", (3, 14), (2, 12, 4, 15)),
    ("신메뉴 게이트 담당", "#9fc5e8", (7, 14), (6, 12, 8, 15)),
    ("공지·문서 담당", "#c9b6e4", (3, 16), (1, 16, 3, 17)),
    ("원가 담당", "#b7d7a8", (3, 18), (1, 18, 3, 19)),
    ("사무 보조", "#e2c4c4", (7, 16), (6, 16, 8, 17)),
]


def build(base):
    cols, rows, tiles = base["cols"], base["rows"], base["tiles"]
    layout = dict(base)
    layout["areas"] = [{"label": a[0], "color": a[1]} for a in AREAS]
    area_tiles = [None] * len(tiles)
    for label, _, seat, (c0, r0, c1, r1) in AREAS:
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                i = r * cols + c
                if 0 <= c < cols and 0 <= r < rows and tiles[i] not in (VOID, WALL):
                    area_tiles[i] = label
        si = seat[1] * cols + seat[0]
        if area_tiles[si] != label:
            raise SystemExit("seat %s of %s is not on a floor tile" % (seat, label))
    layout["areaTiles"] = area_tiles
    layout["layoutRevision"] = int(base.get("layoutRevision", 1)) + 1
    return layout


def main(argv):
    base_path = argv[1] if len(argv) > 1 else os.path.join(HERE, "base-layout.json")
    out_path = argv[2] if len(argv) > 2 else os.path.join(HERE, "layout-office.json")
    with open(base_path) as f:
        base = json.load(f)
    layout = build(base)
    with open(out_path, "w") as f:
        json.dump(layout, f, ensure_ascii=False, separators=(",", ":"))
    painted = sum(1 for x in layout["areaTiles"] if x)
    print("wrote %s: %d areas, %d painted tiles" % (out_path, len(layout["areas"]), painted))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
