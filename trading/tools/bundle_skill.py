"""Copy the engine modules the skill needs into the skill folder.

    python tools/bundle_skill.py          # copy
    python tools/bundle_skill.py --check  # exit 1 if the bundled copy differs

The skill ships a copy (claude.ai uploads are self-contained zips); tests/test_skill_bundle.py
fails when the copy drifts from trading/swing_engine.
"""
import filecmp
import shutil
import sys
from pathlib import Path

TRADING = Path(__file__).resolve().parents[1]
SRC = TRADING / "swing_engine"
DST = TRADING.parent / "skills-library" / "trading" / "swing-scanner-rules" / "scripts" / "swing_engine"
MODULES = ["__init__.py", "analyze.py", "compare_api.py", "data.py", "indicators.py", "notes.py",
           "params.py", "sizing.py", "state.py", "status.py"]


def differences() -> list[str]:
    out = []
    for m in MODULES:
        a, b = SRC / m, DST / m
        if not b.exists() or not filecmp.cmp(a, b, shallow=False):
            out.append(m)
    extra = sorted(p.name for p in DST.glob("*.py") if p.name not in MODULES) if DST.exists() else []
    return out + [f"extra:{e}" for e in extra]


def main() -> int:
    if "--check" in sys.argv:
        diff = differences()
        print("bundle differs: " + ", ".join(diff) if diff else "bundle is identical")
        return 1 if diff else 0
    DST.mkdir(parents=True, exist_ok=True)
    for m in MODULES:
        shutil.copy2(SRC / m, DST / m)
    print(f"copied {len(MODULES)} modules to {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
