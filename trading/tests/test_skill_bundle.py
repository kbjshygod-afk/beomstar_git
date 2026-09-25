"""The skill's bundled engine must be an exact copy of trading/swing_engine."""
import importlib.util
from pathlib import Path


def _load_tool():
    p = Path(__file__).resolve().parents[1] / "tools" / "bundle_skill.py"
    spec = importlib.util.spec_from_file_location("bundle_skill", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_skill_bundle_is_identical():
    tool = _load_tool()
    assert tool.differences() == [], "run: python tools/bundle_skill.py"
