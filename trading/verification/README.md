# Engine verification

Two independent implementations of the same rules are compared bar by bar:

| File | What it is |
|---|---|
| `../swing_engine/compare_api.py` | Primary engine (pandas, vectorised), used by the skill, backtest and paper trading |
| `pine_ref.py` | Reference: pure-Python, bar-by-bar emulation of the TradingView indicator, written without looking at the primary engine |
| `gen.py` | Deterministic synthetic datasets for all five presets, with deliberate edge cases |
| `run.py` | Runs both implementations and diffs every bar, event and status label |

Run it from this directory:

```bash
python -B gen.py && python -B run.py
```

**Result on 2026-09-25:**
- 540 datasets, 492,965 bars and 7,502 events compared: **0 real mismatches**.
- The events break down as SIGNAL 2,144, ENTRY 2,125, EXIT_SIGNAL 1,178, EXIT_MA 1,167 and STOP 888.
- There were 2 floating-point ties, where both sides of a comparison are within 1e-9 relative, and 4 values that follow from them. These are not counted as mismatches.
