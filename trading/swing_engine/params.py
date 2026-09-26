"""Market presets and rule parameters (SPEC section 2).

`resolve(preset, **overrides)` returns a flat dict with exactly the parameter keys
of the comparison interface (COMPARE_API.md) plus `benchmark` (Yahoo ticker) and
`integer_shares`. `compare_api.compute` never looks presets up itself.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

# Keys consumed by compare_api.compute (COMPARE_API.md, "params").
COMPARE_KEYS = (
    "stop_pct", "cap_on", "year_bars", "regime_mode",
    "pivot_len", "vol_len", "vol_mult", "max_breakout_pct", "use_tt",
    "ma200_rise_bars", "rs_min_diff", "exit_ma_len",
    "use_value_filter", "min_trading_value",
)
EXTRA_KEYS = ("benchmark", "integer_shares")
PARAM_KEYS = COMPARE_KEYS + EXTRA_KEYS

REGIME_MODES = ("MA200", "MA200_AND_MA20", "NONE")

# Not part of the signal rules, used by sizing / portfolio (SPEC 2, 7, 8.4).
RISK_PCT = 0.75          # % of equity risked per trade
COST_PCT = 0.2           # % of traded value per side
RS_PERCENTILE_MIN = 70.0  # portfolio percentile rule (SPEC 8.2)


@dataclass(frozen=True)
class RuleDefaults:
    """Market-independent defaults (SPEC 2 table; Pine indicator inputs lines 32-50)."""
    pivot_len: int = 20            # estimated (SPEC 9 #1)
    vol_len: int = 50              # estimated (SPEC 9 #2)
    vol_mult: float = 1.4
    max_breakout_pct: float = 15.0
    use_tt: bool = True
    ma200_rise_bars: int = 22      # estimated (SPEC 9 #5)
    rs_min_diff: float = 0.0       # estimated (SPEC 9 #3)
    exit_ma_len: int = 50
    use_value_filter: bool = False
    min_trading_value: float = 3e9


@dataclass(frozen=True)
class MarketPreset:
    """One row of the SPEC 2 'Market presets' table."""
    name: str
    label_ko: str
    benchmark: str        # Yahoo ticker
    benchmark_tv: str     # TradingView symbol used by the Pine script
    regime_mode: str
    stop_pct: float
    cap_on: bool
    year_bars: int
    integer_shares: bool  # whole shares (Korean stocks); fractional otherwise
    currency: str


PRESETS: dict[str, MarketPreset] = {
    "SP500": MarketPreset("SP500", "S&P500", "^GSPC", "SP:SPX", "MA200", 10.0, True, 252, False, "USD"),
    "NDX100": MarketPreset("NDX100", "나스닥100", "^NDX", "NASDAQ:NDX", "MA200", 7.0, True, 252, False, "USD"),
    "KOSPI": MarketPreset("KOSPI", "코스피", "^KS11", "KRX:KOSPI", "MA200_AND_MA20", 7.0, True, 252, True, "KRW"),
    "KOSDAQ": MarketPreset("KOSDAQ", "코스닥", "^KQ11", "KRX:KOSDAQ", "NONE", 10.0, True, 252, True, "KRW"),
    # Chase cap is OFF for crypto (Pine line 85: capOn = not isCrypto); a year is 365 bars.
    "CRYPTO": MarketPreset("CRYPTO", "크립토", "BTC-USD", "BINANCE:BTCUSDT", "MA200", 10.0, False, 365, False, "USD"),
    # CUSTOM starts from the Pine `custom*` input defaults (lines 25-29) and is meant to be overridden.
    "CUSTOM": MarketPreset("CUSTOM", "직접 설정", "^GSPC", "SP:SPX", "MA200", 10.0, True, 252, False, "USD"),
}

BENCHMARKS = {k: v.benchmark for k, v in PRESETS.items()}

_ALIASES = {
    "SP500": "SP500", "S&P500": "SP500", "SPX": "SP500", "S&P 500": "SP500",
    "NDX100": "NDX100", "NDX": "NDX100", "NASDAQ100": "NDX100", "NASDAQ-100": "NDX100", "나스닥100": "NDX100",
    "KOSPI": "KOSPI", "코스피": "KOSPI",
    "KOSDAQ": "KOSDAQ", "코스닥": "KOSDAQ",
    "CRYPTO": "CRYPTO", "크립토": "CRYPTO",
    "CUSTOM": "CUSTOM", "직접 설정": "CUSTOM",
}

_REGIME_ALIASES = {
    "MA200": "MA200", "200일선": "MA200",
    "MA200_AND_MA20": "MA200_AND_MA20", "200일선+20일선": "MA200_AND_MA20",
    "NONE": "NONE", "무필터": "NONE",
}

_INT_KEYS = {"pivot_len", "vol_len", "year_bars", "ma200_rise_bars", "exit_ma_len"}
_FLOAT_KEYS = {"stop_pct", "vol_mult", "max_breakout_pct", "rs_min_diff", "min_trading_value"}
_BOOL_KEYS = {"cap_on", "use_tt", "use_value_filter", "integer_shares"}


def normalize_preset(name: str) -> str:
    key = str(name).strip()
    for cand in (key, key.upper()):
        if cand in _ALIASES:
            return _ALIASES[cand]
    raise ValueError(f"unknown market preset {name!r}; expected one of {sorted(PRESETS)}")


def get_preset(name: str) -> MarketPreset:
    return PRESETS[normalize_preset(name)]


def normalize_regime(mode: str) -> str:
    key = str(mode).strip()
    for cand in (key, key.upper()):
        if cand in _REGIME_ALIASES:
            return _REGIME_ALIASES[cand]
    raise ValueError(f"unknown regime_mode {mode!r}; expected one of {REGIME_MODES}")


def _to_bool(v) -> bool:
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "y", "on"):
            return True
        if s in ("0", "false", "no", "n", "off"):
            return False
        raise ValueError(f"not a boolean: {v!r}")
    return bool(v)


def _coerce(key: str, value):
    if key in _INT_KEYS:
        iv = int(value)
        if iv != float(value) or iv < 1:
            raise ValueError(f"{key} must be a positive integer, got {value!r}")
        return iv
    if key in _FLOAT_KEYS:
        return float(value)
    if key in _BOOL_KEYS:
        return _to_bool(value)
    if key == "regime_mode":
        return normalize_regime(value)
    if key == "benchmark":
        return str(value)
    raise KeyError(key)


def resolve(preset: str = "SP500", **overrides) -> dict:
    """Fully resolved parameter dict for `preset` with optional overrides.

    Keys are exactly PARAM_KEYS. Overrides whose value is None are ignored (handy for
    CLI flags that were not given). Unknown keys raise ValueError.
    """
    p = get_preset(preset)
    out = asdict(RuleDefaults())
    out.update(
        stop_pct=p.stop_pct, cap_on=p.cap_on, year_bars=p.year_bars, regime_mode=p.regime_mode,
        benchmark=p.benchmark, integer_shares=p.integer_shares,
    )
    unknown = sorted(set(overrides) - set(PARAM_KEYS))
    if unknown:
        raise ValueError(f"unknown parameter(s): {unknown}")
    for k, v in overrides.items():
        if v is None:
            continue
        out[k] = _coerce(k, v)
    if not (0 < out["stop_pct"] < 100):
        raise ValueError("stop_pct must be between 0 and 100")
    return {k: out[k] for k in PARAM_KEYS}
